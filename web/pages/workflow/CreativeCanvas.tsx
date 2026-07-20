import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  AlignHorizontalDistributeCenter,
  BookOpenText,
  Box,
  Clapperboard,
  Film,
  Hand,
  Image as ImageIcon,
  Loader2,
  MapPin,
  MousePointer2,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  User,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api } from '@/services/api'
import { sleep, modelLabel, statusLabel } from '@/lib/helpers'
import type { Asset, Chapter, EnumItem, Scene, Video } from '@/types'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import './canvas.css'

interface CreativeCanvasProps {
  chapterId: number
  novelId: number
}

type CanvasNodeData = {
  kind: 'chapter' | 'asset' | 'scene' | 'video'
  chapter?: Chapter
  asset?: Asset
  scene?: Scene
  video?: Video
  videos?: Video[]
  modelOptions?: EnumItem[]
  busy?: boolean
  onSaveScene?: (sceneId: number, patch: Partial<Scene>) => Promise<void>
  onGenerateVideo?: (sceneId: number, modelType: number) => Promise<void>
  onRefreshVideo?: (videoId: number) => Promise<void>
}

type CanvasNode = Node<CanvasNodeData>

const terminalStatuses = new Set([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])

const assetMeta = {
  [AssetTypeEnum.PERSON]: { label: '角色资产', Icon: User, tone: 'violet' },
  [AssetTypeEnum.SCENE]: { label: '场景资产', Icon: MapPin, tone: 'emerald' },
  [AssetTypeEnum.ITEM]: { label: '道具资产', Icon: Box, tone: 'amber' },
}

function NodeFrame({
  selected,
  tone,
  icon,
  title,
  eyebrow,
  children,
  target = true,
  source = true,
}: {
  selected: boolean
  tone: string
  icon: React.ReactNode
  title: string
  eyebrow: string
  children: React.ReactNode
  target?: boolean
  source?: boolean
}) {
  return (
    <article className={`canvas-node canvas-node--${tone} ${selected ? 'is-selected' : ''}`}>
      {target && <Handle type="target" position={Position.Left} />}
      <header className="canvas-node__header">
        <span className="canvas-node__icon">{icon}</span>
        <span className="canvas-node__heading">
          <small>{eyebrow}</small>
          <strong>{title}</strong>
        </span>
      </header>
      <div className="canvas-node__body nodrag nowheel">{children}</div>
      {source && <Handle type="source" position={Position.Right} />}
    </article>
  )
}

function ChapterNode({ data, selected }: NodeProps<CanvasNode>) {
  const chapter = data.chapter!
  return (
    <NodeFrame
      selected={selected}
      tone="chapter"
      icon={<BookOpenText size={17} />}
      eyebrow="章节源内容"
      title={`第 ${chapter.number} 章 · ${chapter.name}`}
      target={false}
    >
      <p className="canvas-node__copy canvas-node__copy--chapter">
        {chapter.content || '本章暂时没有正文内容。'}
      </p>
      <div className="canvas-node__meta">
        <span>{(chapter.content || '').length.toLocaleString()} 字</span>
        <span>内容源</span>
      </div>
    </NodeFrame>
  )
}

function AssetNode({ data, selected }: NodeProps<CanvasNode>) {
  const asset = data.asset!
  const meta = assetMeta[asset.asset_type] || assetMeta[AssetTypeEnum.ITEM]
  const { Icon } = meta
  return (
    <NodeFrame
      selected={selected}
      tone={meta.tone}
      icon={<Icon size={17} />}
      eyebrow={meta.label}
      title={asset.canonical_name}
      target={false}
    >
      <div className="canvas-node__asset-media">
        {asset.main_image ? (
          <img src={asset.main_image} alt={asset.canonical_name} />
        ) : (
          <span><ImageIcon size={24} />尚未生成主图</span>
        )}
      </div>
      {asset.description && <p className="canvas-node__copy">{asset.description}</p>}
      <div className="canvas-node__meta">
        <span>{asset.main_image ? '视觉已就绪' : '等待视觉资产'}</span>
        {asset.aliases?.[0] && <span>@{asset.aliases[0]}</span>}
      </div>
    </NodeFrame>
  )
}

