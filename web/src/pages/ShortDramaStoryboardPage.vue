<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BookOpenText,
  Boxes,
  Check,
  Clapperboard,
  Clock3,
  Copy,
  Ellipsis,
  Film,
  GripVertical,
  ImageIcon,
  LoaderCircle,
  MonitorPlay,
  PanelsTopLeft,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  Upload,
  UsersRound,
  Video,
  Volume2,
  Workflow,
} from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import CreativeCanvas from '@/features/workbench/pages/CreativeCanvas.vue'
import WorkbenchCanvasIdentity from '@/features/workbench/components/WorkbenchCanvasIdentity.vue'
import { api, sleep } from '@/api'
import { notice } from '@/shared/notice'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import type { AiModelConfig, Asset, Chapter, EnumItem, Novel, Scene, Video as VideoResult } from '@/types'

interface ProjectView extends Novel {
  aspectRatio: string
  resolution: string
  style: string
  creationMode: 'agent' | 'manual'
}

interface SceneDraft {
  description: string
  prompt: string
  duration: number
  selectedAssetIds: number[]
  videoGenerationMode: 'reference' | 'keyframes'
  firstFrameUrl: string
  lastFrameUrl: string
}

const terminalTaskStatuses = new Set([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const project = ref<ProjectView | null>(null)
const chapters = ref<Chapter[]>([])
const activeChapterId = ref(0)
const activeChapter = ref<Chapter | null>(null)
const assets = ref<Asset[]>([])
const scenes = ref<Scene[]>([])
const activeSceneId = ref(0)
const configs = ref<AiModelConfig[]>([])
const videoModelTypes = ref<EnumItem[]>([])
const selectedVideoModel = ref('3')
const videos = ref<Record<number, VideoResult[]>>({})
const loading = ref(true)
const generatingChapterIds = ref<Set<number>>(new Set())
const savingSceneIds = ref<Set<number>>(new Set())
const generatingVideoSceneIds = ref<Set<number>>(new Set())
const generationErrors = ref<Record<number, string>>({})
const sceneDrafts = ref<Record<number, SceneDraft>>({})
const openAssetPickers = ref<Set<string>>(new Set())
const uploadingFrameKey = ref('')
const savingCanvasIdentity = ref(false)
let alive = true
let chapterLoadVersion = 0
let sceneObserver: IntersectionObserver | undefined

const isAgent = computed(() => project.value?.creationMode === 'agent')
const workspaceView = computed<'workflow' | 'storyboard'>(() => route.query.view === 'workflow' ? 'workflow' : 'storyboard')
const generatingStoryboard = computed(() => generatingChapterIds.value.has(activeChapterId.value))
const generationError = computed(() => generationErrors.value[activeChapterId.value] || '')
const videoModelOptions = computed(() => (
  videoModelTypes.value.length
    ? videoModelTypes.value.map(item => ({ value: String(item.value), label: item.label }))
    : [{ value: '3', label: configs.value.find(item => item.is_active && item.task_type === 4)?.model || 'Seedance' }]
))
const phaseItems = computed(() => [
  ...(isAgent.value ? [{ label: '剧本', icon: BookOpenText }] : []),
  { label: '设定', icon: Settings2 },
  { label: '分镜', icon: Clapperboard, active: true },
  { label: '视频', icon: Video },
])
const assetGroups = computed(() => [
  { type: AssetTypeEnum.PERSON, label: '出镜角色', icon: UsersRound, items: assets.value.filter(item => item.asset_type === AssetTypeEnum.PERSON) },
  { type: AssetTypeEnum.SCENE, label: '分镜场景', icon: ImageIcon, items: assets.value.filter(item => item.asset_type === AssetTypeEnum.SCENE) },
  { type: AssetTypeEnum.ITEM, label: '场景道具', icon: Boxes, items: assets.value.filter(item => item.asset_type === AssetTypeEnum.ITEM) },
])

function makeSceneDraft(scene: Scene): SceneDraft {
  const metadata = scene?.metadata && typeof scene.metadata === 'object' ? scene.metadata : {}
  return {
    description: scene.description || '',
    prompt: scene.prompt || '',
    duration: scene.duration || 6,
    selectedAssetIds: scene.assets?.map(item => item.id) ?? scene.asset_ids ?? [],
    videoGenerationMode: metadata.video_generation_mode === 'keyframes' ? 'keyframes' : 'reference',
    firstFrameUrl: typeof metadata.first_frame_url === 'string' ? metadata.first_frame_url : '',
    lastFrameUrl: typeof metadata.last_frame_url === 'string' ? metadata.last_frame_url : '',
  }
}

function draftFor(scene: Scene) {
  if (!sceneDrafts.value[scene.id]) sceneDrafts.value[scene.id] = makeSceneDraft(scene)
  return sceneDrafts.value[scene.id]
}

function initializeSceneDrafts(items: Scene[]) {
  sceneDrafts.value = Object.fromEntries(items.map(scene => [scene.id, makeSceneDraft(scene)]))
}

function setSceneBusy(target: typeof savingSceneIds, sceneId: number, value: boolean) {
  const next = new Set(target.value)
  value ? next.add(sceneId) : next.delete(sceneId)
  target.value = next
}

function selectedVideoFor(scene: Scene) {
  return videos.value[scene.id]?.[0]
}

function canGenerateSceneVideo(scene: Scene) {
  const draft = draftFor(scene)
  return Boolean(draft.prompt.trim() && (draft.videoGenerationMode === 'reference' || (draft.firstFrameUrl && draft.lastFrameUrl)))
}

function selectedAssetsFor(scene: Scene, group: (typeof assetGroups.value)[number]) {
  const selectedIds = draftFor(scene).selectedAssetIds
  const sceneText = `${draftFor(scene).description}\n${draftFor(scene).prompt}`.toLocaleLowerCase()
  return group.items.filter(item => {
    if (selectedIds.includes(item.id)) return true
    const referenceNames = [item.canonical_name, ...(item.aliases || [])]
      .map(name => name.trim().toLocaleLowerCase())
      .filter(name => name.length > 1)
    return referenceNames.some(name => sceneText.includes(name))
  })
}

function assetPickerKey(scene: Scene, type: number) {
  return `${scene.id}:${type}`
}

function toggleAssetPicker(scene: Scene, type: number) {
  const key = assetPickerKey(scene, type)
  const next = new Set(openAssetPickers.value)
  next.has(key) ? next.delete(key) : next.add(key)
  openAssetPickers.value = next
}

async function uploadFrame(scene: Scene, kind: 'first' | 'last', event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    notice.error('首尾帧仅支持图片文件')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    notice.error('图片大小不能超过 20MB')
    return
  }
  const uploadKey = `${scene.id}:${kind}`
  uploadingFrameKey.value = uploadKey
  try {
    const uploaded = await api.upload(file)
    const url = `/media/${uploaded.filename}`
    const draft = draftFor(scene)
    if (kind === 'first') draft.firstFrameUrl = url
    else draft.lastFrameUrl = url
    await saveScene(scene, false)
    notice.success(kind === 'first' ? '首帧已上传' : '尾帧已上传')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    if (uploadingFrameKey.value === uploadKey) uploadingFrameKey.value = ''
  }
}

async function setVideoGenerationMode(scene: Scene, mode: 'reference' | 'keyframes') {
  draftFor(scene).videoGenerationMode = mode
  await saveScene(scene, false)
}

function setChapterGenerating(chapterId: number, value: boolean) {
  const next = new Set(generatingChapterIds.value)
  value ? next.add(chapterId) : next.delete(chapterId)
  generatingChapterIds.value = next
}

function setGenerationError(chapterId: number, message = '') {
  generationErrors.value = { ...generationErrors.value, [chapterId]: message }
}

async function fetchChapterScenes(chapterId: number) {
  const briefScenes = (await api.scenes(chapterId)).data.items
  const chapterScenes = await Promise.all(briefScenes.map(async item => (await api.scene(item.id)).data))
  const entries = await Promise.all(chapterScenes.map(async scene => [scene.id, (await api.videos(scene.id)).data.items] as const))
  return { scenes: chapterScenes, videos: Object.fromEntries(entries) as Record<number, VideoResult[]> }
}

function showChapterScenes(result: Awaited<ReturnType<typeof fetchChapterScenes>>) {
  scenes.value = result.scenes
  videos.value = result.videos
  activeSceneId.value = result.scenes[0]?.id || 0
  initializeSceneDrafts(result.scenes)
  void nextTick(setupSceneObserver)
}

async function createManualScene(chapterId = activeChapterId.value) {
  const chapter = chapters.value.find(item => item.id === chapterId)
  if (!chapter) return
  const created = (await api.createScene({
    chapter_id: chapterId,
    sequence: 1,
    description: chapter.name || '新分镜',
    prompt: '',
    duration: 6,
  })).data
  if (activeChapterId.value !== chapterId) return
  scenes.value = [created]
  activeSceneId.value = created.id
  videos.value[created.id] = []
  initializeSceneDrafts([created])
  void nextTick(setupSceneObserver)
}

async function generateChapterStoryboard(chapterId: number) {
  if (!chapterId || generatingChapterIds.value.has(chapterId)) return
  setChapterGenerating(chapterId, true)
  setGenerationError(chapterId)
  try {
    const task = (await api.generateScenes(chapterId)).data
    let current = task
    while (alive && !terminalTaskStatuses.has(current.status)) {
      await sleep(2200)
      current = (await api.task(task.id)).data
    }
    if (!alive) return
    if (current.status !== TaskStatusEnum.COMPLETED) throw new Error(current.error_message || 'Agent 分镜生成失败')
    const result = await fetchChapterScenes(chapterId)
    if (activeChapterId.value === chapterId) showChapterScenes(result)
    const chapterNumber = chapters.value.find(item => item.id === chapterId)?.number || ''
    notice.success(`第 ${chapterNumber} 集分镜已生成`)
  } catch (error) {
    const message = (error as Error).message
    setGenerationError(chapterId, message)
    notice.error(message)
  } finally {
    setChapterGenerating(chapterId, false)
  }
}

async function regenerateStoryboard() {
  const chapterId = activeChapterId.value
  if (!chapterId || generatingChapterIds.value.has(chapterId)) return
  if (!confirm('重新生成会替换本集现有分镜，是否继续？')) return
  const chapterScenes = [...scenes.value]
  setChapterGenerating(chapterId, true)
  setGenerationError(chapterId)
  try {
    await Promise.all(chapterScenes.map(scene => api.deleteScene(scene.id)))
    if (activeChapterId.value === chapterId) {
      scenes.value = []
      activeSceneId.value = 0
      sceneDrafts.value = {}
    }
  } catch (error) {
    setChapterGenerating(chapterId, false)
    notice.error((error as Error).message)
    return
  }
  setChapterGenerating(chapterId, false)
  await generateChapterStoryboard(chapterId)
}

async function loadChapter(chapterId: number) {
  const loadVersion = ++chapterLoadVersion
  activeChapterId.value = chapterId
  activeChapter.value = chapters.value.find(item => item.id === chapterId) ?? null
  scenes.value = []
  videos.value = {}
  activeSceneId.value = 0
  sceneDrafts.value = {}
  loading.value = true
  setGenerationError(chapterId)
  try {
    const [chapterResponse, result] = await Promise.all([
      api.chapter(chapterId),
      fetchChapterScenes(chapterId),
    ])
    if (loadVersion !== chapterLoadVersion || activeChapterId.value !== chapterId) return
    activeChapter.value = chapterResponse.data
    showChapterScenes(result)
    loading.value = false
    if (!result.scenes.length) {
      if (isAgent.value) await generateChapterStoryboard(chapterId)
      else await createManualScene(chapterId)
    }
  } catch (error) {
    if (loadVersion !== chapterLoadVersion || activeChapterId.value !== chapterId) return
    const message = (error as Error).message
    setGenerationError(chapterId, message)
    notice.error(message)
  } finally {
    if (loadVersion === chapterLoadVersion && activeChapterId.value === chapterId) loading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [novelResponse, chapterResponse, assetResponse, configResponse, enumResponse] = await Promise.all([
      api.novel(projectId.value),
      api.chapters(projectId.value),
      api.assets(projectId.value),
      api.configs(),
      api.enums(),
    ])
    const settings = readShortDramaSettings(novelResponse.data)
    project.value = {
      ...novelResponse.data,
      aspectRatio: settings.aspectRatio || '9:16',
      resolution: settings.resolution || '720p',
      style: settings.style || '写实通用',
      creationMode: novelResponse.data.author?.includes('Agent') ? 'agent' : 'manual',
    }
    chapters.value = chapterResponse.data.items
    assets.value = assetResponse.data.items
    configs.value = configResponse.data.items
    videoModelTypes.value = enumResponse.data.video_model_type || []
    const preferredChapter = Number(route.query.chapter)
    const firstChapter = chapters.value.find(item => item.id === preferredChapter) ?? chapters.value[0]
    if (firstChapter) {
      if (preferredChapter !== firstChapter.id) {
        void router.replace({ query: { ...route.query, chapter: String(firstChapter.id) } })
      }
      await loadChapter(firstChapter.id)
    }
    else loading.value = false
  } catch (error) {
    const message = (error as Error).message
    setGenerationError(activeChapterId.value, message)
    notice.error(message)
    loading.value = false
  }
}

function selectScene(scene: Scene) {
  activeSceneId.value = scene.id
  document.getElementById(`scene-${scene.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function setupSceneObserver() {
  sceneObserver?.disconnect()
  if (typeof IntersectionObserver === 'undefined') return
  sceneObserver = new IntersectionObserver((entries) => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
    const sceneId = Number((visible?.target as HTMLElement | undefined)?.dataset.sceneId)
    if (sceneId) activeSceneId.value = sceneId
  }, { rootMargin: '-84px 0px -42% 0px', threshold: [0.08, 0.25, 0.5, 0.75] })
  document.querySelectorAll<HTMLElement>('[data-scene-id]').forEach(element => sceneObserver?.observe(element))
}

function toggleAsset(scene: Scene, assetId: number) {
  const draft = draftFor(scene)
  draft.selectedAssetIds = draft.selectedAssetIds.includes(assetId)
    ? draft.selectedAssetIds.filter(id => id !== assetId)
    : [...draft.selectedAssetIds, assetId]
}

async function saveScene(scene: Scene, showNotice = true) {
  const draft = draftFor(scene)
  setSceneBusy(savingSceneIds, scene.id, true)
  try {
    const updated = (await api.updateScene(scene.id, {
      description: draft.description,
      prompt: draft.prompt,
      duration: draft.duration,
      asset_ids: draft.selectedAssetIds,
      metadata: {
        ...(scene.metadata || {}),
        video_generation_mode: draft.videoGenerationMode,
        first_frame_url: draft.firstFrameUrl || undefined,
        last_frame_url: draft.lastFrameUrl || undefined,
      },
    })).data
    scenes.value = scenes.value.map(item => item.id === updated.id ? updated : item)
    if (showNotice) notice.success('分镜已保存')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    setSceneBusy(savingSceneIds, scene.id, false)
  }
}

async function addScene() {
  if (!activeChapter.value) return
  try {
    const created = (await api.createScene({
      chapter_id: activeChapter.value.id,
      sequence: Math.max(0, ...scenes.value.map(item => item.sequence)) + 1,
      description: '新分镜',
      prompt: '',
      duration: 6,
    })).data
    scenes.value.push(created)
    videos.value[created.id] = []
    sceneDrafts.value[created.id] = makeSceneDraft(created)
    await nextTick()
    setupSceneObserver()
    selectScene(created)
    notice.success('已添加分镜')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function duplicateScene(scene: Scene) {
  if (!scene || !activeChapter.value) return
  const draft = draftFor(scene)
  try {
    const created = (await api.createScene({
      chapter_id: activeChapter.value.id,
      sequence: Math.max(0, ...scenes.value.map(item => item.sequence)) + 1,
      description: draft.description,
      prompt: draft.prompt,
      duration: draft.duration,
      asset_ids: draft.selectedAssetIds,
    })).data
    scenes.value.push(created)
    videos.value[created.id] = []
    sceneDrafts.value[created.id] = makeSceneDraft(created)
    await nextTick()
    setupSceneObserver()
    selectScene(created)
    notice.success('分镜已复制')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function removeScene(scene: Scene) {
  if (!scene || !confirm(`删除分镜 ${scene.sequence}？`)) return
  try {
    await api.deleteScene(scene.id)
    scenes.value = scenes.value.filter(item => item.id !== scene.id)
    delete sceneDrafts.value[scene.id]
    const next = scenes.value.find(item => item.sequence > scene.sequence) ?? scenes.value.at(-1)
    activeSceneId.value = next?.id || 0
    await nextTick()
    setupSceneObserver()
    if (next) selectScene(next)
    notice.success('分镜已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function generateVideo(scene: Scene) {
  const draft = draftFor(scene)
  setSceneBusy(generatingVideoSceneIds, scene.id, true)
  try {
    await saveScene(scene, false)
    let result = (await api.generateVideo(scene.id, Number(selectedVideoModel.value), {
      generation_mode: draft.videoGenerationMode,
      first_frame_url: draft.firstFrameUrl || undefined,
      last_frame_url: draft.lastFrameUrl || undefined,
    })).data
    videos.value[scene.id] = [result, ...(videos.value[scene.id] || [])]
    while (alive && !terminalTaskStatuses.has(result.status)) {
      await sleep(4000)
      result = (await api.queryVideo(result.id)).data
      videos.value[scene.id] = videos.value[scene.id].map(item => item.id === result.id ? result : item)
    }
    if (!alive) return
    result.status === TaskStatusEnum.COMPLETED
      ? notice.success('分镜视频生成完成')
      : notice.error(String(result.metadata?.error || '视频生成失败'))
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    setSceneBusy(generatingVideoSceneIds, scene.id, false)
  }
}

function selectPhase(label: string) {
  const query = activeChapterId.value ? { chapter: String(activeChapterId.value) } : undefined
  if (label === '剧本' && isAgent.value) void router.push({ path: `/create/short-drama/agent/${projectId.value}`, query })
  if (label === '设定') void router.push({ path: `/create/short-drama/manual/${projectId.value}`, query })
}

function returnToProjects() {
  void router.push('/projects')
}

function selectWorkspaceView(view: 'workflow' | 'storyboard') {
  if (workspaceView.value === view) return
  const query = { ...route.query }
  if (view === 'workflow') query.view = 'workflow'
  else delete query.view
  void router.replace({ query })
}

async function renameCanvas(name: string) {
  if (!activeChapter.value || savingCanvasIdentity.value) return
  savingCanvasIdentity.value = true
  try {
    const updated = (await api.updateChapter(activeChapter.value.id, { name })).data
    activeChapter.value = updated
    chapters.value = chapters.value.map(chapter => chapter.id === updated.id ? updated : chapter)
    notice.success('画布名称已保存')
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '画布名称保存失败')
  } finally {
    savingCanvasIdentity.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  alive = false
  sceneObserver?.disconnect()
})
</script>

<template>
  <main class="storyboard-page" :class="{ 'is-workflow-view': workspaceView === 'workflow' }">
    <header class="storyboard-topbar">
      <div class="project-heading">
        <AppButton variant="ghost" size="sm" icon-only aria-label="返回项目" @click="returnToProjects"><ArrowLeft :size="18" /></AppButton>
        <div v-if="workspaceView === 'storyboard'"><strong>{{ project?.name || '短剧项目' }}</strong><span><Film :size="13" />{{ project?.aspectRatio || '9:16' }}<i />{{ project?.resolution || '720p' }}<i />{{ project?.style || '写实通用' }}</span></div>
        <WorkbenchCanvasIdentity v-else-if="activeChapter" :name="activeChapter.name" :chapter-number="activeChapter.number" :saving="savingCanvasIdentity" @rename="renameCanvas" />
      </div>
      <nav v-if="workspaceView === 'storyboard'" class="phase-nav" aria-label="短剧制作流程">
        <template v-for="(phase, index) in phaseItems" :key="phase.label">
          <span v-if="index" />
          <AppButton variant="soft" size="sm" :active="phase.active" :aria-current="phase.active ? 'step' : undefined" @click="selectPhase(phase.label)"><component :is="phase.icon" :size="16" />{{ phase.label }}</AppButton>
        </template>
      </nav>
      <nav class="workspace-view-switch" aria-label="分镜视图">
        <AppButton variant="ghost" size="sm" :active="workspaceView === 'workflow'" :aria-pressed="workspaceView === 'workflow'" @click="selectWorkspaceView('workflow')"><Workflow :size="14" />工作流</AppButton>
        <AppButton variant="ghost" size="sm" :active="workspaceView === 'storyboard'" :aria-pressed="workspaceView === 'storyboard'" @click="selectWorkspaceView('storyboard')"><PanelsTopLeft :size="14" />故事板</AppButton>
      </nav>
    </header>

    <div class="storyboard-shell">
      <aside v-if="workspaceView === 'storyboard'" class="shot-rail">
        <strong>分镜</strong>
        <AppScrollArea class="scene-list" aria-label="本集分镜列表">
          <AppButton v-for="scene in scenes" :key="scene.id" variant="soft" size="sm" icon-only :active="activeSceneId === scene.id" :aria-label="`分镜 ${scene.sequence}`" @click="selectScene(scene)">{{ scene.sequence }}</AppButton>
          <AppButton v-if="!loading && !generatingStoryboard" variant="ghost" size="sm" icon-only aria-label="添加分镜" @click="addScene"><Plus :size="16" /></AppButton>
        </AppScrollArea>
      </aside>

      <section class="storyboard-main" :class="{ 'is-workflow-view': workspaceView === 'workflow' }">
        <header v-if="workspaceView === 'storyboard'" class="chapter-toolbar">
          <div><span :class="{ 'is-agent': isAgent }">{{ isAgent ? 'AGENT STORYBOARD' : 'MANUAL STORYBOARD' }}</span><h1>第 {{ activeChapter?.number || '-' }} 集 · {{ activeChapter?.name || '分镜制作' }}</h1><p>{{ activeChapter?.content?.slice(0, 120) }}</p></div>
          <div class="chapter-actions">
            <AppSelect v-model="selectedVideoModel" ariaLabel="视频模型" :options="videoModelOptions" :menu-width="220" align="end" />
            <AppButton v-if="isAgent" variant="secondary" size="sm" :loading="generatingStoryboard" @click="regenerateStoryboard"><Sparkles v-if="!generatingStoryboard" :size="15" />{{ generatingStoryboard ? 'Agent 生成中' : '重新生成分镜' }}</AppButton>
            <AppButton variant="primary" size="sm" @click="addScene"><Plus :size="15" />添加分镜</AppButton>
          </div>
        </header>

        <div v-if="loading || generatingStoryboard" class="storyboard-state"><LoaderCircle :size="28" /><strong>{{ generatingStoryboard ? `Agent 正在生成第 ${activeChapter?.number || '-'} 集的全部分镜` : `正在读取第 ${activeChapter?.number || '-'} 集分镜` }}</strong><p>{{ generatingStoryboard ? '仅处理当前选中的这一集，不会自动生成其他集。' : '正在准备本集章节、资产和视频信息。' }}</p></div>
        <div v-else-if="generationError && !scenes.length" class="storyboard-state is-error"><Clapperboard :size="28" /><strong>暂时无法生成分镜</strong><p>{{ generationError }}</p><AppButton variant="primary" size="sm" @click="isAgent ? generateChapterStoryboard(activeChapterId) : createManualScene()">重试</AppButton></div>
        <div v-else-if="workspaceView === 'workflow'" class="workflow-canvas-shell">
          <CreativeCanvas :key="`workflow-${activeChapterId}`" :novel-id="projectId" :chapter-id="activeChapterId" />
        </div>
        <div v-else class="shot-editor-list">
          <article v-for="scene in scenes" :id="`scene-${scene.id}`" :key="scene.id" class="shot-editor" :class="{ 'is-active': activeSceneId === scene.id }" :data-scene-id="scene.id">
            <header class="shot-editor-header">
              <div class="shot-editor-heading">
                <GripVertical class="drag-mark" :size="16" /><strong>分镜 {{ scene.sequence }}</strong><small>ID {{ scene.id }}</small>
                <nav aria-label="视频生成方式">
                  <AppButton variant="soft" size="sm" :active="draftFor(scene).videoGenerationMode === 'reference'" :aria-pressed="draftFor(scene).videoGenerationMode === 'reference'" @click="setVideoGenerationMode(scene, 'reference')"><span class="mode-dot" />全能参考生视频</AppButton>
                  <AppButton variant="soft" size="sm" :active="draftFor(scene).videoGenerationMode === 'keyframes'" :aria-pressed="draftFor(scene).videoGenerationMode === 'keyframes'" @click="setVideoGenerationMode(scene, 'keyframes')"><span class="mode-dot" />首尾帧生视频</AppButton>
                </nav>
              </div>
              <div><AppButton variant="ghost" size="sm" icon-only aria-label="复制分镜" @click="duplicateScene(scene)"><Copy :size="15" /></AppButton><AppButton variant="danger" size="sm" icon-only aria-label="删除分镜" @click="removeScene(scene)"><Trash2 :size="15" /></AppButton></div>
            </header>

            <div class="shot-editor-grid">
              <aside class="shot-info-panel">
                <h2>分镜信息</h2>
                <label><span>分镜描述</span><textarea v-model="draftFor(scene).description" rows="5" placeholder="请输入分镜描述" /></label>
                <section v-for="group in assetGroups" :key="group.type" class="shot-assets">
                  <header><span><component :is="group.icon" :size="15" />{{ group.label }}</span><span><small>{{ selectedAssetsFor(scene, group).length }}/{{ group.items.length }}</small><AppButton variant="ghost" size="sm" icon-only :aria-label="`选择${group.label}`" @click="toggleAssetPicker(scene, group.type)"><Plus :size="15" /></AppButton></span></header>
                  <div v-if="selectedAssetsFor(scene, group).length" class="selected-assets" :class="{ 'is-scene-assets': group.type === AssetTypeEnum.SCENE }">
                    <article v-for="asset in selectedAssetsFor(scene, group)" :key="asset.id" class="selected-asset-row">
                      <span class="asset-thumb"><img v-if="asset.main_image" :src="asset.main_image" :alt="asset.canonical_name" /><component v-else :is="group.icon" :size="16" /></span>
                      <AppButton variant="soft" size="sm" class="asset-name-button"><span>{{ asset.canonical_name }}</span></AppButton>
                      <AppButton v-if="group.type === AssetTypeEnum.PERSON" variant="soft" size="sm" class="asset-voice-button"><Volume2 :size="13" /><span>未配置音色</span></AppButton>
                      <AppButton variant="ghost" size="sm" icon-only aria-label="管理资产" @click="toggleAssetPicker(scene, group.type)"><Ellipsis :size="15" /></AppButton>
                    </article>
                  </div>
                  <p v-else>暂未选择{{ group.label.replace('分镜', '').replace('出镜', '') }}</p>
                  <div v-if="openAssetPickers.has(assetPickerKey(scene, group.type))" class="asset-picker">
                    <AppButton v-for="asset in group.items" :key="asset.id" variant="ghost" size="sm" :active="draftFor(scene).selectedAssetIds.includes(asset.id)" :aria-pressed="draftFor(scene).selectedAssetIds.includes(asset.id)" @click="toggleAsset(scene, asset.id)"><span class="asset-picker-thumb"><img v-if="asset.main_image" :src="asset.main_image" :alt="asset.canonical_name" /><component v-else :is="group.icon" :size="14" /></span><span>{{ asset.canonical_name }}</span><Check v-if="draftFor(scene).selectedAssetIds.includes(asset.id)" :size="13" /></AppButton>
                  </div>
                </section>
              </aside>

              <section class="prompt-panel" :class="{ 'has-keyframes': draftFor(scene).videoGenerationMode === 'keyframes' }">
                <header><div><span><strong>分镜视频生成</strong><small>组合角色、场景和动作，生成连续镜头</small></span></div><AppButton variant="secondary" size="sm" :loading="savingSceneIds.has(scene.id)" @click="saveScene(scene)"><Save v-if="!savingSceneIds.has(scene.id)" :size="14" />保存</AppButton></header>
                <div v-if="draftFor(scene).videoGenerationMode === 'keyframes'" class="keyframe-inputs">
                  <label :class="{ 'has-image': draftFor(scene).firstFrameUrl }"><input type="file" accept="image/png,image/jpeg,image/webp" @change="uploadFrame(scene, 'first', $event)" /><img v-if="draftFor(scene).firstFrameUrl" :src="draftFor(scene).firstFrameUrl" alt="首帧" /><span v-else><LoaderCircle v-if="uploadingFrameKey === `${scene.id}:first`" :size="18" /><Upload v-else :size="18" /><strong>上传首帧</strong><small>视频开始画面</small></span><i>首帧</i></label>
                  <span>→</span>
                  <label :class="{ 'has-image': draftFor(scene).lastFrameUrl }"><input type="file" accept="image/png,image/jpeg,image/webp" @change="uploadFrame(scene, 'last', $event)" /><img v-if="draftFor(scene).lastFrameUrl" :src="draftFor(scene).lastFrameUrl" alt="尾帧" /><span v-else><LoaderCircle v-if="uploadingFrameKey === `${scene.id}:last`" :size="18" /><Upload v-else :size="18" /><strong>上传尾帧</strong><small>视频结束画面</small></span><i>尾帧</i></label>
                </div>
                <div class="prompt-reference-bar"><AppButton variant="soft" size="sm" icon-only aria-label="添加参考素材"><Plus :size="14" /></AppButton><span>使用 @ 引用角色、场景、道具、音色及参考素材，编辑更灵活，分镜更精准</span></div>
                <textarea v-model="draftFor(scene).prompt" placeholder="请输入分镜视频提示词。描述镜头、主体动作、运镜、光线、画面风格和声音。" />
                <footer>
                  <div><AppSelect v-model="selectedVideoModel" ariaLabel="视频模型" :options="videoModelOptions" :menu-width="220" /><span><Clock3 :size="14" /><input v-model.number="draftFor(scene).duration" type="number" min="1" max="30" />s</span><span>{{ project?.resolution || '720p' }}</span><span>1x</span></div>
                  <AppButton variant="primary" size="md" :aria-label="`生成视频，预计消耗 ${draftFor(scene).duration * 150}`" :disabled="!canGenerateSceneVideo(scene)" :loading="generatingVideoSceneIds.has(scene.id)" @click="generateVideo(scene)"><Sparkles v-if="!generatingVideoSceneIds.has(scene.id)" :size="14" />{{ generatingVideoSceneIds.has(scene.id) ? '生成中' : draftFor(scene).duration * 150 }}</AppButton>
                </footer>
              </section>

              <aside class="preview-panel">
                <header><strong>视频预览</strong><RefreshCw :size="15" /></header>
                <div class="preview-stage">
                  <video v-if="selectedVideoFor(scene)?.url" :src="selectedVideoFor(scene)?.url" controls playsinline />
                  <div v-else-if="generatingVideoSceneIds.has(scene.id) || (selectedVideoFor(scene) && !terminalTaskStatuses.has(selectedVideoFor(scene)!.status))" class="preview-empty is-running"><LoaderCircle :size="30" /><strong>视频生成中</strong><span>完成后将在这里自动播放</span></div>
                  <div v-else class="preview-empty"><MonitorPlay :size="32" /><strong>等待生成视频</strong><span>完善提示词后点击“生成视频”</span></div>
                </div>
                <footer v-if="selectedVideoFor(scene)" class="preview-timeline"><AppButton variant="soft" size="sm" class="preview-clip" :aria-label="`当前分镜视频 ${selectedVideoFor(scene)!.id}`"><video v-if="selectedVideoFor(scene)?.url" :src="selectedVideoFor(scene)?.url" muted playsinline /><MonitorPlay v-else :size="16" /><small>当前分镜</small></AppButton></footer>
              </aside>
            </div>
          </article>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.storyboard-page { min-width: 0; min-height: 100%; overflow-x: hidden; color: #303442; background: #f7f8fb; }
.storyboard-page.is-workflow-view { height: 100vh; overflow: hidden; }
.storyboard-topbar { position: sticky; top: 0; z-index: 30; display: grid; min-height: 64px; grid-template-columns: minmax(280px,1fr) auto minmax(280px,1fr); align-items: center; padding: 5px 18px; background: rgb(255 255 255 / 97%); box-shadow: 0 1px 0 #eceef3; backdrop-filter: blur(16px); }
.storyboard-page.is-workflow-view .storyboard-topbar { position: fixed; right: 0; left: 0; min-height: 0; grid-template-columns: 1fr auto; padding: 14px 18px; pointer-events: none; background: transparent; box-shadow: none; backdrop-filter: none; }
.project-heading { display: flex; min-width: 0; align-items: center; gap: 12px; }
.storyboard-page.is-workflow-view .project-heading { pointer-events: none; }
.storyboard-page.is-workflow-view .project-heading > button { pointer-events: auto; color: #eee9e2; background: rgb(33 30 27 / 92%); box-shadow: inset 0 0 0 1px #3b3631, 0 8px 24px rgb(0 0 0 / 24%); backdrop-filter: blur(12px); }
.storyboard-page.is-workflow-view .project-heading > button:hover { color: #fff; background: #2a2622; }
.storyboard-page.is-workflow-view .project-heading > :deep(.workbench-canvas-identity) { pointer-events: auto; }
.project-heading > div { display: grid; min-width: 0; gap: 5px; }
.project-heading strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.project-heading span { display: flex; align-items: center; gap: 7px; color: #9298a8; font-size: 10px; }
.project-heading i { width: 1px; height: 10px; background: #dfe2e9; }
.phase-nav { grid-column: 2; display: flex; align-items: center; }
.phase-nav > span { width: 18px; height: 1px; background: #e2e4eb; }
.phase-nav button { display: flex; width: 64px; min-height: 50px; flex-direction: column; gap: 3px; border-radius: 16px; color: #858b9a; background: #fff; font-size: 10px; }
.phase-nav button.is-active { color: #5b5cf6; background: #f0f0ff; box-shadow: 0 8px 22px rgb(91 92 246 / 11%); }
.storyboard-shell { min-height: calc(100vh - 64px); }
.storyboard-page.is-workflow-view .storyboard-shell { height: 100vh; min-height: 0; }
.shot-rail { position: fixed; top: 64px; bottom: 0; left: 0; z-index: 24; display: grid; width: 48px; align-content: start; justify-items: center; gap: 10px; padding: 14px 5px; background: #fff; box-shadow: 1px 0 0 #eceef3; }
.shot-rail > strong { color: #777d8d; font-size: 11px; }
.scene-list { display: grid; width: 100%; max-height: calc(100vh - 112px); justify-items: center; gap: 8px; padding: 2px 2px 12px; }
.shot-rail button { width: 34px; min-height: 34px; border-radius: 8px; }
.storyboard-main { min-width: 0; margin-left: 48px; padding: 16px 16px 42px; }
.storyboard-main.is-workflow-view { height: 100%; margin-left: 0; padding: 0; }
.chapter-toolbar { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.chapter-toolbar > div:first-child { min-width: 0; }
.chapter-toolbar > div:first-child > span { color: #8c91a0; font-size: 8px; font-weight: 750; letter-spacing: .15em; }
.chapter-toolbar > div:first-child > span.is-agent { color: #6163ef; }
.chapter-toolbar h1 { margin: 5px 0 6px; font-size: 19px; }
.chapter-toolbar p { max-width: 760px; margin: 0; overflow: hidden; color: #898f9e; font-size: 10px; line-height: 1.6; text-overflow: ellipsis; white-space: nowrap; }
.chapter-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }
.workspace-view-switch { grid-column: 3; display: flex; justify-self: end; align-items: center; gap: 3px; padding: 3px; border-radius: 11px; background: #f1f2f7; box-shadow: inset 0 0 0 1px #e5e7ef; }
.workspace-view-switch button { min-height: 32px; gap: 6px; padding-inline: 11px; border-radius: 8px; color: #777d8d; background: transparent; box-shadow: none; font-size: 11px; }
.workspace-view-switch button:hover { color: #575d6d; background: rgb(255 255 255 / 68%); }
.workspace-view-switch button.is-active { color: #5759eb; background: #fff; box-shadow: 0 3px 10px rgb(47 50 80 / 9%); }
.workspace-view-switch button:focus-visible { outline: 2px solid rgb(91 92 246 / 22%); outline-offset: 1px; }
.storyboard-page.is-workflow-view .workspace-view-switch { grid-column: 2; pointer-events: auto; background: rgb(33 30 27 / 92%); box-shadow: inset 0 0 0 1px #3b3631, 0 8px 24px rgb(0 0 0 / 24%); backdrop-filter: blur(12px); }
.storyboard-page.is-workflow-view .workspace-view-switch button { color: #c7bdb4; }
.storyboard-page.is-workflow-view .workspace-view-switch button:hover { color: #eee9e2; background: #2a2622; }
.storyboard-page.is-workflow-view .workspace-view-switch button.is-active { color: #eee9e2; background: #3a354f; box-shadow: inset 0 0 0 1px rgb(169 149 255 / 22%); }
.storyboard-page.is-workflow-view .workspace-view-switch button:focus-visible { outline-color: rgb(169 149 255 / 34%); }
.workflow-canvas-shell { width: 100%; height: 100%; min-height: 0; overflow: hidden; background: #151412; }
.storyboard-state { display: grid; min-height: calc(100vh - 210px); place-items: center; align-content: center; gap: 8px; color: #686ef1; text-align: center; }
.storyboard-state svg { animation: spin 1s linear infinite; }
.storyboard-state strong { color: #454a59; font-size: 14px; }
.storyboard-state p { max-width: 460px; margin: 0; color: #9297a6; font-size: 11px; }
.storyboard-state.is-error svg { color: #bf6470; animation: none; }
.storyboard-state button { margin-top: 8px; }
.shot-editor-list { display: grid; gap: 12px; }
.shot-editor { overflow: hidden; scroll-margin-top: 78px; border-radius: 16px; background: #fff; box-shadow: inset 0 0 0 1px #e9ebf2; }
.shot-editor.is-active { box-shadow: inset 0 0 0 1px #dfe1f5; }
.shot-editor-header { display: flex; min-height: 48px; align-items: center; justify-content: space-between; padding: 0 12px; background: #fbfbfd; }
.shot-editor-header > div { display: flex; align-items: center; gap: 7px; }
.shot-editor-heading > nav { display: flex; align-items: center; gap: 2px; margin-left: 8px; padding: 3px; border-radius: 9px; background: #f1f2f7; }
.shot-editor-heading > nav button { min-height: 28px; padding-inline: 9px; color: #747a89; background: transparent; box-shadow: none; font-size: 9px; }
.shot-editor-heading > nav button.is-active { color: #5658ea; background: #fff; box-shadow: 0 2px 8px rgb(46 49 70 / 7%); }
.mode-dot { width: 11px; height: 11px; border: 1px solid #d9dce6; border-radius: 50%; background: #fff; }
.shot-editor-heading > nav button.is-active .mode-dot { border: 3px solid #6264ef; }
.shot-editor-header strong { font-size: 12px; }
.shot-editor-header small { padding: 3px 5px; border-radius: 5px; color: #7476df; background: #efefff; font-size: 8px; }
.drag-mark { color: #9ba0ae; font-size: 17px; }
.shot-editor-grid { display: grid; min-height: 630px; grid-template-columns: 410px minmax(600px,3fr) minmax(520px,2fr); gap: 12px; padding: 12px; background: #f8f9fc; }
.shot-info-panel,.prompt-panel,.preview-panel { min-width: 0; border-radius: 12px; background: #fff; box-shadow: inset 0 0 0 1px #e7e9f0; }
.shot-info-panel { display: grid; align-content: start; gap: 16px; padding: 16px; overflow-y: auto; }
.shot-info-panel h2,.prompt-panel strong,.preview-panel strong { margin: 0; font-size: 13px; }
.shot-info-panel label { display: grid; gap: 7px; color: #686e7d; font-size: 10px; }
.shot-info-panel textarea,.prompt-panel textarea { width: 100%; border: 0; outline: 0; color: #3e4351; background: #f7f8fb; font: inherit; resize: none; }
.shot-info-panel textarea { padding: 11px; border-radius: 9px; font-size: 11px; line-height: 1.65; box-shadow: inset 0 0 0 1px #e1e4ec; }
.shot-info-panel textarea:focus,.prompt-panel textarea:focus { box-shadow: inset 0 0 0 2px rgb(91 92 246 / 14%); }
.shot-assets { display: grid; gap: 8px; }
.shot-assets > header { display: flex; align-items: center; justify-content: space-between; color: #525867; font-size: 10px; font-weight: 650; }
.shot-assets > header > span { display: inline-flex; align-items: center; gap: 6px; }
.shot-assets > header > span:last-child { display: flex; align-items: center; gap: 2px; }
.shot-assets > header small { color: #9a9fac; font-weight: 400; }
.shot-assets > header button { width: 26px; min-height: 26px; padding: 0; }
.selected-assets { display: grid; gap: 7px; }
.selected-asset-row { display: grid; grid-template-columns: 38px minmax(0,1fr) 116px 30px; align-items: center; gap: 6px; }
.selected-asset-row > button { min-width: 0; justify-content: flex-start; }
.selected-asset-row .asset-name-button { padding-inline: 9px; color: #4c5261; background: #fff; box-shadow: inset 0 0 0 1px #e0e3eb; }
.selected-asset-row .asset-name-button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-asset-row .asset-voice-button { color: #a0a5b2; background: #fafbfc; box-shadow: inset 0 0 0 1px #eceef3; font-size: 9px; }
.selected-assets.is-scene-assets .selected-asset-row { grid-template-columns: 1fr 30px; align-items: end; }
.selected-assets.is-scene-assets .asset-thumb { grid-column: 1 / -1; width: 180px; height: 108px; border-radius: 10px; }
.selected-assets.is-scene-assets .asset-name-button { grid-column: 1; }
.asset-thumb { display: grid; width: 38px; height: 38px; flex: 0 0 38px; overflow: hidden; place-items: center; border-radius: 7px; color: #959baa; background: #e9ebf1; }
.asset-thumb img { width: 100%; height: 100%; object-fit: cover; }
.shot-assets > p { display: grid; min-height: 52px; margin: 0; place-items: center; border-radius: 9px; color: #a1a6b3; background: #f7f8fb; font-size: 9px; }
.asset-picker { display: grid; max-height: 180px; gap: 4px; overflow-y: auto; padding: 6px; border-radius: 10px; background: #f7f8fb; }
.asset-picker button { width: 100%; justify-content: flex-start; color: #646a79; }
.asset-picker button > span:nth-child(2) { min-width: 0; flex: 1; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.asset-picker-thumb { display: grid; width: 26px; height: 26px; overflow: hidden; place-items: center; border-radius: 6px; background: #e8eaf0; }
.asset-picker-thumb img { width: 100%; height: 100%; object-fit: cover; }
.prompt-panel { display: grid; grid-template-rows: auto auto minmax(0,1fr) auto; }
.prompt-panel.has-keyframes { grid-template-rows: auto auto auto minmax(0,1fr) auto; }
.prompt-panel > header { display: flex; min-height: 62px; align-items: center; justify-content: space-between; padding: 0 16px; }
.prompt-panel > header > div { display: flex; min-width: 0; align-items: center; gap: 10px; color: #343945; }
.prompt-panel > header span { display: grid; min-width: 0; gap: 3px; }
.prompt-panel > header small { color: #9a9fac; font-size: 9px; font-weight: 400; }
.keyframe-inputs { display: grid; grid-template-columns: minmax(0,1fr) auto minmax(0,1fr); align-items: center; gap: 10px; padding: 0 16px 14px; }
.keyframe-inputs > span { color: #a0a5b2; font-size: 16px; }
.keyframe-inputs label { position: relative; display: grid; min-height: 112px; overflow: hidden; place-items: center; border-radius: 12px; color: #858b9a; background: #f7f8fb; box-shadow: inset 0 0 0 1px #e8eaf1; cursor: pointer; }
.keyframe-inputs label:hover { color: #5d5fee; background: #f4f4ff; box-shadow: inset 0 0 0 1px #cdcffa; }
.keyframe-inputs input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.keyframe-inputs img { width: 100%; height: 112px; object-fit: cover; }
.keyframe-inputs label > span { display: grid; place-items: center; gap: 4px; }
.keyframe-inputs label > span svg { margin-bottom: 2px; }
.keyframe-inputs label > span strong { color: currentColor; font-size: 11px; }
.keyframe-inputs label > span small { color: #a1a6b3; font-size: 9px; }
.keyframe-inputs label > i { position: absolute; top: 8px; left: 8px; padding: 4px 7px; border-radius: 7px; color: #5e60e9; background: rgb(255 255 255 / 92%); box-shadow: 0 3px 10px rgb(37 40 58 / 8%); font-size: 9px; font-style: normal; font-weight: 700; }
.prompt-reference-bar { display: flex; align-items: center; gap: 8px; padding: 0 16px 8px; color: #b0b4c0; font-size: 9px; }
.prompt-reference-bar button { width: 34px; min-height: 34px; flex: 0 0 34px; border-radius: 9px; }
.prompt-panel > textarea { min-height: 420px; padding: 8px 16px 18px; background: #fff; font-size: 11px; line-height: 1.8; white-space: pre-wrap; }
.prompt-panel > footer { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px; background: #fbfbfd; }
.prompt-panel > footer > div { display: flex; min-width: 0; align-items: center; gap: 6px; }
.prompt-panel > footer > div > span { display: inline-flex; min-height: 34px; align-items: center; gap: 4px; padding: 0 10px; border-radius: 9px; color: #777d8d; background: #fff; box-shadow: 0 1px 3px rgb(35 39 55 / 8%); font-size: 10px; }
.prompt-panel input { width: 23px; padding: 0; border: 0; outline: 0; color: #555b6a; background: transparent; font: inherit; text-align: right; }
.preview-panel { display: grid; grid-template-rows: 48px minmax(0,1fr) 58px; overflow: hidden; }
.preview-panel > header { display: flex; align-items: center; justify-content: space-between; padding: 0 15px; }
.preview-panel > header svg { color: #9197a6; }
.preview-stage { display: grid; min-height: 520px; overflow: hidden; place-items: center; background: #292e39; }
.preview-stage video { width: 100%; height: 100%; object-fit: contain; }
.preview-empty { display: grid; place-items: center; gap: 8px; color: #7f8798; text-align: center; }
.preview-empty svg { color: #8e96a8; }
.preview-empty strong { color: #c8ccd4; font-size: 12px; }
.preview-empty span { font-size: 9px; }
.preview-empty.is-running svg { color: #8587ff; animation: spin 1s linear infinite; }
.preview-timeline { display: grid; min-height: 58px; place-items: center; padding: 5px 10px; background: #fff; }
.preview-timeline .preview-clip { position: relative; display: grid; width: 46px; min-height: 46px; overflow: visible; place-items: center; padding: 2px; border-radius: 7px; color: #6264ef; background: #fff; box-shadow: inset 0 0 0 2px #696bff; }
.preview-clip video { width: 40px; height: 40px; border-radius: 5px; object-fit: cover; }
.preview-clip small { position: absolute; right: 1px; bottom: 1px; left: 1px; padding: 2px; border-radius: 0 0 5px 5px; color: #fff; background: #6264ef; font-size: 7px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) { .shot-editor-grid { grid-template-columns: 260px minmax(380px,1fr); }.preview-panel { grid-column: 1 / -1; }.preview-stage { min-height: 420px; max-height: 560px; } }
@media (max-width: 820px) { .storyboard-topbar { position: static; grid-template-columns: 1fr auto; gap: 8px; padding: 10px 14px; }.storyboard-page.is-workflow-view .storyboard-topbar { position: fixed; padding: 12px 14px; }.phase-nav { grid-column: 1 / -1; grid-row: 2; justify-content: center; }.workspace-view-switch { grid-column: 2; grid-row: 1; flex: 0 0 auto; }.storyboard-page.is-workflow-view .storyboard-shell { height: 100vh; }.shot-rail { top: 126px; bottom: auto; z-index: 20; display: flex; width: 100%; height: 56px; align-items: center; justify-items: initial; padding: 9px 14px; overflow: hidden; }.shot-rail > .scene-list { display: flex; max-height: none; justify-items: initial; overflow-x: auto; overflow-y: hidden; padding: 0; }.storyboard-main { margin-left: 0; padding: 74px 14px 36px; }.storyboard-main.is-workflow-view { height: 100%; padding: 0; }.chapter-toolbar { flex-direction: column; }.chapter-actions { width: 100%; overflow-x: auto; padding-bottom: 4px; }.workflow-canvas-shell { min-height: 520px; }.shot-editor-header { flex-wrap: wrap; gap: 6px; padding-block: 7px; }.shot-editor-header > nav { order: 3; width: 100%; }.shot-editor-grid { grid-template-columns: 1fr; }.preview-panel { grid-column: 1; }.shot-info-panel { max-height: none; }.prompt-panel > footer { align-items: stretch; flex-direction: column; }.prompt-panel > footer > div { overflow-x: auto; }.prompt-panel > footer > button { width: 100%; } }
@media (max-width: 520px) { .phase-nav button { width: 54px; }.phase-nav > span { width: 7px; }.chapter-toolbar p { white-space: normal; }.shot-editor-grid { padding: 7px; }.prompt-panel > textarea { min-height: 320px; }.preview-stage { min-height: 360px; } }
@media (prefers-reduced-motion: reduce) { .storyboard-state svg,.preview-empty.is-running svg { animation-duration: 1.8s; } }
</style>
