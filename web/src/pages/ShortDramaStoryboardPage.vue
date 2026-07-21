<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BookOpenText,
  Boxes,
  Check,
  Clapperboard,
  Clock3,
  Copy,
  Film,
  GripVertical,
  ImageIcon,
  LoaderCircle,
  MonitorPlay,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  UsersRound,
  Video,
} from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
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
const generatingStoryboard = ref(false)
const saving = ref(false)
const generatingVideo = ref(false)
const generationError = ref('')
const description = ref('')
const prompt = ref('')
const duration = ref(6)
const selectedAssetIds = ref<number[]>([])
let alive = true

const isAgent = computed(() => project.value?.creationMode === 'agent')
const selectedScene = computed(() => scenes.value.find(item => item.id === activeSceneId.value) ?? scenes.value[0])
const selectedVideo = computed(() => selectedScene.value ? videos.value[selectedScene.value.id]?.[0] : undefined)
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

function syncSceneForm(scene?: Scene) {
  description.value = scene?.description || ''
  prompt.value = scene?.prompt || ''
  duration.value = scene?.duration || 6
  selectedAssetIds.value = scene?.assets?.map(item => item.id) ?? scene?.asset_ids ?? []
}

async function fetchScenes(chapterId: number) {
  const briefScenes = (await api.scenes(chapterId)).data.items
  scenes.value = await Promise.all(briefScenes.map(async item => (await api.scene(item.id)).data))
  activeSceneId.value = scenes.value[0]?.id || 0
  syncSceneForm(scenes.value[0])
  const entries = await Promise.all(scenes.value.map(async scene => [scene.id, (await api.videos(scene.id)).data.items] as const))
  videos.value = Object.fromEntries(entries)
}

async function createManualScene() {
  if (!activeChapter.value) return
  const created = (await api.createScene({
    chapter_id: activeChapter.value.id,
    sequence: 1,
    description: activeChapter.value.name || '新分镜',
    prompt: '',
    duration: 6,
  })).data
  scenes.value = [created]
  activeSceneId.value = created.id
  videos.value[created.id] = []
  syncSceneForm(created)
}

async function generateChapterStoryboard(chapterId: number) {
  if (generatingStoryboard.value) return
  generatingStoryboard.value = true
  generationError.value = ''
  try {
    const task = (await api.generateScenes(chapterId)).data
    let current = task
    while (alive && !terminalTaskStatuses.has(current.status)) {
      await sleep(2200)
      current = (await api.task(task.id)).data
    }
    if (!alive) return
    if (current.status !== TaskStatusEnum.COMPLETED) throw new Error(current.error_message || 'Agent 分镜生成失败')
    await fetchScenes(chapterId)
    notice.success(`第 ${activeChapter.value?.number || ''} 集分镜已生成`)
  } catch (error) {
    generationError.value = (error as Error).message
    notice.error(generationError.value)
  } finally {
    generatingStoryboard.value = false
  }
}

async function regenerateStoryboard() {
  if (!activeChapterId.value || generatingStoryboard.value) return
  if (!confirm('重新生成会替换本集现有分镜，是否继续？')) return
  generatingStoryboard.value = true
  generationError.value = ''
  try {
    await Promise.all(scenes.value.map(scene => api.deleteScene(scene.id)))
    scenes.value = []
    activeSceneId.value = 0
    syncSceneForm()
  } catch (error) {
    generatingStoryboard.value = false
    notice.error((error as Error).message)
    return
  }
  generatingStoryboard.value = false
  await generateChapterStoryboard(activeChapterId.value)
}

async function loadChapter(chapterId: number) {
  activeChapterId.value = chapterId
  loading.value = true
  generationError.value = ''
  try {
    activeChapter.value = (await api.chapter(chapterId)).data
    await fetchScenes(chapterId)
    if (!scenes.value.length) {
      if (isAgent.value) await generateChapterStoryboard(chapterId)
      else await createManualScene()
    }
  } catch (error) {
    generationError.value = (error as Error).message
    notice.error(generationError.value)
  } finally {
    loading.value = false
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
    if (firstChapter) await loadChapter(firstChapter.id)
  } catch (error) {
    generationError.value = (error as Error).message
    notice.error(generationError.value)
  } finally {
    loading.value = false
  }
}

