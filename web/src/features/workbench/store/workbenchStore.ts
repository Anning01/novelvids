import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { api, mediaUrl } from '@/api'
import { notice } from '@/shared/notice'
import type { Asset, AudioReference, Chapter, DigitalHuman, EnumItem, ImageGenerationModel, Scene, Video, VideoGenerationModel } from '@/types'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import type { ImageAnnotation, NodeSize, Point, UploadedMediaData, WorkbenchEdge, WorkbenchNode, WorkbenchViewport } from '../types/workbenchTypes'
import { sceneAssetIds } from '../graph/sceneAssets'
import { activeVideoForScene, isTerminalVideo, sceneHasRunningVideo, sceneWithActiveVideo } from '../graph/videoVersions'
import { assetImageMediaMetadata, assetTypeLabel, DEFAULT_ASSET_ASPECT_RATIO, isReusableAssetPlaceholder, patchAssetImageMediaMetadata, REUSABLE_ASSET_PLACEHOLDER_KEY } from '../config/assetConfig'
import { normalizeWatermarkConfig, type WatermarkConfig } from '../config/watermarkConfig'
import { moveOrder, normalizeComposerConfig, orderedComposerInputs, type ComposerConfig, type ComposerMoveDirection } from '../config/composerConfig'
import { nodeCapabilities } from '../config/nodeCapabilities'
import { isAbortError, pollUntilTerminal, WorkbenchLoadEpoch } from '../execution/workbenchAsync'
import { isManualNodeKind, parseWorkbenchState, serializeWorkbenchState, WORKBENCH_LAYOUT_VERSION } from './workbenchPersistence'

