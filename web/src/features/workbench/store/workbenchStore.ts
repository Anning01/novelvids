import { defineStore } from 'pinia'
import { api, sleep } from '@/api'
import { notice } from '@/shared/notice'
import type { Asset, AudioReference, Chapter, DigitalHuman, EnumItem, Scene, Video } from '@/types'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import type { NodeSize, Point, WorkbenchEdge, WorkbenchNode, WorkbenchViewport } from '../types/workbenchTypes'
import { sceneAssetIds } from '../graph/sceneAssets'

interface HistorySnapshot {
  nodes: Record<string, { position: Point; size: NodeSize | null; zIndex: number; ui: Record<string, unknown> }>
  manualNodes: WorkbenchNode[]
  mediaEdges: WorkbenchEdge[]
  viewport: WorkbenchViewport
}
interface SavedCanvasState {
  viewport?: WorkbenchViewport
  nodes?: Record<string, { position: Point; size?: NodeSize | null; zIndex: number; ui: Record<string, unknown> }>
  manualNodes?: WorkbenchNode[]
  mediaNodes?: WorkbenchNode[]
  mediaEdges?: WorkbenchEdge[]
}
const manualNodeKinds = new Set<WorkbenchNode['kind']>(['audio_reference', 'digital_human', 'section', 'note'])
const terminal = new Set([TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED])
const now = () => new Date().toISOString()
const cloneValue = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

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
    busyAssetIds: [] as number[],
    manualNodes: [] as WorkbenchNode[],
    mediaEdges: [] as WorkbenchEdge[],
    viewport: { x: 0, y: 0, zoom: 1 } as WorkbenchViewport,
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
        nodes: Object.fromEntries(this.nodes.map(item => [item.key, {
          position: { ...item.position }, size: item.size ? { ...item.size } : null, zIndex: item.zIndex,
          ui: { ...((item.data.ui as Record<string, unknown>) || {}) },
        }])),
        manualNodes: cloneValue(this.nodes.filter(item => manualNodeKinds.has(item.kind))),
        mediaEdges: cloneValue(this.edges.filter(item => item.key.startsWith('media-edge-'))),
        viewport: { ...this.viewport },
      }
    },
    restore(snapshot: HistorySnapshot) {
      const automaticNodes = this.nodes.filter(item => !manualNodeKinds.has(item.kind))
      this.manualNodes = cloneValue(snapshot.manualNodes)
      this.nodes = [...automaticNodes, ...this.manualNodes]
      this.nodes.forEach((item) => {
        const saved = snapshot.nodes[item.key]
        if (!saved) return
        item.position = { ...saved.position }; item.size = saved.size ? { ...saved.size } : null; item.zIndex = saved.zIndex
        item.data.ui = { ...saved.ui }
      })
      const automaticEdges = this.edges.filter(item => !item.key.startsWith('media-edge-'))
      this.mediaEdges = cloneValue(snapshot.mediaEdges)
      this.edges = [...automaticEdges, ...this.mediaEdges.filter(item => this.nodeByKey(item.source) && this.nodeByKey(item.target))]
      this.selectedNodeKeys = this.selectedNodeKeys.filter(key => Boolean(this.nodeByKey(key)))
      this.selectedEdgeKeys = this.selectedEdgeKeys.filter(key => this.edges.some(item => item.key === key))
      this.viewport = { ...snapshot.viewport }
      this.persistLayout()
    },
    checkpoint() {
      const snapshot = this.capture()
      const previous = this.history.at(-1)
      this.future = []
      if (previous && JSON.stringify(previous) === JSON.stringify(snapshot)) return
      this.history.push(snapshot)
      if (this.history.length > 60) this.history.shift()
    },
    undo() { const previous = this.history.at(-1); if (!previous) return false; const current = this.capture(); this.restore(previous); this.history.pop(); this.future.push(current); return true },
    redo() { const next = this.future.at(-1); if (!next) return false; const current = this.capture(); this.restore(next); this.future.pop(); this.history.push(current); return true },
    persistLayout() {
      localStorage.setItem(this.layoutKey(), JSON.stringify({
        viewport: this.viewport,
        nodes: Object.fromEntries(this.nodes.map(item => [item.key, { position: item.position, size: item.size, zIndex: item.zIndex, ui: item.data.ui || {} }])),
        manualNodes: this.nodes.filter(item => manualNodeKinds.has(item.kind)),
        mediaEdges: this.edges.filter(item => item.key.startsWith('media-edge-')),
      }))
    },
    loadSavedLayout() {
      try {
        const saved = JSON.parse(localStorage.getItem(this.layoutKey()) || '{}') as SavedCanvasState
        if (saved.viewport) this.viewport = saved.viewport
        this.manualNodes = (saved.manualNodes || saved.mediaNodes || []).filter(item => manualNodeKinds.has(item.kind))
        this.mediaEdges = (saved.mediaEdges || []).filter(item => item.key.startsWith('media-edge-'))
        this.nodes.push(...this.manualNodes.filter(item => !this.nodes.some(current => current.key === item.key)))
        this.edges.push(...this.mediaEdges.filter(item => !this.edges.some(current => current.key === item.key)))
        this.nodes.forEach((item) => {
          const value = saved.nodes?.[item.key]
          if (value) { item.position = value.position; if (value.size !== undefined) item.size = value.size; item.zIndex = value.zIndex; item.data.ui = value.ui }
        })
      } catch { /* ignore invalid local layout */ }
    },
    async load(novelId: number, chapterId: number) {
      this.loading = true; this.novelId = novelId; this.chapterId = chapterId
      this.nodes = []; this.edges = []; this.manualNodes = []; this.mediaEdges = []; this.history = []; this.future = []; this.busyAssetIds = []; this.busySceneIds = []; this.viewport = { x: 0, y: 0, zoom: 1 }; this.clearSelection()
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
        sceneAssetIds(scene).forEach(assetId => edges.push(edge(200000 + scene.id * 1000 + assetId, `asset-${assetId}-${sceneKey}`, `asset-${assetId}`, sceneKey, 'asset_reference')))
        const latest = this.videos[scene.id]?.[0]
        if (latest) {
          const resultKey = `video-${latest.id}`
          nodes.push(node(latest.id, resultKey, 'video_result', `视频结果 · #${latest.id}`, { x: 1400, y: index * 520 }, { video: latest, sceneId: scene.id, layout_family: 'result', ui: {} }))
          edges.push(edge(300000 + latest.id, `${sceneKey}-${resultKey}`, sceneKey, resultKey, 'output_binding'))
        }
      })
      const old = new Map(this.nodes.map(item => [item.key, item]))
      this.nodes = nodes.map(item => old.has(item.key) ? { ...item, position: old.get(item.key)!.position, size: old.get(item.key)!.size, zIndex: old.get(item.key)!.zIndex, data: { ...item.data, ui: old.get(item.key)!.data.ui } } : item)
      this.manualNodes = [...old.values()].filter(item => manualNodeKinds.has(item.kind))
      this.nodes.push(...this.manualNodes)
      this.edges = [...edges, ...this.mediaEdges.filter(item => this.nodes.some(nodeItem => nodeItem.key === item.source) && this.nodes.some(nodeItem => nodeItem.key === item.target))]
    },
    selectNode(key: string, additive = false) {
      this.selectedNodeKeys = additive
        ? this.selectedNodeKeys.includes(key) ? this.selectedNodeKeys.filter(item => item !== key) : [...this.selectedNodeKeys, key]
        : [key]
      this.selectedEdgeKeys = []
    },
    clearSelection() { this.selectedNodeKeys = []; this.selectedEdgeKeys = [] },
    updateNodeLayout(key: string, position: Point, size?: NodeSize | null, zIndex?: number) { const item = this.nodeByKey(key); if (!item) return; item.position = position; if (size !== undefined) item.size = size; if (zIndex !== undefined) item.zIndex = zIndex },
    updateNodeUi(key: string, ui: Record<string, unknown>) { const item = this.nodeByKey(key); if (item) item.data.ui = ui; this.persistLayout() },
    updateManualNodeData(key: string, patch: Record<string, unknown>) {
      const item = this.nodeByKey(key)
      if (!item || !manualNodeKinds.has(item.kind)) return
      item.data = { ...item.data, ...patch }
      this.manualNodes = this.nodes.filter(nodeItem => manualNodeKinds.has(nodeItem.kind))
    },
    async flushLayout() { this.persistLayout() },
    copySelection() { const key = this.selectedNodeKeys[0]; const item = key ? this.nodeByKey(key) : null; this.clipboardNode = item && ['shot', 'note'].includes(item.kind) ? cloneValue(item) : null },
    async paste() {
      if (!this.clipboardNode) return
      if (this.clipboardNode.kind === 'note') {
        const created = this.addNote({ x: this.clipboardNode.position.x + 48, y: this.clipboardNode.position.y + 48 })
        created.data = { ...created.data, content: this.clipboardNode.data.content || '', color: this.clipboardNode.data.color || '#8d793d' }
        this.persistLayout(); notice.success('已复制便签'); return
      }
      if (this.clipboardNode.kind !== 'shot') return
      const source = this.clipboardNode.data.scene as Scene
      const created = (await api.createScene({ chapter_id: this.chapterId, sequence: Math.max(0, ...this.scenes.map(item => item.sequence)) + 1, description: source.description, prompt: source.prompt || '', duration: source.duration, asset_ids: sceneAssetIds(source) })).data
      this.scenes.push(created); this.videos[created.id] = []; this.rebuildGraph()
      const item = this.nodeByKey(`shot-${created.id}`); if (item) item.position = { x: this.clipboardNode.position.x + 48, y: this.clipboardNode.position.y + 48 }
      notice.success('已复制镜头')
    },
    async deleteSelection() {
      const shots = this.selectedNodeKeys.map(key => this.nodeByKey(key)).filter(item => item?.kind === 'shot') as WorkbenchNode[]
      const removableKeys = new Set(this.selectedNodeKeys.filter(key => {
        const kind = this.nodeByKey(key)?.kind
        return Boolean(kind && manualNodeKinds.has(kind))
      }))
      if (removableKeys.size) this.checkpoint()
      await Promise.all(shots.map(item => api.deleteScene(item.id)))
      this.scenes = this.scenes.filter(item => !shots.some(nodeItem => nodeItem.id === item.id))
      this.manualNodes = this.manualNodes.filter(item => !removableKeys.has(item.key))
      this.manualNodes.filter(item => item.kind === 'section').forEach((section) => {
        const keys = Array.isArray(section.data.node_keys) ? section.data.node_keys.filter((key): key is string => typeof key === 'string') : []
        section.data.node_keys = keys.filter(key => !removableKeys.has(key))
      })
      this.mediaEdges = this.mediaEdges.filter(item => !removableKeys.has(item.source) && !removableKeys.has(item.target))
      this.nodes = this.nodes.filter(item => !removableKeys.has(item.key))
      this.edges = this.edges.filter(item => !removableKeys.has(item.source) && !removableKeys.has(item.target))
      this.clearSelection(); this.rebuildGraph(); this.persistLayout()
      const removed = shots.length + removableKeys.size
      if (removed) notice.success(`已删除 ${removed} 个节点`)
    },
    addMediaNode(kind: 'audio_reference' | 'digital_human') {
      this.checkpoint()
      const stamp = Date.now()
      const key = `${kind}-${stamp}`
      const item = node(-stamp, key, kind, kind === 'audio_reference' ? '参考音频' : '数字人', { x: 520, y: 120 + this.manualNodes.length * 340 }, {
        resource: null,
        asset_type: kind === 'audio_reference' ? 'audio' : 'digital_human',
        layout_family: 'asset',
        layout_lane: kind === 'audio_reference' ? 'asset:audio' : 'asset:digital-human',
        ui: {},
      })
      this.manualNodes.push(item); this.nodes.push(item); this.selectNode(key); this.persistLayout()
    },
    setMediaResource(key: string, resource: AudioReference | DigitalHuman) {
      const item = this.nodeByKey(key)
      if (!item || (item.kind !== 'audio_reference' && item.kind !== 'digital_human')) return
      this.checkpoint()
      item.data.resource = resource
      item.title = item.kind === 'audio_reference' && 'nickname' in resource ? resource.nickname : 'occupation' in resource ? `${resource.country} · ${resource.occupation}` : item.title
      this.manualNodes = this.nodes.filter(nodeItem => manualNodeKinds.has(nodeItem.kind))
      this.persistLayout()
      notice.success(item.kind === 'audio_reference' ? '参考音频已选择' : '数字人已选择')
    },
    addNote(position?: Point) {
      this.checkpoint()
      const stamp = Date.now(); const key = `note-${stamp}`
      const item = node(-stamp, key, 'note', '便签', position || { x: 560, y: 120 + this.manualNodes.length * 260 }, { content: '', color: '#8d793d', layout_family: 'note', ui: {} })
      item.size = { width: 320, height: 220 }
      this.manualNodes.push(item); this.nodes.push(item); this.selectNode(key); this.persistLayout()
      return item
    },
    addSection(memberKeys: string[], position: Point, size: NodeSize, color: string) {
      const stamp = Date.now(); const key = `section-${stamp}`
      const count = this.nodes.filter(item => item.kind === 'section').length + 1
      const memberZ = memberKeys.map(keyValue => this.nodeByKey(keyValue)?.zIndex ?? 1)
      const item = node(-stamp, key, 'section', `分区 ${count}`, position, { color, description: '', node_keys: memberKeys, layout_family: 'section', ui: {} })
      item.size = size; item.zIndex = Math.min(-1, ...memberZ.map(value => value - 1))
      this.manualNodes.push(item); this.nodes.push(item); this.selectNode(key); this.persistLayout()
      return item
    },
    connectMediaNode(source: string, target: string) {
      const sourceNode = this.nodeByKey(source); const targetNode = this.nodeByKey(target)
      if (!sourceNode || !targetNode || targetNode.kind !== 'shot' || (sourceNode.kind !== 'audio_reference' && sourceNode.kind !== 'digital_human')) return
      if (this.mediaEdges.some(item => item.source === source && item.target === target)) return
      this.checkpoint()
      const stamp = Date.now()
      const item = edge(-stamp, `media-edge-${stamp}`, source, target, 'asset_reference')
      this.mediaEdges.push(item); this.edges.push(item); this.persistLayout(); notice.success('参考资源已连接到镜头')
    },
    async saveScene(sceneId: number, patch: Partial<Scene>) {
      const updated = (await api.updateScene(sceneId, patch)).data
      this.scenes = this.scenes.map(item => item.id === sceneId ? updated : item); this.rebuildGraph(); notice.success('镜头已保存')
    },
    async saveAsset(assetId: number, patch: Partial<Asset>) {
      const updated = (await api.updateAsset(assetId, patch)).data
      this.assets = this.assets.map(item => item.id === assetId ? updated : item)
      this.rebuildGraph()
      notice.success('资产描述已保存')
    },
    async generateAsset(assetId: number) {
      if (!this.busyAssetIds.includes(assetId)) this.busyAssetIds.push(assetId)
      try {
        let task = (await api.generateAsset(assetId)).data
        while (!terminal.has(task.status)) { await sleep(2500); task = (await api.task(task.id)).data }
        if (task.status !== TaskStatusEnum.COMPLETED) throw new Error(task.error_message || '资产图片生成失败')
        this.assets = (await api.assets(this.novelId)).data.items
        this.rebuildGraph()
        notice.success('资产图片生成完成')
      } catch (error) {
        notice.error(error instanceof Error ? error.message : '资产图片生成失败')
      } finally {
        this.busyAssetIds = this.busyAssetIds.filter(id => id !== assetId)
      }
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