function SceneNode({ data, selected }: NodeProps<CanvasNode>) {
  const scene = data.scene!
  const [description, setDescription] = useState(scene.description || '')
  const [prompt, setPrompt] = useState(scene.prompt || '')
  const [duration, setDuration] = useState(String(scene.duration || 6))
  const [model, setModel] = useState('')
  const [saving, setSaving] = useState(false)
  const latestVideo = data.videos?.[0]

  useEffect(() => {
    setDescription(scene.description || '')
    setPrompt(scene.prompt || '')
    setDuration(String(scene.duration || 6))
  }, [scene.description, scene.duration, scene.prompt])

  useEffect(() => {
    if (!model && data.modelOptions?.length) {
      setModel(String(latestVideo?.model_type || data.modelOptions[0].value))
    }
  }, [data.modelOptions, latestVideo?.model_type, model])

  const save = async () => {
    setSaving(true)
    try {
      await data.onSaveScene?.(scene.id, {
        description: description.trim(),
        prompt: prompt.trim(),
        duration: Number(duration) || 6,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <NodeFrame
      selected={selected}
      tone="scene"
      icon={<Clapperboard size={17} />}
      eyebrow={`镜头 ${String(scene.sequence).padStart(2, '0')}`}
      title={description || '未命名镜头'}
    >
      <label className="canvas-node__field">
        <span>画面描述</span>
        <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} />
      </label>
      <label className="canvas-node__field">
        <span>生成提示词</span>
        <Textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={4} />
      </label>
      <div className="canvas-node__form-row">
        <label className="canvas-node__field canvas-node__field--duration">
          <span>时长</span>
          <input value={duration} onChange={(event) => setDuration(event.target.value)} inputMode="decimal" />
        </label>
        <label className="canvas-node__field">
          <span>视频模型</span>
            <Select value={model} onValueChange={setModel} disabled={!data.modelOptions?.length}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {data.modelOptions?.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
        </label>
      </div>
      <div className="canvas-node__actions">
        <Button size="sm" variant="secondary" onClick={save} disabled={saving || data.busy}>
          {saving ? <Loader2 className="animate-spin" /> : <Save />}
          保存镜头
        </Button>
        <Button size="sm" onClick={() => data.onGenerateVideo?.(scene.id, Number(model))} disabled={data.busy || !model}>
          {data.busy ? <Loader2 className="animate-spin" /> : <Play />}
          {latestVideo ? '再次生成' : '生成视频'}
        </Button>
      </div>
      {latestVideo && (
        <div className="canvas-node__meta">
          <span>{modelLabel(latestVideo.model_type)}</span>
          <Badge variant="outline">{statusLabel(latestVideo.status)}</Badge>
        </div>
      )}
    </NodeFrame>
  )
}

function VideoNode({ data, selected }: NodeProps<CanvasNode>) {
  const video = data.video!
  const processing = !terminalStatuses.has(video.status)
  return (
    <NodeFrame
      selected={selected}
      tone={video.status === TaskStatusEnum.FAILED ? 'error' : 'video'}
      icon={<Film size={17} />}
      eyebrow="视频结果"
      title={`${modelLabel(video.model_type)} · #${video.id}`}
      source={false}
    >
      <div className="canvas-node__video">
        {video.status === TaskStatusEnum.COMPLETED && video.url ? (
          <video src={video.url} controls preload="metadata" />
        ) : processing ? (
          <span><Loader2 className="animate-spin" size={26} />视频生成中</span>
        ) : (
          <span><Film size={26} />{video.metadata?.error || '生成失败，请重试'}</span>
        )}
      </div>
      <div className="canvas-node__actions canvas-node__actions--result">
        <Badge variant="outline">{statusLabel(video.status)}</Badge>
        {processing && (
          <Button size="sm" variant="ghost" onClick={() => data.onRefreshVideo?.(video.id)}>
            <RefreshCw />刷新状态
          </Button>
        )}
      </div>
    </NodeFrame>
  )
}

const nodeTypes = {
  chapter: ChapterNode,
  asset: AssetNode,
  scene: SceneNode,
  video: VideoNode,
}

function canvasLayout(
  chapter: Chapter,
  assets: Asset[],
  scenes: Scene[],
  videosByScene: Record<number, Video[]>,
  callbacks: Pick<CanvasNodeData, 'onSaveScene' | 'onGenerateVideo' | 'onRefreshVideo'>,
  busySceneIds: Set<number>,
  modelOptions: EnumItem[],
) {
  const nodes: CanvasNode[] = []
  const edges: Edge[] = []
  nodes.push({ id: 'chapter', type: 'chapter', position: { x: 0, y: 120 }, data: { kind: 'chapter', chapter, ...callbacks } })

  assets.forEach((asset, index) => {
    nodes.push({
      id: `asset-${asset.id}`,
      type: 'asset',
      position: { x: 430, y: index * 310 },
      data: { kind: 'asset', asset, ...callbacks },
    })
  })

  scenes.forEach((scene, index) => {
    const sceneVideos = videosByScene[scene.id] || []
    const sceneY = index * 540
    nodes.push({
      id: `scene-${scene.id}`,
      type: 'scene',
      position: { x: 850, y: sceneY },
      data: { kind: 'scene', scene, videos: sceneVideos, modelOptions, busy: busySceneIds.has(scene.id), ...callbacks },
    })
    edges.push({ id: `chapter-scene-${scene.id}`, source: 'chapter', target: `scene-${scene.id}`, type: 'smoothstep' })
    ;(scene.asset_ids || []).forEach((assetId) => {
      if (assets.some((asset) => asset.id === assetId)) {
        edges.push({ id: `asset-${assetId}-scene-${scene.id}`, source: `asset-${assetId}`, target: `scene-${scene.id}`, type: 'smoothstep' })
      }
    })
    sceneVideos.slice(0, 1).forEach((video) => {
      nodes.push({
        id: `video-${video.id}`,
        type: 'video',
        position: { x: 1360, y: sceneY + 40 },
        data: { kind: 'video', video, ...callbacks },
      })
      edges.push({ id: `scene-${scene.id}-video-${video.id}`, source: `scene-${scene.id}`, target: `video-${video.id}`, type: 'smoothstep', animated: !terminalStatuses.has(video.status) })
    })
  })
  return { nodes, edges }
}

function CreativeCanvasInner({ chapterId, novelId }: CreativeCanvasProps) {
  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [assets, setAssets] = useState<Asset[]>([])
  const [scenes, setScenes] = useState<Scene[]>([])
  const [videosByScene, setVideosByScene] = useState<Record<number, Video[]>>({})
  const [modelOptions, setModelOptions] = useState<EnumItem[]>([])
  const [loading, setLoading] = useState(true)
  const [generatingScenes, setGeneratingScenes] = useState(false)
  const [busySceneIds, setBusySceneIds] = useState<Set<number>>(new Set())
  const [tool, setTool] = useState<'select' | 'pan'>('select')
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const { fitView } = useReactFlow<CanvasNode>()

  const loadWorkspace = useCallback(async () => {
    const [chapterRes, assetsRes, scenesRes, enumsRes] = await Promise.all([
      api.getChapter(chapterId),
      api.getAssets(novelId),
      api.getScenes(chapterId),
      api.getEnums(),
    ])
    const nextScenes = scenesRes.data.items
    const videoEntries = await Promise.all(nextScenes.map(async (scene) => {
      const response = await api.getVideos(1, 20, '-id', scene.id)
      return [scene.id, response.data.items] as const
    }))
    setChapter(chapterRes.data)
    setAssets(assetsRes.data.items)
    setScenes(nextScenes)
    setVideosByScene(Object.fromEntries(videoEntries))
    setModelOptions(enumsRes.data.video_model_type || [])
  }, [chapterId, novelId])

  useEffect(() => {
    setLoading(true)
    loadWorkspace().catch((error) => toast.error(error.message || '画布加载失败')).finally(() => setLoading(false))
  }, [loadWorkspace])

  const saveScene = useCallback(async (sceneId: number, patch: Partial<Scene>) => {
    const response = await api.patchScene(sceneId, patch)
    setScenes((current) => current.map((scene) => scene.id === sceneId ? response.data : scene))
    toast.success('镜头已保存')
  }, [])

  const refreshVideo = useCallback(async (videoId: number) => {
    const response = await api.queryVideo(videoId)
    const video = response.data
    setVideosByScene((current) => ({
      ...current,
      [video.scene_id]: (current[video.scene_id] || []).map((item) => item.id === video.id ? video : item),
    }))
  }, [])

  const generateVideo = useCallback(async (sceneId: number, modelType: number) => {
    setBusySceneIds((current) => new Set(current).add(sceneId))
    try {
      const created = (await api.generateVideo({ scene_id: sceneId, model_type: modelType })).data
      setVideosByScene((current) => ({ ...current, [sceneId]: [created, ...(current[sceneId] || [])] }))
      let video = created
      while (!terminalStatuses.has(video.status)) {
        await sleep(4000)
        video = (await api.queryVideo(video.id)).data
        setVideosByScene((current) => ({
          ...current,
          [sceneId]: (current[sceneId] || []).map((item) => item.id === video.id ? video : item),
        }))
      }
      video.status === TaskStatusEnum.COMPLETED ? toast.success('视频生成完成') : toast.error(video.metadata?.error || '视频生成失败')
    } catch (error) {
      toast.error((error as Error).message || '视频生成失败')
    } finally {
      setBusySceneIds((current) => {
        const next = new Set(current)
        next.delete(sceneId)
        return next
      })
    }
  }, [])

  const callbacks = useMemo(() => ({ onSaveScene: saveScene, onGenerateVideo: generateVideo, onRefreshVideo: refreshVideo }), [generateVideo, refreshVideo, saveScene])

  useEffect(() => {
    if (!chapter) return
    const layout = canvasLayout(chapter, assets, scenes, videosByScene, callbacks, busySceneIds, modelOptions)
    setNodes((current) => layout.nodes.map((node) => {
      const existing = current.find((item) => item.id === node.id)
      return existing ? { ...node, position: existing.position, selected: existing.selected } : node
    }))
    setEdges(layout.edges)
  }, [assets, busySceneIds, callbacks, chapter, modelOptions, scenes, setEdges, setNodes, videosByScene])

  const generateScenes = async () => {
    setGeneratingScenes(true)
    try {
      const task = (await api.generateScenes({ chapter_id: chapterId })).data
      let result = task
      while (!terminalStatuses.has(result.status)) {
        await sleep(3000)
        result = (await api.getTask(task.id)).data
      }
      if (result.status !== TaskStatusEnum.COMPLETED) throw new Error(result.error_message || '分镜生成失败')
      await loadWorkspace()
      toast.success('分镜已生成并加入画布')
      window.setTimeout(() => fitView({ padding: 0.14, duration: 500 }), 80)
    } catch (error) {
      toast.error((error as Error).message || '分镜生成失败')
    } finally {
      setGeneratingScenes(false)
    }
  }

  if (loading) return <div className="creative-canvas-state"><Loader2 className="animate-spin" />正在搭建创作画布…</div>

  return (
    <main className="creative-canvas" aria-label="章节视频创作画布">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        minZoom={0.15}
        maxZoom={2.2}
        fitView
        fitViewOptions={{ padding: 0.16 }}
        panOnDrag={tool === 'pan'}
        nodesDraggable={tool === 'select'}
        nodesConnectable={false}
        elementsSelectable={tool === 'select'}
        panOnScroll
        selectionOnDrag={tool === 'select'}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Lines} gap={38} color="#302d2a" />
        <MiniMap pannable zoomable nodeStrokeWidth={2} ariaLabel="画布缩略图" />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>

      <div className="canvas-mode-tools" role="toolbar" aria-label="画布操作模式">
        <button className={tool === 'select' ? 'is-active' : ''} onClick={() => setTool('select')} aria-label="选择工具" title="选择工具">
          <MousePointer2 size={19} />
        </button>
        <button className={tool === 'pan' ? 'is-active' : ''} onClick={() => setTool('pan')} aria-label="拖动画布" title="拖动画布">
          <Hand size={19} />
        </button>
      </div>

      <div className="canvas-toolbar" role="toolbar" aria-label="创作画布工具栏">
        <div className="canvas-toolbar__summary">
          <span className="canvas-toolbar__mark"><Sparkles size={16} /></span>
          <span><strong>章节创作画布</strong><small>{assets.length} 个资产 · {scenes.length} 个镜头</small></span>
        </div>
        <span className="canvas-toolbar__divider" />
        <Button variant="ghost" size="sm" onClick={() => fitView({ padding: 0.15, duration: 500 })}>
          <AlignHorizontalDistributeCenter />自动整理
        </Button>
        <Button size="sm" onClick={generateScenes} disabled={generatingScenes}>
          {generatingScenes ? <Loader2 className="animate-spin" /> : <Clapperboard />}
          {scenes.length ? '重新生成分镜' : '生成分镜'}
        </Button>
      </div>

      {!scenes.length && (
        <div className="canvas-empty">
          <span><Clapperboard size={24} /></span>
          <strong>从这一章开始搭建镜头</strong>
          <p>视觉资产已经就位。生成分镜后，可在画布上编辑提示词并逐镜生成视频。</p>
          <Button onClick={generateScenes} disabled={generatingScenes}>生成第一组分镜</Button>
        </div>
      )}
    </main>
  )
}

export function CreativeCanvas(props: CreativeCanvasProps) {
  return <ReactFlowProvider><CreativeCanvasInner {...props} /></ReactFlowProvider>
}