interface HistorySnapshot {
  nodes: Record<string, { position: Point; size: NodeSize | null; zIndex: number; ui: Record<string, unknown> }>
  manualNodes: WorkbenchNode[]
  manualEdges: WorkbenchEdge[]
  selectedNodeKeys: string[]
  selectedEdgeKeys: string[]
  viewport: WorkbenchViewport
}
const terminal = new Set([TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED])
const uploadedMediaKinds = new Set<WorkbenchNode['kind']>(['image_media', 'video_media', 'audio_media'])
const now = () => new Date().toISOString()
const cloneValue = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const mediaTitle = (filename: string) => filename.replace(/\.[^.]+$/, '') || filename
const uploadedMediaUrl = (filename: string) => mediaUrl(`/media/${encodeURIComponent(filename)}`)

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
    videoModelOptions: [] as VideoGenerationModel[],
    imageModelOptions: [] as ImageGenerationModel[],
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
    loadEpoch: markRaw(new WorkbenchLoadEpoch()),
    pendingControllers: [] as AbortController[],
    pollingVideoIds: [] as number[],
  }),
  getters: {
    canUndo: state => state.history.length > 0,
    canRedo: state => state.future.length > 0,
  },
  actions: {
    nodeByKey(key: string) { return this.nodes.find(item => item.key === key) },
    beginPendingWork() {
      const controller = markRaw(new AbortController())
      this.pendingControllers.push(controller)
      return controller
    },
    finishPendingWork(controller: AbortController) {
      this.pendingControllers = this.pendingControllers.filter(item => item !== controller)
    },
    cancelPendingWork() {
      this.loadEpoch.begin()
      this.pendingControllers.forEach(controller => controller.abort())
      this.pendingControllers = []
      this.pollingVideoIds = []
      this.busyAssetIds = []
      this.busySceneIds = []
      this.loading = false
    },
    layoutKey() { return `novelvids:canvas:${this.chapterId}:layout:v${WORKBENCH_LAYOUT_VERSION}` },
    legacyLayoutKey() { return `novelvids:canvas:${this.chapterId}:layout:v1` },
    capture(): HistorySnapshot {
      return {
        nodes: Object.fromEntries(this.nodes.map(item => [item.key, {
          position: { ...item.position }, size: item.size ? { ...item.size } : null, zIndex: item.zIndex,
          ui: { ...((item.data.ui as Record<string, unknown>) || {}) },
        }])),
        manualNodes: cloneValue(this.nodes.filter(item => isManualNodeKind(item.kind))),
        manualEdges: cloneValue(this.mediaEdges),
        selectedNodeKeys: [...this.selectedNodeKeys],
        selectedEdgeKeys: [...this.selectedEdgeKeys],
        viewport: { ...this.viewport },
      }
    },
    restore(snapshot: HistorySnapshot) {
      const automaticNodes = this.nodes.filter(item => !isManualNodeKind(item.kind))
      this.manualNodes = cloneValue(snapshot.manualNodes)
      this.nodes = [...automaticNodes, ...this.manualNodes]
      this.nodes.forEach((item) => {
        const saved = snapshot.nodes[item.key]
        if (!saved) return
        item.position = { ...saved.position }; item.size = saved.size ? { ...saved.size } : null; item.zIndex = saved.zIndex
        item.data.ui = { ...saved.ui }
      })
      const automaticEdges = this.edges.filter(item => !item.key.startsWith('media-edge-'))
      this.mediaEdges = cloneValue(snapshot.manualEdges)
      this.edges = [...automaticEdges, ...this.mediaEdges.filter(item => this.nodeByKey(item.source) && this.nodeByKey(item.target))]
      this.selectedNodeKeys = snapshot.selectedNodeKeys.filter(key => Boolean(this.nodeByKey(key)))
      this.selectedEdgeKeys = snapshot.selectedEdgeKeys.filter(key => this.edges.some(item => item.key === key))
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
      try {
        localStorage.setItem(this.layoutKey(), serializeWorkbenchState({
          version: WORKBENCH_LAYOUT_VERSION,
          viewport: this.viewport,
          canvasSize: { width: 0, height: 0 },
          nodes: Object.fromEntries(this.nodes.map(item => [item.key, { position: item.position, size: item.size, zIndex: item.zIndex, ui: item.data.ui || {} }])),
          manualNodes: this.nodes.filter(item => isManualNodeKind(item.kind)),
          manualEdges: this.mediaEdges,
        }))
      } catch { /* ignore unavailable storage */ }
    },
    loadSavedLayout() {
      try {
        const current = localStorage.getItem(this.layoutKey())
        const legacy = current ? null : localStorage.getItem(this.legacyLayoutKey())
        const saved = parseWorkbenchState(current || legacy || '')
        if (!saved) return
        this.viewport = saved.viewport
        this.manualNodes = saved.manualNodes.filter(item => isManualNodeKind(item.kind))
        this.mediaEdges = saved.manualEdges
        this.nodes.push(...this.manualNodes.filter(item => !this.nodes.some(current => current.key === item.key)))
        this.edges.push(...this.mediaEdges.filter(item => !this.edges.some(current => current.key === item.key)))
        this.nodes.forEach((item) => {
          const value = saved.nodes[item.key]
          if (value) { item.position = value.position; if (value.size !== undefined) item.size = value.size; item.zIndex = value.zIndex; item.data.ui = value.ui }
        })
        if (!current && legacy) localStorage.setItem(this.layoutKey(), serializeWorkbenchState(saved))
      } catch { /* ignore invalid local layout */ }
    },
    async load(novelId: number, chapterId: number) {
      const epoch = this.loadEpoch.begin()
      this.loading = true; this.novelId = novelId; this.chapterId = chapterId
      this.nodes = []; this.edges = []; this.manualNodes = []; this.mediaEdges = []; this.history = []; this.future = []; this.busyAssetIds = []; this.busySceneIds = []; this.pollingVideoIds = []; this.videoModelOptions = []; this.imageModelOptions = []; this.viewport = { x: 0, y: 0, zoom: 1 }; this.clearSelection()
      try {
        const [bootstrapResponse, videoConfigResponse, imageConfigResponse] = await Promise.all([
          api.workbenchBootstrap(novelId, chapterId),
          api.videoGenerationModels(),
          api.imageGenerationModels(),
        ])
        if (!this.loadEpoch.isCurrent(epoch)) return
        this.chapter = bootstrapResponse.data.chapter
        this.assets = bootstrapResponse.data.assets
        this.scenes = bootstrapResponse.data.scenes
        this.videoModelOptions = videoConfigResponse.data
        this.modelOptions = this.videoModelOptions.map(item => ({ value: item.config_id, label: item.name }))
        this.imageModelOptions = imageConfigResponse.data
        this.videos = bootstrapResponse.data.videos
        this.rebuildGraph()
        this.loadSavedLayout()
        Object.entries(this.videos).forEach(([sceneId, videos]) => videos
          .filter(video => !isTerminalVideo(video))
          .forEach(video => { void this.resumeVideoPolling(Number(sceneId), video.id) }))
      } finally {
        if (this.loadEpoch.isCurrent(epoch)) this.loading = false
      }
    },
    rebuildGraph() {
      if (!this.chapter) return
      const nodes: WorkbenchNode[] = [node(this.chapter.id, 'chapter', 'chapter', `第 ${this.chapter.number} 章 · ${this.chapter.name}`, { x: 80, y: 80 }, { chapter: this.chapter, presentation: 'note', layout_family: 'note', layout_lane: 'note' })]
      const edges: WorkbenchEdge[] = []
      const validAssetIds = new Set(this.assets.map(asset => asset.id))
      this.assets.forEach((asset, index) => nodes.push(node(asset.id, `asset-${asset.id}`, 'asset', asset.canonical_name, { x: 480, y: index * 320 }, { asset, imageModelOptions: this.imageModelOptions, asset_type: assetTypeLabel(asset.asset_type), layout_family: 'asset', ui: {}, index })))
      this.scenes.forEach((scene, index) => {
        const sceneKey = `shot-${scene.id}`
        const sceneVideos = this.videos[scene.id] || []
        const sceneNode = node(scene.id, sceneKey, 'shot', `镜头 ${String(scene.sequence).padStart(2, '0')}`, { x: 900, y: index * 520 }, { scene, videos: sceneVideos, modelOptions: this.modelOptions, videoModelOptions: this.videoModelOptions, shot_index: scene.sequence, layout_family: 'shot', ui: {} })
        sceneNode.status = sceneHasRunningVideo(sceneVideos) ? 'running' : 'ready'
        nodes.push(sceneNode)
        sceneAssetIds(scene).filter(assetId => validAssetIds.has(assetId)).forEach(assetId => edges.push(edge(200000 + scene.id * 1000 + assetId, `asset-${assetId}-${sceneKey}`, `asset-${assetId}`, sceneKey, 'asset_reference')))
        const activeVideo = activeVideoForScene(scene, sceneVideos)
        if (activeVideo) {
          const resultKey = `video-${activeVideo.id}`
          nodes.push(node(activeVideo.id, resultKey, 'video_result', `视频结果 · #${activeVideo.id}`, { x: 1400, y: index * 520 }, { video: activeVideo, sceneId: scene.id, layout_family: 'result', ui: {} }))
          edges.push(edge(300000 + activeVideo.id, `${sceneKey}-${resultKey}`, sceneKey, resultKey, 'output_binding'))
        }
      })
      const old = new Map(this.nodes.map(item => [item.key, item]))
      this.nodes = nodes.map(item => old.has(item.key) ? { ...item, position: old.get(item.key)!.position, size: old.get(item.key)!.size, zIndex: old.get(item.key)!.zIndex, data: { ...item.data, ui: old.get(item.key)!.data.ui } } : item)
      this.manualNodes = [...old.values()].filter(item => isManualNodeKind(item.kind))
      this.nodes.push(...this.manualNodes)
      this.edges = [...edges, ...this.mediaEdges.filter(item => this.nodes.some(nodeItem => nodeItem.key === item.source) && this.nodes.some(nodeItem => nodeItem.key === item.target))]
    },
    selectNode(key: string, additive = false) {
      this.selectedNodeKeys = additive
        ? this.selectedNodeKeys.includes(key) ? this.selectedNodeKeys.filter(item => item !== key) : [...this.selectedNodeKeys, key]
        : [key]
      this.selectedEdgeKeys = []
    },
    selectNodes(keys: string[]) {
      this.selectedNodeKeys = [...new Set(keys)].filter(key => this.nodeByKey(key))
      if (this.selectedNodeKeys.length) this.selectedEdgeKeys = []
    },
    clearSelection() { this.selectedNodeKeys = []; this.selectedEdgeKeys = [] },
    updateNodeLayout(key: string, position: Point, size?: NodeSize | null, zIndex?: number) { const item = this.nodeByKey(key); if (!item) return; item.position = position; if (size !== undefined) item.size = size; if (zIndex !== undefined) item.zIndex = zIndex },
    updateNodeUi(key: string, ui: Record<string, unknown>) { const item = this.nodeByKey(key); if (item) item.data.ui = ui; this.persistLayout() },
    updateManualNodeData(key: string, patch: Record<string, unknown>) {
      const item = this.nodeByKey(key)
      if (!item || !isManualNodeKind(item.kind)) return
      item.data = { ...item.data, ...patch }
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
    },
    updateNodeDraft(key: string, patch: Record<string, unknown>) {
      const item = this.nodeByKey(key)
      if (!item) return
      item.data = { ...item.data, ...patch }
      if (isManualNodeKind(item.kind)) {
        this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
      }
    },
    async flushNodeDraft(key: string) {
      if (!this.nodeByKey(key)) return
      this.persistLayout()
    },
    async saveChapter(patch: Pick<Partial<Chapter>, 'name' | 'content'>) {
      if (!this.chapter) return null
      const updated = (await api.updateChapter(this.chapter.id, patch)).data
      this.chapter = updated
      this.rebuildGraph()
      notice.success('章节已保存')
      return updated
    },
    async flushLayout() { this.persistLayout() },
    copySelection() { const key = this.selectedNodeKeys[0]; const item = key ? this.nodeByKey(key) : null; this.clipboardNode = item && nodeCapabilities(item.kind).copyable ? cloneValue(item) : null },
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
    async deleteNodeKeys(keys: string[]) {
      const selected = [...new Set(keys)]
        .map(key => this.nodeByKey(key))
        .filter((item): item is WorkbenchNode => Boolean(item))
      const assets = selected.filter(item => item.kind === 'asset')
      const shots = selected.filter(item => item.kind === 'shot')
      const hiddenResults = selected.filter(item => item.kind === 'video_result')
      const manualKeys = new Set(selected.filter(item => isManualNodeKind(item.kind)).map(item => item.key))
      await Promise.all([
        ...assets.map(item => api.deleteAsset(item.id)),
        ...shots.map(item => api.deleteScene(item.id)),
      ])
      if (manualKeys.size || hiddenResults.length) this.checkpoint()
      hiddenResults.forEach((item) => {
        item.data.ui = { ...((item.data.ui as Record<string, unknown>) || {}), hidden: true }
      })
      const removedKeys = new Set([...manualKeys, ...assets.map(item => item.key), ...shots.map(item => item.key)])
      const affectedKeys = new Set([...removedKeys, ...hiddenResults.map(item => item.key)])
      this.assets = this.assets.filter(item => !assets.some(nodeItem => nodeItem.id === item.id))
      this.scenes = this.scenes.filter(item => !shots.some(nodeItem => nodeItem.id === item.id))
      this.manualNodes = this.manualNodes.filter(item => !manualKeys.has(item.key))
      this.manualNodes.filter(item => item.kind === 'section').forEach((section) => {
        const keys = Array.isArray(section.data.node_keys) ? section.data.node_keys.filter((key): key is string => typeof key === 'string') : []
        section.data.node_keys = keys.filter(key => !removedKeys.has(key))
      })
      this.mediaEdges = this.mediaEdges.filter(item => !removedKeys.has(item.source) && !removedKeys.has(item.target))
      this.nodes = this.nodes.filter(item => !removedKeys.has(item.key))
      this.edges = this.edges.filter(item => !removedKeys.has(item.source) && !removedKeys.has(item.target))
      this.selectedNodeKeys = this.selectedNodeKeys.filter(key => !affectedKeys.has(key))
      this.selectedEdgeKeys = this.selectedEdgeKeys.filter(key => this.edges.some(item => item.key === key))
      this.rebuildGraph(); this.persistLayout()
      if (affectedKeys.size) notice.success(`已删除 ${affectedKeys.size} 个节点`)
      return affectedKeys.size
    },
    async deleteSelection() { return this.deleteNodeKeys([...this.selectedNodeKeys]) },
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
    addUploadedMedia(
      kind: 'image_media' | 'video_media' | 'audio_media',
      uploaded: { filename: string; original_filename: string; content_type: string },
      position?: Point,
    ) {
      this.checkpoint()
      const stamp = Date.now()
      const key = `${kind.replace('_', '-')}-${stamp}`
      const mediaData: UploadedMediaData = {
        url: uploadedMediaUrl(uploaded.filename),
        filename: uploaded.filename,
        originalFilename: uploaded.original_filename || uploaded.filename,
        mimeType: uploaded.content_type,
      }
      const label = kind === 'image_media' ? '图片' : kind === 'video_media' ? '视频' : '音频'
      const item = node(-stamp, key, kind, mediaTitle(mediaData.originalFilename), position || { x: 560, y: 120 + this.manualNodes.length * 300 }, {
        ...mediaData,
        media_type: label,
        layout_family: 'asset',
        layout_lane: `asset:${kind}`,
        ui: {},
      })
      item.size = kind === 'audio_media' ? { width: 420, height: 170 } : { width: 360, height: 340 }
      this.manualNodes.push(item); this.nodes.push(item); this.selectNode(key); this.persistLayout()
      notice.success(`${label}上传完成`)
      return item
    },
    async uploadMedia(kind: 'image_media' | 'video_media' | 'audio_media', file: File, position?: Point) {
      const uploaded = await api.upload(file)
      return this.addUploadedMedia(kind, {
        filename: uploaded.filename,
        original_filename: uploaded.original_filename || file.name,
        content_type: uploaded.content_type || file.type,
      }, position)
    },
    async uploadImageAsset(file: File, position?: Point) {
      const uploaded = await api.upload(file)
      const originalFilename = uploaded.original_filename || file.name
      const canonicalName = mediaTitle(originalFilename)
      const created = (await api.createAsset({
        novel_id: this.novelId,
        chapter_id: this.chapterId,
        asset_type: AssetTypeEnum.ITEM,
        canonical_name: canonicalName,
        main_image: uploadedMediaUrl(uploaded.filename),
        metadata: patchAssetImageMediaMetadata(undefined, {
          source: 'upload',
          assetTypeExplicit: false,
          filename: uploaded.filename,
          originalFilename,
          mimeType: uploaded.content_type || file.type,
          annotations: [],
        }),
      })).data
      this.assets.push(created)
      this.rebuildGraph()
      const item = this.nodeByKey(`asset-${created.id}`) || null
      if (item && position) item.position = position
      if (item) this.selectNode(item.key)
      this.persistLayout()
      notice.success('图片已作为资产添加')
      return item
    },
    async replaceUploadedMedia(key: string, file: File) {
      const item = this.nodeByKey(key)
      if (!item || !uploadedMediaKinds.has(item.kind)) return null
      const uploaded = await api.upload(file)
      this.checkpoint()
      item.title = mediaTitle(uploaded.original_filename || file.name)
      item.data = {
        ...item.data,
        url: uploadedMediaUrl(uploaded.filename),
        filename: uploaded.filename,
        originalFilename: uploaded.original_filename || file.name,
        mimeType: uploaded.content_type || file.type,
        width: undefined,
        height: undefined,
        durationSeconds: undefined,
        annotations: item.kind === 'image_media' ? [] : undefined,
      }
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
      this.persistLayout()
      notice.success('媒体已重新上传')
      return item
    },
    updateUploadedMediaMetadata(key: string, patch: Pick<UploadedMediaData, 'width' | 'height' | 'durationSeconds'>) {
      const item = this.nodeByKey(key)
      if (!item || !uploadedMediaKinds.has(item.kind)) return
      const next = Object.fromEntries(Object.entries(patch).filter(([, value]) => typeof value === 'number' && Number.isFinite(value) && value > 0))
      if (!Object.keys(next).length) return
      const changed = Object.entries(next).some(([field, value]) => item.data[field] !== value)
      if (!changed) return
      item.data = { ...item.data, ...next }
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
      this.persistLayout()
    },
    saveImageAnnotations(key: string, annotations: ImageAnnotation[]) {
      const item = this.nodeByKey(key)
      if (!item || item.kind !== 'image_media') return false
      this.checkpoint()
      item.data = { ...item.data, annotations: cloneValue(annotations) }
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
      this.persistLayout()
      notice.success('图片标注已保存')
      return true
    },
    setMediaResource(key: string, resource: AudioReference | DigitalHuman) {
      const item = this.nodeByKey(key)
      if (!item || (item.kind !== 'audio_reference' && item.kind !== 'digital_human')) return
      this.checkpoint()
      item.data.resource = resource
      item.title = item.kind === 'audio_reference' && 'nickname' in resource ? resource.nickname : 'occupation' in resource ? `${resource.country} · ${resource.occupation}` : item.title
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
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
    addWatermark(position?: Point) {
      this.checkpoint()
      const stamp = Date.now(); const key = `watermark-${stamp}`
      const item = node(-stamp, key, 'watermark', '新水印', position || { x: 560, y: 120 + this.manualNodes.length * 320 }, {
        config: normalizeWatermarkConfig(null),
        capability_key: 'apply_watermark',
        layout_family: 'result',
        layout_lane: 'result:watermark',
        ui: {},
      })
      item.size = { width: 360, height: 300 }
      this.manualNodes.push(item); this.nodes.push(item); this.selectNode(key); this.persistLayout()
      return item
    },
    saveWatermarkConfig(key: string, config: Partial<WatermarkConfig>) {
      const item = this.nodeByKey(key)
      if (!item || item.kind !== 'watermark') return false
      this.checkpoint()
      item.data = { ...item.data, config: normalizeWatermarkConfig(config) }
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
      this.persistLayout()
      notice.success('水印配置已保存')
      return true
    },
    addVideoComposer(position?: Point) {
      this.checkpoint()
      const stamp = Date.now(); const key = `video-composer-${stamp}`
      const count = this.nodes.filter(item => item.kind === 'video_composer').length + 1
      const item = node(-stamp, key, 'video_composer', '视频合成器', position || { x: 980, y: 120 + this.manualNodes.length * 440 }, {
        config: normalizeComposerConfig({ name: count === 1 ? '视频合成器' : `视频合成器 ${count}` }),
        capability_key: 'compose_video',
        layout_family: 'result',
        layout_lane: 'result:composer',
        ui: {},
      })
      item.size = { width: 390, height: 420 }
      this.manualNodes.push(item); this.nodes.push(item); this.selectNode(key); this.persistLayout()
      return item
    },
    saveVideoComposerConfig(key: string, config: Partial<ComposerConfig>) {
      const item = this.nodeByKey(key)
      if (!item || item.kind !== 'video_composer') return false
      this.checkpoint()
      item.data = { ...item.data, config: normalizeComposerConfig(config) }
      this.manualNodes = this.nodes.filter(nodeItem => isManualNodeKind(nodeItem.kind))
      this.persistLayout()
      return true
    },
    moveComposerInput(composerKey: string, inputKey: string, direction: ComposerMoveDirection) {
      const current = orderedComposerInputs(composerKey, this.nodes, this.edges).map(item => item.key)
      const next = moveOrder(current, inputKey, direction)
      if (next.every((key, index) => key === current[index])) return false
      this.checkpoint()
      const indexes = new Map(next.map((key, index) => [key, index]))
      this.mediaEdges
        .filter(item => item.target === composerKey && item.targetHandle !== 'watermark-input')
        .forEach((item) => { item.orderIndex = indexes.get(item.source) ?? item.orderIndex })
      this.edges
        .filter(item => item.target === composerKey && item.targetHandle !== 'watermark-input')
        .forEach((item) => { item.orderIndex = indexes.get(item.source) ?? item.orderIndex })
      this.persistLayout()
      return true
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
    connectMediaNode(
      source: string,
      target: string,
      handles: { sourceHandle?: string | null; targetHandle?: string | null } = {},
    ) {
      const sourceNode = this.nodeByKey(source); const targetNode = this.nodeByKey(target)
      if (!sourceNode || !targetNode) return false
      if (!nodeCapabilities(sourceNode.kind).source || !nodeCapabilities(targetNode.kind).target) return false
      const hasExplicitHandles = Boolean(handles.sourceHandle || handles.targetHandle)
      const usesHandles = (sourceHandle: string, targetHandle: string) => !hasExplicitHandles
        || (handles.sourceHandle === sourceHandle && handles.targetHandle === targetHandle)
      const isShotReference = targetNode.kind === 'shot'
        && ['asset', 'audio_reference', 'digital_human', 'image_media', 'video_media', 'audio_media', 'video_result'].includes(sourceNode.kind)
        && usesHandles('asset-output', 'asset-input')
      const isAssetReference = targetNode.kind === 'asset'
        && ['asset', 'digital_human', 'image_media'].includes(sourceNode.kind)
        && source !== target
        && usesHandles('asset-output', 'asset-input')
      const isShotSequence = sourceNode.kind === 'shot'
        && targetNode.kind === 'shot'
        && source !== target
        && usesHandles('sequence-output', 'sequence-input')
      const isWatermarkVideo = targetNode.kind === 'watermark'
        && ['shot', 'video_result', 'video_media', 'video_composer', 'watermark'].includes(sourceNode.kind)
        && source !== target
        && usesHandles('output-output', 'watermark-video-input')
      const isComposerShot = targetNode.kind === 'video_composer'
        && sourceNode.kind === 'shot'
        && usesHandles('sequence-output', 'shot-input')
      const isComposerVideo = targetNode.kind === 'video_composer'
        && ['shot', 'video_result', 'video_media'].includes(sourceNode.kind)
        && usesHandles('output-output', 'video-input')
      const isComposerWatermark = targetNode.kind === 'video_composer'
        && sourceNode.kind === 'watermark'
        && usesHandles('watermark-output', 'watermark-input')
      if (!isShotReference && !isAssetReference && !isShotSequence && !isWatermarkVideo && !isComposerShot && !isComposerVideo && !isComposerWatermark) return false
      if (isShotReference && sourceNode.kind === 'asset') {
        const scene = targetNode.data.scene as Scene
        const assetIds = sceneAssetIds(scene)
        if (assetIds.includes(sourceNode.id)) return false
        this.checkpoint()
        void this.saveScene(scene.id, { asset_ids: [...assetIds, sourceNode.id] })
        return true
      }
      if (this.mediaEdges.some(item => item.source === source && item.target === target)) return false
      this.checkpoint()
      const stamp = Date.now()
      const isOutputBinding = isWatermarkVideo || isComposerShot || isComposerVideo || isComposerWatermark
      const orderIndex = isComposerShot || isComposerVideo
        ? this.mediaEdges.filter(item => item.target === target && item.targetHandle !== 'watermark-input').length
        : 0
      const edgeType = isShotSequence ? 'shot_sequence' : isOutputBinding ? 'output_binding' : 'asset_reference'
      const item = edge(-stamp, `media-edge-${stamp}`, source, target, edgeType, orderIndex)
      if (isAssetReference || isShotReference) {
        item.sourceHandle = 'asset-output'
        item.targetHandle = 'asset-input'
      } else if (isShotSequence) {
        item.sourceHandle = 'sequence-output'
        item.targetHandle = 'sequence-input'
      } else if (isWatermarkVideo) {
        item.sourceHandle = 'output-output'
        item.targetHandle = 'watermark-video-input'
      } else if (isComposerShot) {
        item.sourceHandle = 'sequence-output'
        item.targetHandle = 'shot-input'
      } else if (isComposerVideo) {
        item.sourceHandle = 'output-output'
        item.targetHandle = 'video-input'
      } else if (isComposerWatermark) {
        item.sourceHandle = 'watermark-output'
        item.targetHandle = 'watermark-input'
      }
      this.mediaEdges.push(item); this.edges.push(item); this.persistLayout()
      notice.success(isAssetReference
        ? '参考图片已连接到资产'
        : isShotSequence
          ? '视频顺序已连接'
          : isWatermarkVideo
            ? '视频已连接到水印'
            : isComposerWatermark
              ? '水印已连接到视频合成器'
              : isComposerShot || isComposerVideo
                ? '视频已加入成片输入'
                : '参考资源已连接到视频')
      return true
    },
    deleteMediaEdge(edgeKey: string) {
      if (!this.mediaEdges.some(item => item.key === edgeKey)) return false
      this.checkpoint()
      this.mediaEdges = this.mediaEdges.filter(item => item.key !== edgeKey)
      this.edges = this.edges.filter(item => item.key !== edgeKey)
      this.selectedEdgeKeys = this.selectedEdgeKeys.filter(key => key !== edgeKey)
      this.persistLayout()
      notice.success('已移除参考资源')
      return true
    },
    updateMediaEdgeConfig(edgeKey: string, patch: Record<string, unknown>) {
      const mediaEdge = this.mediaEdges.find(item => item.key === edgeKey)
      if (!mediaEdge) return false
      this.checkpoint()
      mediaEdge.config = { ...(mediaEdge.config || {}), ...patch }
      const graphEdge = this.edges.find(item => item.key === edgeKey)
      if (graphEdge) graphEdge.config = { ...mediaEdge.config }
      this.persistLayout()
      return true
    },
    async removeReferenceEdge(edgeKey: string) {
      if (this.mediaEdges.some(item => item.key === edgeKey))
        return this.deleteMediaEdge(edgeKey)
      const target = this.edges.find(item => item.key === edgeKey && item.type === 'asset_reference')
      if (!target) return false
      const sourceNode = this.nodeByKey(target.source)
      const targetNode = this.nodeByKey(target.target)
      const scene = targetNode?.kind === 'shot' ? targetNode.data.scene as Scene | undefined : undefined
      if (!sourceNode || sourceNode.kind !== 'asset' || !scene) return false
      await this.saveScene(scene.id, {
        asset_ids: sceneAssetIds(scene).filter(id => id !== sourceNode.id),
      })
      return true
    },
    async saveScene(sceneId: number, patch: Partial<Scene>) {
      const updated = (await api.updateScene(sceneId, patch)).data
      this.scenes = this.scenes.map(item => item.id === sceneId ? updated : item); this.rebuildGraph(); notice.success('镜头已保存')
    },
    async setActiveVideo(sceneId: number, videoId: number) {
      const scene = this.scenes.find(item => item.id === sceneId)
      if (!scene || !this.videos[sceneId]?.some(video => video.id === videoId)) return null
      const nextMetadata = sceneWithActiveVideo(scene, videoId).metadata
      const updated = (await api.updateScene(sceneId, { metadata: nextMetadata })).data
      this.scenes = this.scenes.map(item => item.id === sceneId ? updated : item)
      this.rebuildGraph()
      notice.success('已切换镜头视频版本')
      return updated
    },
    async saveAsset(assetId: number, patch: Partial<Asset>) {
      const updated = (await api.updateAsset(assetId, patch)).data
      this.assets = this.assets.map(item => item.id === assetId ? updated : item)
      this.rebuildGraph()
      notice.success('资产描述已保存')
    },
    async addEmptyAsset(position?: Point) {
      const names = new Set(this.assets.map(item => item.canonical_name))
      let suffix = 1
      while (names.has(`资产 ${suffix}`)) suffix += 1
      const created = (await api.createAsset({
        novel_id: this.novelId,
        chapter_id: this.chapterId,
        asset_type: AssetTypeEnum.PERSON,
        canonical_name: `资产 ${suffix}`,
        metadata: {
          [REUSABLE_ASSET_PLACEHOLDER_KEY]: true,
          aspect_ratio: DEFAULT_ASSET_ASPECT_RATIO,
          workbench: { aspectRatio: DEFAULT_ASSET_ASPECT_RATIO },
        },
      })).data
      this.assets.push(created)
      this.rebuildGraph()
      const item = this.nodeByKey(`asset-${created.id}`) || null
      if (item && position) item.position = position
      if (item) this.selectNode(item.key)
      this.persistLayout()
      notice.success('已添加空资产')
      return item
    },
    reusableAssetName(name: string, targetAssetId: number) {
      const base = name.trim() || '复用资产'
      const usedNames = new Set(this.assets.filter(asset => asset.id !== targetAssetId).map(asset => `${asset.asset_type}:${asset.canonical_name}`))
      const target = this.assets.find(asset => asset.id === targetAssetId)
      if (!target || !usedNames.has(`${target.asset_type}:${base}`)) return base
      let suffix = 2
      while (usedNames.has(`${target.asset_type}:${base} ${suffix}`)) suffix += 1
      return `${base} ${suffix}`
    },
    async applyPublicAssetToPlaceholder(placeholderId: number, source: Asset) {
      const placeholder = this.assets.find(asset => asset.id === placeholderId)
      if (!placeholder || !isReusableAssetPlaceholder(placeholder)) throw new Error('请从新建的空资产选择公共资产')
      if (placeholder.asset_type !== source.asset_type) throw new Error('只能选择与当前节点类型一致的公共资产')
      const sourceMetadata = source.metadata && typeof source.metadata === 'object' && !Array.isArray(source.metadata)
        ? source.metadata as Record<string, unknown>
        : {}
      const updated = (await api.updateAsset(placeholderId, {
        canonical_name: this.reusableAssetName(source.canonical_name, placeholderId),
        aliases: source.aliases,
        description: source.description,
        base_traits: source.base_traits,
        main_image: source.main_image,
        angle_image_1: source.angle_image_1,
        angle_image_2: source.angle_image_2,
        image_source: source.image_source,
        is_global: false,
        metadata: {
          ...sourceMetadata,
          library_source: 'public',
          source_asset_id: source.id,
          [REUSABLE_ASSET_PLACEHOLDER_KEY]: false,
        },
      })).data
      this.assets = this.assets.map(asset => asset.id === placeholderId ? updated : asset)
      this.rebuildGraph()
      notice.success(`已应用公共资产「${updated.canonical_name}」`)
      return this.nodeByKey(`asset-${updated.id}`) || null
    },
    async applyPublicDigitalHumanToPlaceholder(placeholderId: number, human: DigitalHuman) {
      const placeholder = this.assets.find(asset => asset.id === placeholderId)
      if (!placeholder || !isReusableAssetPlaceholder(placeholder)) throw new Error('请从新建的空资产选择公共人物')
      if (placeholder.asset_type !== AssetTypeEnum.PERSON) throw new Error('公共人物只能用于人物资产')
      const currentMetadata = placeholder.metadata && typeof placeholder.metadata === 'object' && !Array.isArray(placeholder.metadata)
        ? placeholder.metadata as Record<string, unknown>
        : {}
      const currentWorkbench = currentMetadata.workbench && typeof currentMetadata.workbench === 'object' && !Array.isArray(currentMetadata.workbench)
        ? currentMetadata.workbench as Record<string, unknown>
        : {}
      const updated = (await api.updateAsset(placeholderId, {
        canonical_name: this.reusableAssetName(human.occupation || '公共人物', placeholderId),
        description: `${human.country} · ${human.gender} · ${human.age} 岁${human.occupation ? ` · ${human.occupation}` : ''}`,
        main_image: human.image_url,
        is_global: false,
        metadata: {
          ...currentMetadata,
          library_source: 'public',
          source_asset_id: human.asset_id,
          gender: human.gender,
          age: human.age,
          country: human.country,
          occupation: human.occupation,
          [REUSABLE_ASSET_PLACEHOLDER_KEY]: false,
          workbench: {
            ...currentWorkbench,
            digitalHumanAssetId: human.asset_id,
            digitalHumanPreviewUrl: human.image_url,
          },
        },
      })).data
      this.assets = this.assets.map(asset => asset.id === placeholderId ? updated : asset)
      this.rebuildGraph()
      notice.success(`已应用公共人物「${updated.canonical_name}」`)
      return this.nodeByKey(`asset-${updated.id}`) || null
    },
    async reuseProjectAssetInPlaceholder(placeholderId: number, source: Asset) {
      const placeholder = this.assets.find(asset => asset.id === placeholderId)
      if (!placeholder || !isReusableAssetPlaceholder(placeholder)) throw new Error('请从新建的空资产选择项目资产')
      if (placeholder.asset_type !== source.asset_type) throw new Error('只能选择与当前节点类型一致的项目资产')
      if (placeholder.novel_id !== source.novel_id || source.novel_id !== this.novelId) throw new Error('只能复用当前项目的资产')
      const placeholderNode = this.nodeByKey(`asset-${placeholderId}`)
      const position = placeholderNode ? { ...placeholderNode.position } : null
      const zIndex = placeholderNode?.zIndex
      const reused = (await api.reuseAsset(source.id, this.chapterId)).data
      const merged = (await api.mergeAssets(placeholderId, reused.id)).data.asset
      this.assets = [...this.assets.filter(asset => asset.id !== placeholderId && asset.id !== reused.id), merged]
      this.rebuildGraph()
      const item = this.nodeByKey(`asset-${merged.id}`) || null
      if (item && position) item.position = position
      if (item && zIndex !== undefined) item.zIndex = zIndex
      if (item) this.selectNode(item.key)
      this.persistLayout()
      notice.success(`已复用项目资产「${merged.canonical_name}」`)
      return item
    },
    async reuseAsset(assetId: number, position?: Point) {
      const existing = this.nodeByKey(`asset-${assetId}`)
      if (existing) {
        this.selectNode(existing.key)
        return existing
      }
      const reused = (await api.reuseAsset(assetId, this.chapterId)).data
      this.assets.push(reused)
      this.rebuildGraph()
      const item = this.nodeByKey(`asset-${reused.id}`) || null
      if (item && position) item.position = position
      if (item) this.selectNode(item.key)
      this.persistLayout()
      notice.success(`已复用资产「${reused.canonical_name}」`)
      return item
    },
    async setAssetMainImage(assetId: number, url: string | null) {
      const updated = (await api.updateAsset(assetId, { main_image: url } as Partial<Asset>)).data
      this.assets = this.assets.map(item => item.id === assetId ? updated : item)
      this.rebuildGraph()
      notice.success(url ? '已设为主图' : '已清除主图')
      return updated
    },
    async replaceAssetImage(assetId: number, file: File) {
      const asset = this.assets.find(item => item.id === assetId)
      if (!asset) return null
      const currentImageMetadata = assetImageMediaMetadata(asset)
      const uploaded = await api.upload(file)
      const originalFilename = uploaded.original_filename || file.name
      const updated = (await api.updateAsset(assetId, {
        main_image: uploadedMediaUrl(uploaded.filename),
        metadata: patchAssetImageMediaMetadata(asset.metadata, {
          source: 'upload',
          assetTypeExplicit: currentImageMetadata.source === 'upload'
            ? currentImageMetadata.assetTypeExplicit
            : true,
          filename: uploaded.filename,
          originalFilename,
          mimeType: uploaded.content_type || file.type,
          width: undefined,
          height: undefined,
          annotations: [],
        }),
      })).data
      this.assets = this.assets.map(item => item.id === updated.id ? updated : item)
      this.rebuildGraph()
      notice.success('资产图片已更新')
      return updated
    },
    async updateAssetImageMetadata(assetId: number, patch: { width?: number; height?: number }) {
      const asset = this.assets.find(item => item.id === assetId)
      if (!asset) return null
      const next = Object.fromEntries(Object.entries(patch)
        .filter(([, value]) => typeof value === 'number' && Number.isFinite(value) && value > 0))
      if (!Object.keys(next).length) return asset
      const updated = (await api.updateAsset(assetId, {
        metadata: patchAssetImageMediaMetadata(asset.metadata, next),
      })).data
      this.assets = this.assets.map(item => item.id === updated.id ? updated : item)
      this.rebuildGraph()
      return updated
    },
    async saveAssetImageAnnotations(assetId: number, annotations: ImageAnnotation[]) {
      const asset = this.assets.find(item => item.id === assetId)
      if (!asset) return null
      const updated = (await api.updateAsset(assetId, {
        metadata: patchAssetImageMediaMetadata(asset.metadata, {
          annotations: cloneValue(annotations),
        }),
      })).data
      this.assets = this.assets.map(item => item.id === updated.id ? updated : item)
      this.rebuildGraph()
      notice.success('图片标注已保存')
      return updated
    },
    async createAssetVariant(assetId: number, data: { name: string; description?: string; base_traits?: string; chapter_numbers?: number[]; metadata?: Record<string, unknown> }) {
      const created = (await api.createAssetVariant(assetId, data)).data
      this.assets = this.assets.map(asset => asset.id === assetId
        ? { ...asset, variants: [...(asset.variants || []), created] }
        : asset)
      this.rebuildGraph()
      notice.success(`已新增形态「${created.name}」`)
      return created
    },
    async deleteAssetVariant(assetId: number, variantId: number) {
      await api.deleteAssetVariant(assetId, variantId)
      this.assets = this.assets.map(asset => asset.id === assetId
        ? { ...asset, variants: (asset.variants || []).filter(variant => variant.id !== variantId) }
        : asset)
      this.rebuildGraph()
      notice.success('资产形态已删除')
    },
    async generateAsset(assetId: number, variantId?: number) {
      const controller = this.beginPendingWork()
      if (!this.busyAssetIds.includes(assetId)) this.busyAssetIds.push(assetId)
      try {
        let task = (await api.generateAsset(assetId, variantId)).data
        if (!terminal.has(task.status)) {
          task = await pollUntilTerminal(
            async () => (await api.task(task.id)).data,
            { signal: controller.signal, intervalMs: 2500, terminalStatuses: terminal },
          )
        }
        if (task.status !== TaskStatusEnum.COMPLETED) throw new Error(task.error_message || '资产图片生成失败')
        const updated = (await api.asset(assetId)).data
        if (controller.signal.aborted) return
        this.assets = this.assets.map(item => item.id === updated.id ? updated : item)
        this.rebuildGraph()
        notice.success('资产图片生成完成')
      } catch (error) {
        if (!isAbortError(error)) notice.error(error instanceof Error ? error.message : '资产图片生成失败')
      } finally {
        this.finishPendingWork(controller)
        this.busyAssetIds = this.busyAssetIds.filter(id => id !== assetId)
      }
    },
    async addShot(position?: Point) {
      const created = (await api.createScene({ chapter_id: this.chapterId, sequence: Math.max(0, ...this.scenes.map(item => item.sequence)) + 1, description: '新镜头', prompt: '', duration: 6 })).data
      this.scenes.push(created); this.videos[created.id] = []; this.rebuildGraph()
      const item = this.nodeByKey(`shot-${created.id}`) || null
      if (item && position) item.position = position
      if (item) this.selectNode(item.key)
      this.persistLayout()
      notice.success('已添加镜头')
      return item
    },
    async generateScenes() {
      const controller = this.beginPendingWork()
      try {
        const task = (await api.generateScenes(this.chapterId)).data
        const current = terminal.has(task.status)
          ? task
          : await pollUntilTerminal(
              async () => (await api.task(task.id)).data,
              { signal: controller.signal, intervalMs: 2500, terminalStatuses: terminal },
            )
        if (current.status !== TaskStatusEnum.COMPLETED) throw new Error(current.error_message || '分镜生成失败')
        if (controller.signal.aborted) return
        await this.load(this.novelId, this.chapterId)
        notice.success('分镜生成完成')
      } catch (error) {
        if (!isAbortError(error)) throw error
      } finally {
        this.finishPendingWork(controller)
      }
    },
    async generateVideo(sceneId: number, modelConfigId: number, options: { generation_mode?: 'reference' | 'keyframes'; first_frame_url?: string; last_frame_url?: string; resolution?: string; aspect_ratio?: string; duration?: number; output_format?: string; generate_audio?: boolean; return_last_frame?: boolean } = {}) {
      const controller = this.beginPendingWork()
      let submittedVideoId: number | null = null
      if (!this.busySceneIds.includes(sceneId)) this.busySceneIds.push(sceneId)
      try {
        let video = (await api.generateVideo(sceneId, modelConfigId, options)).data
        submittedVideoId = video.id
        if (controller.signal.aborted) return
        this.videos[sceneId] = [video, ...(this.videos[sceneId] || []).filter(item => item.id !== video.id)]
        const scene = this.scenes.find(item => item.id === sceneId)
        if (scene) {
          const adopted = sceneWithActiveVideo(scene, video.id)
          this.scenes = this.scenes.map(item => item.id === sceneId ? adopted : item)
          try {
            const updated = (await api.updateScene(sceneId, { metadata: adopted.metadata })).data
            this.scenes = this.scenes.map(item => item.id === sceneId ? updated : item)
          } catch {
            notice.error('视频已提交，但采用状态保存失败；刷新后可重新选择该版本')
          }
        }
        this.rebuildGraph()
        if (!terminal.has(video.status)) {
          this.pollingVideoIds.push(video.id)
          video = await pollUntilTerminal(async () => {
            const current = (await api.queryVideo(video.id)).data
            if (!controller.signal.aborted) {
              this.videos[sceneId] = this.videos[sceneId].map(item => item.id === current.id ? current : item)
              this.rebuildGraph()
            }
            return current
          }, { signal: controller.signal, intervalMs: 4000, terminalStatuses: terminal })
        }
        video.status === TaskStatusEnum.COMPLETED ? notice.success('视频生成完成') : notice.error(String(video.metadata?.error || '视频生成失败'))
      } catch (error) {
        if (!isAbortError(error)) throw error
      } finally {
        this.finishPendingWork(controller)
        if (submittedVideoId !== null) this.pollingVideoIds = this.pollingVideoIds.filter(id => id !== submittedVideoId)
        this.busySceneIds = this.busySceneIds.filter(id => id !== sceneId)
        this.rebuildGraph()
      }
    },
    async resumeVideoPolling(sceneId: number, videoId: number) {
      if (this.pollingVideoIds.includes(videoId)) return
      const initial = this.videos[sceneId]?.find(video => video.id === videoId)
      if (!initial || isTerminalVideo(initial)) return
      const chapterId = this.chapterId
      const controller = this.beginPendingWork()
      this.pollingVideoIds.push(videoId)
      if (!this.busySceneIds.includes(sceneId)) this.busySceneIds.push(sceneId)
      try {
        const video = await pollUntilTerminal(async () => {
          const current = (await api.queryVideo(videoId)).data
          if (this.chapterId !== chapterId) controller.abort()
          if (!controller.signal.aborted) {
            this.videos[sceneId] = (this.videos[sceneId] || []).map(item => item.id === current.id ? current : item)
            this.rebuildGraph()
          }
          return current
        }, { signal: controller.signal, intervalMs: 4000, terminalStatuses: terminal })
        if (!controller.signal.aborted) {
          video.status === TaskStatusEnum.COMPLETED
            ? notice.success('视频生成完成')
            : notice.error(String(video.metadata?.error || '视频生成失败'))
        }
      } catch (error) {
        if (!isAbortError(error)) notice.error(error instanceof Error ? error.message : '视频状态刷新失败')
      } finally {
        this.finishPendingWork(controller)
        this.pollingVideoIds = this.pollingVideoIds.filter(id => id !== videoId)
        if (!sceneHasRunningVideo(this.videos[sceneId] || [])) {
          this.busySceneIds = this.busySceneIds.filter(id => id !== sceneId)
        }
        this.rebuildGraph()
      }
    },
    async refreshVideo(videoId: number) {
      const updated = (await api.queryVideo(videoId)).data
      this.videos[updated.scene_id] = (this.videos[updated.scene_id] || []).map(item => item.id === updated.id ? updated : item); this.rebuildGraph()
    },
  },
})
