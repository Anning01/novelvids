import { defineStore } from 'pinia'
import { api, sleep } from '@/api'
import { notice } from '@/shared/notice'
import type { Asset, Chapter, EnumItem, Scene, Video } from '@/types'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import type { Point, WorkbenchEdge, WorkbenchNode, WorkbenchViewport } from '../types/workbenchTypes'

interface HistorySnapshot { positions: Record<string, Point>; ui: Record<string, Record<string, unknown>> }
const terminal = new Set([TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED])
const now = () => new Date().toISOString()

function node(id: number, key: string, kind: WorkbenchNode['kind'], title: string, position: Point, data: Record<string, unknown>): WorkbenchNode {
  const timestamp = now()
  return { id, key, kind, backendKind: kind, title, position, size: null, zIndex: 1, activeVersionId: null, status: 'ready', data, createdAt: timestamp, updatedAt: timestamp }
}
function edge(id: number, key: string, source: string, target: string, type: WorkbenchEdge['type'], orderIndex = 0): WorkbenchEdge {
  const timestamp = now()
  return { id, key, source, target, type, backendType: type, sourceHandle: null, targetHandle: null, orderIndex, config: null, createdAt: timestamp, updatedAt: timestamp }
}

export const useWorkbenchStore = defineStore('novel-workbench', {
  state: () => ({
    loading: false,
    chapterId: 0,
    novelId: 0,
    chapter: null as Chapter | null,
    assets: [] as Asset[],
    scenes: [] as Scene[],
    videos: {} as Record<number, Video[]>,
    modelOptions: [] as EnumItem[],
    nodes: [] as WorkbenchNode[],
    edges: [] as WorkbenchEdge[],
    selectedNodeKeys: [] as string[],
    selectedEdgeKeys: [] as string[],
    clipboardNode: null as WorkbenchNode | null,
    history: [] as HistorySnapshot[],
    future: [] as HistorySnapshot[],
    busySceneIds: [] as number[],
    viewport: { x: 40, y: 40, zoom: 0.4 } as WorkbenchViewport,
  }),
  getters: {
    canUndo: state => state.history.length > 0,
    canRedo: state => state.future.length > 0,
  },
  actions: {
    nodeByKey(key: string) { return this.nodes.find(item => item.key === key) },
    layoutKey() { return `novelvids:canvas:${this.chapterId}:layout:v1` },
    capture(): HistorySnapshot {
      return {
        positions: Object.fromEntries(this.nodes.map(item => [item.key, { ...item.position }])),
        ui: Object.fromEntries(this.nodes.map(item => [item.key, { ...((item.data.ui as Record<string, unknown>) || {}) }])),
      }
    },
    restore(snapshot: HistorySnapshot) {
      this.nodes.forEach((item) => {
        if (snapshot.positions[item.key]) item.position = { ...snapshot.positions[item.key] }
        item.data.ui = { ...(snapshot.ui[item.key] || {}) }
      })
      this.persistLayout()
    },
    checkpoint() { this.history.push(this.capture()); if (this.history.length > 60) this.history.shift(); this.future = [] },
    undo() { const previous = this.history.pop(); if (!previous) return; this.future.push(this.capture()); this.restore(previous) },
    redo() { const next = this.future.pop(); if (!next) return; this.history.push(this.capture()); this.restore(next) },
    persistLayout() {
      localStorage.setItem(this.layoutKey(), JSON.stringify({
        viewport: this.viewport,
        nodes: Object.fromEntries(this.nodes.map(item => [item.key, { position: item.position, zIndex: item.zIndex, ui: item.data.ui || {} }])),
      }))
    },
    loadSavedLayout() {
      try {
        const saved = JSON.parse(localStorage.getItem(this.layoutKey()) || '{}') as { viewport?: WorkbenchViewport; nodes?: Record<string, { position: Point; zIndex: number; ui: Record<string, unknown> }> }
        if (saved.viewport) this.viewport = saved.viewport
        this.nodes.forEach((item) => {
          const value = saved.nodes?.[item.key]
          if (value) { item.position = value.position; item.zIndex = value.zIndex; item.data.ui = value.ui }
        })
      } catch { /* ignore invalid local layout */ }
    },
    async load(novelId: number, chapterId: number) {
      this.loading = true; this.novelId = novelId; this.chapterId = chapterId
      try {
        const [chapterResponse, assetsResponse, scenesResponse, enumsResponse] = await Promise.all([api.chapter(chapterId), api.assets(novelId), api.scenes(chapterId), api.enums()])
        this.chapter = chapterResponse.data
        this.assets = assetsResponse.data.items
        this.scenes = await Promise.all(scenesResponse.data.items.map(async item => (await api.scene(item.id)).data))
        this.modelOptions = enumsResponse.data.video_model_type || []
        const entries = await Promise.all(this.scenes.map(async item => [item.id, (await api.videos(item.id)).data.items] as const))
        this.videos = Object.fromEntries(entries)
        this.rebuildGraph()
        this.loadSavedLayout()
      } finally { this.loading = false }
    },
    rebuildGraph() {
      if (!this.chapter) return
      const nodes: WorkbenchNode[] = [node(this.chapter.id, 'chapter', 'chapter', `第 ${this.chapter.number} 章 · ${this.chapter.name}`, { x: 80, y: 80 }, { chapter: this.chapter, layout_family: 'chapter', layout_lane: 'chapter' })]
      const edges: WorkbenchEdge[] = []
      this.assets.forEach((asset, index) => nodes.push(node(asset.id, `asset-${asset.id}`, 'asset', asset.canonical_name, { x: 480, y: index * 320 }, { asset, asset_type: ({ [AssetTypeEnum.PERSON]: 'character', [AssetTypeEnum.SCENE]: 'scene', [AssetTypeEnum.ITEM]: 'object' } as Record<number, string>)[asset.asset_type], layout_family: 'asset', ui: {}, index })))
      this.scenes.forEach((scene, index) => {
        const sceneKey = `shot-${scene.id}`
        nodes.push(node(scene.id, sceneKey, 'shot', `镜头 ${String(scene.sequence).padStart(2, '0')}`, { x: 900, y: index * 520 }, { scene, videos: this.videos[scene.id] || [], modelOptions: this.modelOptions, shot_index: scene.sequence, layout_family: 'shot', ui: {} }))
        edges.push(edge(100000 + scene.id, `chapter-${sceneKey}`, 'chapter', sceneKey, 'shot_sequence', index))
        ;(scene.asset_ids || []).forEach(assetId => edges.push(edge(200000 + scene.id * 1000 + assetId, `asset-${assetId}-${sceneKey}`, `asset-${assetId}`, sceneKey, 'asset_reference')))
        const latest = this.videos[scene.id]?.[0]
        if (latest) {
          const resultKey = `video-${latest.id}`
          nodes.push(node(latest.id, resultKey, 'video_result', `视频结果 · #${latest.id}`, { x: 1400, y: index * 520 }, { video: latest, sceneId: scene.id, layout_family: 'result', ui: {} }))
          edges.push(edge(300000 + latest.id, `${sceneKey}-${resultKey}`, sceneKey, resultKey, 'output_binding'))
        }
      })
      const old = new Map(this.nodes.map(item => [item.key, item]))
      this.nodes = nodes.map(item => old.has(item.key) ? { ...item, position: old.get(item.key)!.position, zIndex: old.get(item.key)!.zIndex, data: { ...item.data, ui: old.get(item.key)!.data.ui } } : item)
      this.edges = edges
    },
    selectNode(key: string, additive = false) { this.selectedNodeKeys = additive ? [...new Set([...this.selectedNodeKeys, key])] : [key]; this.selectedEdgeKeys = [] },
    clearSelection() { this.selectedNodeKeys = []; this.selectedEdgeKeys = [] },
    updateNodeLayout(key: string, position: Point, _size?: unknown, zIndex?: number) { const item = this.nodeByKey(key); if (!item) return; item.position = position; if (zIndex !== undefined) item.zIndex = zIndex },
    updateNodeUi(key: string, ui: Record<string, unknown>) { const item = this.nodeByKey(key); if (item) item.data.ui = ui; this.persistLayout() },
    async flushLayout() { this.persistLayout() },
    copySelection() { const key = this.selectedNodeKeys[0]; const item = key ? this.nodeByKey(key) : null; this.clipboardNode = item?.kind === 'shot' ? structuredClone(item) : null },
    async paste() {
      if (!this.clipboardNode || this.clipboardNode.kind !== 'shot') return
      const source = this.clipboardNode.data.scene as Scene
      const created = (await api.createScene({ chapter_id: this.chapterId, sequence: Math.max(0, ...this.scenes.map(item => item.sequence)) + 1, description: source.description, prompt: source.prompt || '', duration: source.duration, asset_ids: source.asset_ids })).data
      this.scenes.push(created); this.videos[created.id] = []; this.rebuildGraph()
      const item = this.nodeByKey(`shot-${created.id}`); if (item) item.position = { x: this.clipboardNode.position.x + 48, y: this.clipboardNode.position.y + 48 }
      notice.success('已复制镜头')
    },
    async deleteSelection() {
      const shots = this.selectedNodeKeys.map(key => this.nodeByKey(key)).filter(item => item?.kind === 'shot') as WorkbenchNode[]
      await Promise.all(shots.map(item => api.deleteScene(item.id)))
      this.scenes = this.scenes.filter(item => !shots.some(nodeItem => nodeItem.id === item.id)); this.clearSelection(); this.rebuildGraph()
      if (shots.length) notice.success(`已删除 ${shots.length} 个镜头`)
    },
    async saveScene(sceneId: number, patch: Partial<Scene>) {
      const updated = (await api.updateScene(sceneId, patch)).data
      this.scenes = this.scenes.map(item => item.id === sceneId ? updated : item); this.rebuildGraph(); notice.success('镜头已保存')
    },
    async addShot(position?: Point) {
      const created = (await api.createScene({ chapter_id: this.chapterId, sequence: Math.max(0, ...this.scenes.map(item => item.sequence)) + 1, description: '新镜头', prompt: '', duration: 6 })).data
      this.scenes.push(created); this.videos[created.id] = []; this.rebuildGraph()
      const item = this.nodeByKey(`shot-${created.id}`); if (item && position) item.position = position
      notice.success('已添加镜头')
    },
    async generateScenes() {
      const task = (await api.generateScenes(this.chapterId)).data
      let current = task
      while (!terminal.has(current.status)) { await sleep(2500); current = (await api.task(task.id)).data }
      if (current.status !== TaskStatusEnum.COMPLETED) throw new Error(current.error_message || '分镜生成失败')
      await this.load(this.novelId, this.chapterId); notice.success('分镜生成完成')
    },
    async generateVideo(sceneId: number, modelType: number) {
      if (!this.busySceneIds.includes(sceneId)) this.busySceneIds.push(sceneId)
      try {
        let video = (await api.generateVideo(sceneId, modelType)).data
        this.videos[sceneId] = [video, ...(this.videos[sceneId] || [])]; this.rebuildGraph()
        while (!terminal.has(video.status)) { await sleep(4000); video = (await api.queryVideo(video.id)).data; this.videos[sceneId] = this.videos[sceneId].map(item => item.id === video.id ? video : item); this.rebuildGraph() }
        video.status === TaskStatusEnum.COMPLETED ? notice.success('视频生成完成') : notice.error(String(video.metadata?.error || '视频生成失败'))
      } finally { this.busySceneIds = this.busySceneIds.filter(id => id !== sceneId); this.rebuildGraph() }
    },
    async refreshVideo(videoId: number) {
      const updated = (await api.queryVideo(videoId)).data
      this.videos[updated.scene_id] = (this.videos[updated.scene_id] || []).map(item => item.id === updated.id ? updated : item); this.rebuildGraph()
    },
  },
})