function selectScene(scene: Scene) {
  activeSceneId.value = scene.id
  syncSceneForm(scene)
}

function toggleAsset(assetId: number) {
  selectedAssetIds.value = selectedAssetIds.value.includes(assetId)
    ? selectedAssetIds.value.filter(id => id !== assetId)
    : [...selectedAssetIds.value, assetId]
}

async function saveScene(showNotice = true) {
  const scene = selectedScene.value
  if (!scene) return
  saving.value = true
  try {
    const updated = (await api.updateScene(scene.id, {
      description: description.value,
      prompt: prompt.value,
      duration: duration.value,
      asset_ids: selectedAssetIds.value,
    })).data
    scenes.value = scenes.value.map(item => item.id === updated.id ? updated : item)
    syncSceneForm(updated)
    if (showNotice) notice.success('分镜已保存')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
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
    selectScene(created)
    notice.success('已添加分镜')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function duplicateScene() {
  const scene = selectedScene.value
  if (!scene || !activeChapter.value) return
  try {
    const created = (await api.createScene({
      chapter_id: activeChapter.value.id,
      sequence: Math.max(0, ...scenes.value.map(item => item.sequence)) + 1,
      description: description.value,
      prompt: prompt.value,
      duration: duration.value,
      asset_ids: selectedAssetIds.value,
    })).data
    scenes.value.push(created)
    videos.value[created.id] = []
    selectScene(created)
    notice.success('分镜已复制')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function removeScene() {
  const scene = selectedScene.value
  if (!scene || !confirm(`删除分镜 ${scene.sequence}？`)) return
  try {
    await api.deleteScene(scene.id)
    scenes.value = scenes.value.filter(item => item.id !== scene.id)
    const next = scenes.value[0]
    activeSceneId.value = next?.id || 0
    syncSceneForm(next)
    notice.success('分镜已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function generateVideo() {
  const scene = selectedScene.value
  if (!scene) return
  generatingVideo.value = true
  try {
    await saveScene(false)
    let result = (await api.generateVideo(scene.id, Number(selectedVideoModel.value))).data
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
    generatingVideo.value = false
  }
}

function selectPhase(label: string) {
  if (label === '剧本' && isAgent.value) void router.push(`/create/short-drama/agent/${projectId.value}`)
  if (label === '设定') void router.push(`/create/short-drama/manual/${projectId.value}`)
}

onMounted(load)
onBeforeUnmount(() => { alive = false })
</script>

<template>
  <main class="storyboard-page">
    <header class="storyboard-topbar">
      <div class="project-heading">
        <AppButton variant="ghost" size="sm" icon-only aria-label="返回" @click="router.back()"><ArrowLeft :size="18" /></AppButton>
        <div><strong>{{ project?.name || '短剧项目' }}</strong><span><Film :size="13" />{{ project?.aspectRatio || '9:16' }}<i />{{ project?.resolution || '720p' }}<i />{{ project?.style || '写实通用' }}</span></div>
      </div>
      <nav class="phase-nav" aria-label="短剧制作流程">
        <template v-for="(phase, index) in phaseItems" :key="phase.label">
          <span v-if="index" />
          <AppButton variant="soft" size="sm" :active="phase.active" :aria-current="phase.active ? 'step' : undefined" @click="selectPhase(phase.label)"><component :is="phase.icon" :size="16" />{{ phase.label }}</AppButton>
        </template>
      </nav>
    </header>

    <div class="storyboard-shell">
      <aside class="episode-rail">
        <strong>集数</strong>
        <div>
          <AppButton v-for="chapter in chapters" :key="chapter.id" variant="soft" size="sm" icon-only :active="activeChapterId === chapter.id" :aria-label="`第 ${chapter.number} 集`" @click="loadChapter(chapter.id)">{{ chapter.number }}</AppButton>
        </div>
      </aside>

      <section class="storyboard-main">
        <header class="chapter-toolbar">
          <div><span :class="{ 'is-agent': isAgent }">{{ isAgent ? 'AGENT STORYBOARD' : 'MANUAL STORYBOARD' }}</span><h1>第 {{ activeChapter?.number || '-' }} 集 · {{ activeChapter?.name || '分镜制作' }}</h1><p>{{ activeChapter?.content?.slice(0, 120) }}</p></div>
          <div class="chapter-actions">
            <AppSelect v-model="selectedVideoModel" ariaLabel="视频模型" :options="videoModelOptions" :menu-width="220" align="end" />
            <AppButton v-if="isAgent" variant="secondary" size="sm" :loading="generatingStoryboard" @click="regenerateStoryboard"><Sparkles v-if="!generatingStoryboard" :size="15" />{{ generatingStoryboard ? 'Agent 生成中' : '重新生成分镜' }}</AppButton>
            <AppButton variant="primary" size="sm" @click="addScene"><Plus :size="15" />添加分镜</AppButton>
          </div>
        </header>

        <div v-if="loading || generatingStoryboard" class="storyboard-state"><LoaderCircle :size="28" /><strong>{{ generatingStoryboard ? 'Agent 正在拆解章节并生成多个分镜' : '正在读取分镜' }}</strong><p>{{ generatingStoryboard ? '生成完成后会自动展示全部镜头，请稍候。' : '正在准备章节、资产和视频信息。' }}</p></div>
        <div v-else-if="generationError && !scenes.length" class="storyboard-state is-error"><Clapperboard :size="28" /><strong>暂时无法生成分镜</strong><p>{{ generationError }}</p><AppButton variant="primary" size="sm" @click="isAgent ? generateChapterStoryboard(activeChapterId) : createManualScene()">重试</AppButton></div>
        <template v-else>
          <nav class="shot-strip" aria-label="本集分镜">
            <AppButton v-for="scene in scenes" :key="scene.id" variant="soft" size="sm" :active="activeSceneId === scene.id" @click="selectScene(scene)"><span>{{ String(scene.sequence).padStart(2, '0') }}</span>分镜 {{ scene.sequence }}</AppButton>
            <AppButton variant="ghost" size="sm" icon-only aria-label="添加分镜" @click="addScene"><Plus :size="16" /></AppButton>
          </nav>

          <article v-if="selectedScene" class="shot-editor">
            <header class="shot-editor-header">
              <div><GripVertical class="drag-mark" :size="16" /><strong>分镜 {{ selectedScene.sequence }}</strong><small>ID {{ selectedScene.id }}</small></div>
              <div><AppButton variant="ghost" size="sm" icon-only aria-label="复制分镜" @click="duplicateScene"><Copy :size="15" /></AppButton><AppButton variant="danger" size="sm" icon-only aria-label="删除分镜" @click="removeScene"><Trash2 :size="15" /></AppButton></div>
            </header>

            <div class="shot-editor-grid">
              <aside class="shot-info-panel">
                <h2>分镜信息</h2>
                <label><span>分镜描述</span><textarea v-model="description" rows="5" placeholder="请输入分镜描述" /></label>
                <section v-for="group in assetGroups" :key="group.type" class="shot-assets">
                  <header><span><component :is="group.icon" :size="15" />{{ group.label }}</span><small>{{ selectedAssetIds.filter(id => group.items.some(item => item.id === id)).length }}/{{ group.items.length }}</small></header>
                  <div v-if="group.items.length">
                    <AppButton v-for="asset in group.items" :key="asset.id" variant="ghost" size="sm" :active="selectedAssetIds.includes(asset.id)" :aria-pressed="selectedAssetIds.includes(asset.id)" @click="toggleAsset(asset.id)"><span class="asset-thumb"><img v-if="asset.main_image" :src="asset.main_image" :alt="asset.canonical_name" /><component v-else :is="group.icon" :size="15" /></span><span>{{ asset.canonical_name }}</span><Check v-if="selectedAssetIds.includes(asset.id)" :size="14" /></AppButton>
                  </div>
                  <p v-else>暂无可用{{ group.label.replace('分镜', '').replace('出镜', '') }}</p>
                </section>
              </aside>

              <section class="prompt-panel">
                <header><div><Sparkles :size="17" /><span><strong>分镜视频生成</strong><small>使用 @ 引用角色、场景与道具，保持视觉一致性</small></span></div><AppButton variant="secondary" size="sm" :loading="saving" @click="saveScene()"><Save v-if="!saving" :size="14" />保存</AppButton></header>
                <textarea v-model="prompt" placeholder="请输入分镜视频提示词。描述镜头、主体动作、运镜、光线、画面风格和声音。" />
                <footer>
                  <div><AppSelect v-model="selectedVideoModel" ariaLabel="视频模型" :options="videoModelOptions" :menu-width="220" /><span><Clock3 :size="14" /><input v-model.number="duration" type="number" min="1" max="30" />s</span><span>{{ project?.resolution || '720p' }}</span><span>1x</span></div>
                  <AppButton variant="primary" size="md" :disabled="!prompt.trim()" :loading="generatingVideo" @click="generateVideo"><Play v-if="!generatingVideo" :size="15" />{{ generatingVideo ? '生成中' : '生成视频' }}</AppButton>
                </footer>
              </section>

              <aside class="preview-panel">
                <header><strong>视频预览</strong><RefreshCw :size="15" /></header>
                <div class="preview-stage">
                  <video v-if="selectedVideo?.url" :src="selectedVideo.url" controls playsinline />
                  <div v-else-if="generatingVideo || (selectedVideo && !terminalTaskStatuses.has(selectedVideo.status))" class="preview-empty is-running"><LoaderCircle :size="30" /><strong>视频生成中</strong><span>完成后将在这里自动播放</span></div>
                  <div v-else class="preview-empty"><MonitorPlay :size="32" /><strong>等待生成视频</strong><span>完善提示词后点击“生成视频”</span></div>
                </div>
                <footer v-if="selectedVideo"><span :class="{ 'is-ready': selectedVideo.status === TaskStatusEnum.COMPLETED }">{{ selectedVideo.status === TaskStatusEnum.COMPLETED ? '已完成' : selectedVideo.status === TaskStatusEnum.FAILED ? '生成失败' : '生成中' }}</span><small>#{{ selectedVideo.id }}</small></footer>
              </aside>
            </div>
          </article>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.storyboard-page { min-width: 0; min-height: 100%; overflow-x: hidden; color: #303442; background: #f7f8fb; }
.storyboard-topbar { position: sticky; top: 0; z-index: 30; display: grid; min-height: 72px; grid-template-columns: minmax(280px,1fr) auto minmax(280px,1fr); align-items: center; padding: 7px 26px; background: rgb(255 255 255 / 96%); box-shadow: 0 8px 26px rgb(35 39 56 / 5%); backdrop-filter: blur(16px); }
.project-heading { display: flex; min-width: 0; align-items: center; gap: 12px; }
.project-heading > div { display: grid; min-width: 0; gap: 5px; }
.project-heading strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.project-heading span { display: flex; align-items: center; gap: 7px; color: #9298a8; font-size: 10px; }
.project-heading i { width: 1px; height: 10px; background: #dfe2e9; }
.phase-nav { grid-column: 2; display: flex; align-items: center; }
.phase-nav > span { width: 18px; height: 1px; background: #e2e4eb; }
.phase-nav button { display: flex; width: 68px; min-height: 54px; flex-direction: column; gap: 4px; border-radius: 16px; color: #858b9a; background: #fff; font-size: 10px; }
.phase-nav button.is-active { color: #5b5cf6; background: #f0f0ff; box-shadow: 0 8px 22px rgb(91 92 246 / 11%); }
.storyboard-shell { display: grid; min-height: calc(100vh - 72px); grid-template-columns: 68px minmax(0,1fr); }
.episode-rail { display: grid; align-content: start; justify-items: center; gap: 14px; padding: 24px 8px; background: #fff; box-shadow: 7px 0 24px rgb(43 47 65 / 4%); }
.episode-rail > strong { color: #777d8d; font-size: 11px; }
.episode-rail > div { display: grid; max-height: calc(100vh - 140px); gap: 9px; overflow-y: auto; padding: 2px 4px 12px; scrollbar-width: thin; }
.episode-rail button { width: 38px; min-height: 38px; }
.storyboard-main { min-width: 0; padding: 24px 26px 48px; }
.chapter-toolbar { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.chapter-toolbar > div:first-child { min-width: 0; }
.chapter-toolbar > div:first-child > span { color: #8c91a0; font-size: 8px; font-weight: 750; letter-spacing: .15em; }
.chapter-toolbar > div:first-child > span.is-agent { color: #6163ef; }
.chapter-toolbar h1 { margin: 5px 0 6px; font-size: 19px; }
.chapter-toolbar p { max-width: 760px; margin: 0; overflow: hidden; color: #898f9e; font-size: 10px; line-height: 1.6; text-overflow: ellipsis; white-space: nowrap; }
.chapter-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }
.storyboard-state { display: grid; min-height: calc(100vh - 210px); place-items: center; align-content: center; gap: 8px; color: #686ef1; text-align: center; }
.storyboard-state svg { animation: spin 1s linear infinite; }
.storyboard-state strong { color: #454a59; font-size: 14px; }
.storyboard-state p { max-width: 460px; margin: 0; color: #9297a6; font-size: 11px; }
.storyboard-state.is-error svg { color: #bf6470; animation: none; }
.storyboard-state button { margin-top: 8px; }
.shot-strip { display: flex; min-width: 0; gap: 7px; margin-bottom: 11px; overflow-x: auto; padding: 2px 2px 7px; scrollbar-width: thin; }
.shot-strip button { flex: 0 0 auto; }
.shot-strip button > span { display: grid; width: 20px; height: 20px; place-items: center; border-radius: 6px; color: #7678e9; background: #fff; font-size: 8px; }
.shot-strip button.is-active > span { color: #fff; background: #6668ef; }
.shot-editor { overflow: hidden; border-radius: 18px; background: #fff; box-shadow: 0 16px 46px rgb(39 43 61 / 7%); }
.shot-editor-header { display: flex; min-height: 48px; align-items: center; justify-content: space-between; padding: 0 14px; background: #fbfbfd; }
.shot-editor-header > div { display: flex; align-items: center; gap: 8px; }
.shot-editor-header strong { font-size: 12px; }
.shot-editor-header small { padding: 3px 5px; border-radius: 5px; color: #7476df; background: #efefff; font-size: 8px; }
.drag-mark { color: #9ba0ae; font-size: 17px; }
.shot-editor-grid { display: grid; min-height: 660px; grid-template-columns: 300px minmax(400px,1fr) minmax(300px,34%); gap: 12px; padding: 12px; background: #f7f8fb; }
.shot-info-panel,.prompt-panel,.preview-panel { min-width: 0; border-radius: 14px; background: #fff; box-shadow: 0 5px 20px rgb(45 49 68 / 4%); }
.shot-info-panel { display: grid; align-content: start; gap: 17px; padding: 17px; overflow-y: auto; }
.shot-info-panel h2,.prompt-panel strong,.preview-panel strong { margin: 0; font-size: 13px; }
.shot-info-panel label { display: grid; gap: 7px; color: #686e7d; font-size: 10px; }
.shot-info-panel textarea,.prompt-panel textarea { width: 100%; border: 0; outline: 0; color: #3e4351; background: #f7f8fb; font: inherit; resize: none; }
.shot-info-panel textarea { padding: 11px; border-radius: 10px; font-size: 11px; line-height: 1.6; }
.shot-info-panel textarea:focus,.prompt-panel textarea:focus { box-shadow: inset 0 0 0 2px rgb(91 92 246 / 14%); }
.shot-assets { display: grid; gap: 8px; }
.shot-assets > header { display: flex; align-items: center; justify-content: space-between; color: #525867; font-size: 10px; font-weight: 650; }
.shot-assets > header > span { display: inline-flex; align-items: center; gap: 6px; }
.shot-assets > header small { color: #9a9fac; font-weight: 400; }
.shot-assets > div { display: grid; gap: 5px; }
.shot-assets button { width: 100%; justify-content: flex-start; padding: 5px 7px; color: #666c7b; background: #f7f8fb; }
.shot-assets button > span:nth-child(2) { flex: 1; overflow: hidden; text-align: left; text-overflow: ellipsis; }
.shot-assets button.is-active { color: #5658e8; background: #eeeefe; }
.asset-thumb { display: grid; width: 28px; height: 28px; flex: 0 0 28px; overflow: hidden; place-items: center; border-radius: 7px; color: #959baa; background: #e9ebf1; }
.asset-thumb img { width: 100%; height: 100%; object-fit: cover; }
.shot-assets > p { display: grid; min-height: 52px; margin: 0; place-items: center; border-radius: 9px; color: #a1a6b3; background: #f7f8fb; font-size: 9px; }
.prompt-panel { display: grid; grid-template-rows: auto minmax(0,1fr) auto; }
.prompt-panel > header { display: flex; min-height: 62px; align-items: center; justify-content: space-between; padding: 0 16px; }
.prompt-panel > header > div { display: flex; min-width: 0; align-items: center; gap: 10px; color: #6264ec; }
.prompt-panel > header span { display: grid; min-width: 0; gap: 3px; }
.prompt-panel > header small { color: #9a9fac; font-size: 9px; font-weight: 400; }
.prompt-panel > textarea { min-height: 420px; padding: 18px; background: #fff; font-size: 12px; line-height: 1.85; white-space: pre-wrap; }
.prompt-panel > footer { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px; background: #fbfbfd; }
.prompt-panel > footer > div { display: flex; min-width: 0; align-items: center; gap: 6px; }
.prompt-panel > footer > div > span { display: inline-flex; min-height: 34px; align-items: center; gap: 4px; padding: 0 10px; border-radius: 9px; color: #777d8d; background: #fff; box-shadow: 0 1px 3px rgb(35 39 55 / 8%); font-size: 10px; }
.prompt-panel input { width: 23px; padding: 0; border: 0; outline: 0; color: #555b6a; background: transparent; font: inherit; text-align: right; }
.preview-panel { display: grid; grid-template-rows: 48px minmax(0,1fr) auto; overflow: hidden; }
.preview-panel > header { display: flex; align-items: center; justify-content: space-between; padding: 0 15px; }
.preview-panel > header svg { color: #9197a6; }
.preview-stage { display: grid; min-height: 520px; overflow: hidden; place-items: center; background: #252a35; }
.preview-stage video { width: 100%; height: 100%; object-fit: contain; }
.preview-empty { display: grid; place-items: center; gap: 8px; color: #7f8798; text-align: center; }
.preview-empty svg { color: #8e96a8; }
.preview-empty strong { color: #c8ccd4; font-size: 12px; }
.preview-empty span { font-size: 9px; }
.preview-empty.is-running svg { color: #8587ff; animation: spin 1s linear infinite; }
.preview-panel > footer { display: flex; min-height: 44px; align-items: center; justify-content: space-between; padding: 0 14px; }
.preview-panel > footer span { color: #8a90a0; font-size: 9px; }
.preview-panel > footer span.is-ready { color: #32916c; }
.preview-panel > footer small { color: #a0a5b1; font-size: 9px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) { .shot-editor-grid { grid-template-columns: 260px minmax(380px,1fr); }.preview-panel { grid-column: 1 / -1; }.preview-stage { min-height: 420px; max-height: 560px; } }
@media (max-width: 820px) { .storyboard-topbar { grid-template-columns: 1fr; gap: 8px; padding: 10px 14px; }.phase-nav { grid-column: 1; justify-content: center; }.storyboard-shell { grid-template-columns: 1fr; }.episode-rail { display: flex; align-items: center; justify-items: initial; padding: 9px 14px; overflow: hidden; }.episode-rail > div { display: flex; max-height: none; overflow-x: auto; padding: 0; }.storyboard-main { padding: 18px 14px 36px; }.chapter-toolbar { flex-direction: column; }.chapter-actions { width: 100%; overflow-x: auto; padding-bottom: 4px; }.shot-editor-grid { grid-template-columns: 1fr; }.preview-panel { grid-column: 1; }.shot-info-panel { max-height: none; }.prompt-panel > footer { align-items: stretch; flex-direction: column; }.prompt-panel > footer > div { overflow-x: auto; }.prompt-panel > footer > button { width: 100%; } }
@media (max-width: 520px) { .phase-nav button { width: 54px; }.phase-nav > span { width: 7px; }.chapter-toolbar p { white-space: normal; }.shot-editor-grid { padding: 7px; }.prompt-panel > textarea { min-height: 320px; }.preview-stage { min-height: 360px; } }
@media (prefers-reduced-motion: reduce) { .storyboard-state svg,.preview-empty.is-running svg { animation-duration: 1.8s; } }
</style>
