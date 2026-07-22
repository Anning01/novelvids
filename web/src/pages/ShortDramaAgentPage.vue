<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  BookOpenText,
  Bot,
  Check,
  ChevronDown,
  Clapperboard,
  FileText,
  Film,
  Image,
  MonitorPlay,
  RefreshCw,
  Settings2,
  Sparkles,
  UsersRound,
  Video,
} from 'lucide-vue-next'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { TaskStatusEnum } from '@/types'
import type { AiModelConfig, AiTask, Chapter } from '@/types'

interface AgentProjectMeta {
  projectId?: number
  name: string
  aspectRatio: string
  resolution: string
  style: string
  fileName: string
  sourcePath?: string
  cover?: string
  analysisTaskId?: string
}

interface KeyCharacter {
  name: string
  aliases: string[]
  role: string
  description: string
  base_traits: string
  chapter_numbers: number[]
}

interface ProjectAnalysisResult {
  book_types: string[]
  story_outline: string
  key_characters: KeyCharacter[]
  chapter_count: number
  cover: string
}

const fallbackProject: AgentProjectMeta = {
  name: '短剧项目',
  aspectRatio: '9:16',
  resolution: '720p',
  style: '写实通用',
  fileName: '',
}

function readProjectMeta(): AgentProjectMeta {
  try {
    const stored = sessionStorage.getItem('short-drama-agent-project')
    return stored ? { ...fallbackProject, ...JSON.parse(stored) } : fallbackProject
  } catch {
    return fallbackProject
  }
}

const project = ref(readProjectMeta())
const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const configs = ref<AiModelConfig[]>([])
const activeEpisode = ref(1)
const showingAllCharacters = ref(false)
const analysisTask = ref<AiTask | null>(null)
const chapters = ref<Chapter[]>([])
const chapterDetails = ref<Record<number, Chapter>>({})
const loadingChapterId = ref<number | null>(null)
const startingAnalysis = ref(false)
const episodeTabs = ref<HTMLElement | null>(null)
let pollTimer: number | undefined

const phases = [
  { label: '剧本', icon: BookOpenText, active: true },
  { label: '设定', icon: Settings2 },
  { label: '分镜', icon: Clapperboard },
  { label: '视频', icon: Video },
]

const analysisResult = computed<ProjectAnalysisResult | null>(() => {
  if (analysisTask.value?.status !== TaskStatusEnum.COMPLETED || !analysisTask.value.response_data) return null
  return analysisTask.value.response_data as unknown as ProjectAnalysisResult
})
const characters = computed(() => analysisResult.value?.key_characters ?? [])
const visibleCharacters = computed(() => showingAllCharacters.value ? characters.value : characters.value.slice(0, 4))
const selectedEpisodeBrief = computed(() => chapters.value.find(item => item.number === activeEpisode.value) ?? chapters.value[0])
const selectedEpisode = computed(() => {
  const chapter = selectedEpisodeBrief.value
  return chapter ? (chapterDetails.value[chapter.id] ?? chapter) : undefined
})
const selectedEpisodeLoading = computed(() => {
  const chapter = selectedEpisodeBrief.value
  return Boolean(chapter && loadingChapterId.value === chapter.id && !chapterDetails.value[chapter.id])
})
const selectedEpisodeCharacters = computed(() => {
  const chapterNumber = selectedEpisode.value?.number
  if (!chapterNumber) return '暂无关键人物标记'
  return characters.value
    .filter(character => character.chapter_numbers.includes(chapterNumber))
    .map(character => character.name)
    .join('、') || '暂无关键人物标记'
})
const analysisRunning = computed(() => {
  const status = analysisTask.value?.status
  return status === TaskStatusEnum.PENDING || status === TaskStatusEnum.PROCESSING || status === TaskStatusEnum.QUEUED
})
const analysisStatus = computed(() => {
  if (startingAnalysis.value || analysisRunning.value) return 'AI 正在理解书稿并生成封面'
  if (analysisTask.value?.status === TaskStatusEnum.FAILED) return '分析失败'
  if (analysisResult.value) return '剧本分析完成'
  return '准备分析'
})
const characterColors = ['#6a6cf4', '#df9854', '#4c9d89', '#ad6d9e', '#df7790', '#8d73db']
const activeModels = computed(() => ({
  llm: configs.value.find(item => item.is_active && (item.task_types?.length ? item.task_types : [item.task_type]).some(value => [1, 3].includes(value))),
  image: configs.value.find(item => item.is_active && (item.task_types?.length ? item.task_types : [item.task_type]).includes(2)),
  video: configs.value.find(item => item.is_active && (item.task_types?.length ? item.task_types : [item.task_type]).includes(4)),
}))

async function loadModels() {
  try {
    configs.value = (await api.configs()).data.items
  } catch {
    // The analysis page remains usable when the local API is unavailable.
  }
}

async function loadProject(): Promise<boolean> {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return false
  try {
    const response = await api.novel(projectId.value)
    const contentLength = (response.data.content || '').trim().length
    if (contentLength >= 30_000 && (response.data.total_chapters || 0) <= 1) {
      notice.error(`书稿约 ${contentLength.toLocaleString()} 字但只拆分出 ${response.data.total_chapters || 0} 章，已阻止进入。请重新上传并检查文件编码或章节标题。`)
      await router.replace('/create/short-drama')
      return false
    }
    const settings = readShortDramaSettings(response.data)
    project.value = {
      ...project.value,
      projectId: response.data.id,
      name: response.data.name,
      aspectRatio: settings.aspectRatio || project.value.aspectRatio,
      resolution: settings.resolution || project.value.resolution,
      style: settings.style || project.value.style,
      fileName: settings.sourceFile || project.value.fileName,
      cover: response.data.cover,
    }
    return true
  } catch (error) {
    notice.error((error as Error).message)
    return false
  }
}

async function loadChapters() {
  try {
    chapters.value = (await api.chapters(projectId.value)).data.items
    const requestedChapterId = Number(route.query.chapter)
    const requestedChapter = chapters.value.find(item => item.id === requestedChapterId)
    if (requestedChapter) {
      activeEpisode.value = requestedChapter.number
    } else if (chapters.value.length && !chapters.value.some(item => item.number === activeEpisode.value)) {
      activeEpisode.value = chapters.value[0].number
    }
    await loadChapterContent(selectedEpisodeBrief.value)
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function loadChapterContent(chapter?: Chapter) {
  if (!chapter || chapterDetails.value[chapter.id]) return
  loadingChapterId.value = chapter.id
  try {
    const detail = (await api.chapter(chapter.id)).data
    chapterDetails.value = { ...chapterDetails.value, [chapter.id]: detail }
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    if (loadingChapterId.value === chapter.id) loadingChapterId.value = null
  }
}

function stopPolling() {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

async function pollAnalysis(taskId: string) {
  stopPolling()
  try {
    const response = await api.task(taskId)
    analysisTask.value = response.data
    if (analysisRunning.value) {
      pollTimer = window.setTimeout(() => pollAnalysis(taskId), 1800)
    } else if (response.data.status === TaskStatusEnum.COMPLETED) {
      await Promise.all([loadProject(), loadChapters()])
    }
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function startAnalysis() {
  if (startingAnalysis.value || analysisRunning.value) return
  startingAnalysis.value = true
  try {
    const response = await api.analyzeNovel(projectId.value)
    analysisTask.value = response.data
    notice.success('AI 已开始提取类型、大纲和关键人物，并生成 1K 封面')
    await pollAnalysis(response.data.id)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    startingAnalysis.value = false
  }
}

async function loadAnalysis() {
  try {
    const response = await api.novelAnalysis(projectId.value)
    analysisTask.value = response.data
    if (!response.data) {
      await startAnalysis()
    } else if (analysisRunning.value) {
      await pollAnalysis(response.data.id)
    } else if (response.data.status === TaskStatusEnum.COMPLETED) {
      await loadChapters()
    }
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function regenerateAnalysis() {
  analysisTask.value = null
  await startAnalysis()
}

function continueToSettings() {
  notice.success('剧本分析已确认，正在进入角色与场景设定')
  void router.push({
    path: `/create/short-drama/manual/${projectId.value}`,
    query: selectedEpisodeBrief.value ? { chapter: String(selectedEpisodeBrief.value.id) } : undefined,
  })
}

async function selectEpisode(chapterNumber: number, event?: MouseEvent) {
  activeEpisode.value = chapterNumber
  const chapter = chapters.value.find(item => item.number === chapterNumber)
  if (chapter) void router.replace({ query: { ...route.query, chapter: String(chapter.id) } })
  void loadChapterContent(chapter)
  await nextTick()
  const button = event?.currentTarget as HTMLElement | null
  if (!button || !episodeTabs.value) return
  const left = button.offsetLeft - (episodeTabs.value.clientWidth - button.offsetWidth) / 2
  episodeTabs.value.scrollTo({ left: Math.max(0, left), behavior: 'smooth' })
}

onMounted(async () => {
  const [, projectReady] = await Promise.all([loadModels(), loadProject()])
  if (projectReady) await loadAnalysis()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <main class="agent-page">
    <header class="agent-topbar">
      <div class="agent-project-nav">
        <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="返回上一页" @click="router.back()"><ArrowLeft :size="18" /></AppButton>
        <div>
          <strong>{{ project.name }}</strong>
          <span><Film :size="13" />{{ project.aspectRatio }}<i />{{ project.resolution }}<i />{{ project.style }}</span>
        </div>
      </div>

      <nav class="agent-phases" aria-label="短剧制作流程">
        <template v-for="(phase, index) in phases" :key="phase.label">
          <span v-if="index" class="phase-line" />
          <AppButton type="button" variant="soft" size="sm" :active="phase.active" :aria-current="phase.active ? 'step' : undefined">
            <component :is="phase.icon" :size="16" />
            {{ phase.label }}
          </AppButton>
        </template>
      </nav>
    </header>

    <section class="agent-content">
      <div class="analysis-hero">
        <div class="project-cover-art" aria-label="项目封面">
          <img v-if="project.cover || analysisResult?.cover" :src="project.cover || analysisResult?.cover" :alt="`${project.name}封面`" />
          <template v-else>
          <span class="cover-orbit orbit-one" />
          <span class="cover-orbit orbit-two" />
          <Sparkles :size="34" />
          <small>AI DRAMA</small>
          </template>
        </div>
        <div class="analysis-hero-copy">
          <span class="analysis-ready" :class="{ 'is-processing': analysisRunning || startingAnalysis, 'is-failed': analysisTask?.status === TaskStatusEnum.FAILED }">
            <RefreshCw v-if="analysisRunning || startingAnalysis" class="status-spinner" :size="13" />
            <Check v-else-if="analysisResult" :size="13" />
            <FileText v-else :size="13" />
            {{ analysisStatus }}
          </span>
          <h1>{{ project.name }}</h1>
          <p><FileText :size="14" />{{ analysisResult?.chapter_count || chapters.length || 0 }} 章 <i /> <Film :size="14" />{{ project.aspectRatio }} <i /> <MonitorPlay :size="14" />{{ project.resolution }}</p>
          <div v-if="analysisResult?.book_types.length" class="genre-tags"><span v-for="genre in analysisResult.book_types" :key="genre">{{ genre }}</span></div>
        </div>
        <AppButton class="secondary-action" variant="secondary" size="sm" type="button" :disabled="analysisRunning || startingAnalysis" @click="regenerateAnalysis"><RefreshCw :size="15" />重新分析</AppButton>
      </div>

      <section v-if="!analysisResult" class="analysis-progress-card" :class="{ 'is-failed': analysisTask?.status === TaskStatusEnum.FAILED }">
        <span><RefreshCw v-if="analysisRunning || startingAnalysis" class="status-spinner" :size="25" /><FileText v-else :size="25" /></span>
        <div>
          <h2>{{ analysisStatus }}</h2>
          <p v-if="analysisRunning || startingAnalysis">正在分割章节、提取书籍类型与故事大纲、识别关键人物，随后生成 1K 封面。请稍候，这通常需要几分钟。</p>
          <p v-else-if="analysisTask?.status === TaskStatusEnum.FAILED">{{ analysisTask.error_message || '模型调用失败，请检查模型配置后重试。' }}</p>
          <p v-else>开始分析后，结果会自动保存在当前项目中。</p>
        </div>
        <AppButton v-if="!analysisRunning && !startingAnalysis" variant="primary" size="sm" type="button" @click="startAnalysis">开始分析</AppButton>
      </section>

      <template v-if="analysisResult">
      <section class="analysis-section">
        <header><div><span class="section-kicker">PRODUCTION PROFILE</span><h2>项目设定</h2></div></header>
        <div class="profile-grid">
          <article class="profile-card"><span><Bot :size="18" /></span><div><small>剧本类型</small><strong>AI 精品短剧</strong><p>自动理解完整剧本，规划分集节奏、人物关系与视觉生产流程。</p></div></article>
          <article class="profile-card"><span><Clapperboard :size="18" /></span><div><small>分镜策略</small><strong>电影化叙事 1.5</strong><p>强调连续动作、景别变化与情绪转折，适配竖屏短剧节奏。</p></div></article>
        </div>
      </section>

      <section class="analysis-section">
        <header><div><span class="section-kicker">MODEL READINESS</span><h2>模型能力</h2></div><RouterLink to="/settings">管理模型<ArrowRight :size="14" /></RouterLink></header>
        <div class="model-readiness-grid">
          <article><span class="model-kind is-llm"><Bot :size="17" /></span><div><small>LLM 大模型</small><strong>{{ activeModels.llm?.model || '待配置' }}</strong></div><i :class="{ 'is-ready': activeModels.llm }" /></article>
          <article><span class="model-kind is-image"><Image :size="17" /></span><div><small>生图模型</small><strong>{{ activeModels.image?.model || '待配置' }}</strong></div><i :class="{ 'is-ready': activeModels.image }" /></article>
          <article><span class="model-kind is-video"><Video :size="17" /></span><div><small>视频模型</small><strong>{{ activeModels.video?.model || '待配置' }}</strong></div><i :class="{ 'is-ready': activeModels.video }" /></article>
        </div>
      </section>

      <section class="analysis-section">
        <header><div><span class="section-kicker">STORY OVERVIEW</span><h2>故事大纲</h2></div></header>
        <article class="outline-card">
          <span><BookOpenText :size="20" /></span>
          <p>{{ analysisResult.story_outline }}</p>
        </article>
      </section>

      <section class="analysis-section">
        <header><div><span class="section-kicker">CHARACTER BIBLE</span><h2>人物小传</h2></div><span>{{ characters.length }} 位主要人物</span></header>
        <div class="character-grid">
          <article v-for="(character, index) in visibleCharacters" :key="character.name" class="character-card">
            <div class="character-title"><span :style="{ '--character-accent': characterColors[index % characterColors.length] }">{{ character.name.slice(0, 1) }}</span><div><h3>{{ character.name }}</h3><small>{{ character.role }}</small></div></div>
            <p>{{ character.description }}</p>
            <div class="episode-appearances"><small>出场章节</small><span v-for="chapterNumber in character.chapter_numbers" :key="chapterNumber">第 {{ chapterNumber }} 章</span></div>
          </article>
        </div>
        <AppButton v-if="characters.length > 4" class="show-more" variant="ghost" size="sm" block type="button" @click="showingAllCharacters = !showingAllCharacters">
          {{ showingAllCharacters ? '收起人物' : '查看全部人物' }}<ChevronDown :class="{ 'is-up': showingAllCharacters }" :size="15" />
        </AppButton>
      </section>

      <section class="analysis-section episode-section">
        <header>
          <div><span class="section-kicker">EPISODE CHAPTERS</span><h2>分集剧情</h2><p>复用项目的分章节结构，每一集对应一个章节。</p></div>
          <span>{{ chapters.length }} 章</span>
        </header>
        <div ref="episodeTabs" class="episode-tabs" role="tablist" aria-label="分集剧情" tabindex="0">
          <AppButton v-for="chapter in chapters" :key="chapter.id" variant="soft" size="sm" icon-only type="button" role="tab" :active="activeEpisode === chapter.number" :aria-selected="activeEpisode === chapter.number" @click="selectEpisode(chapter.number, $event)">{{ chapter.number }}</AppButton>
        </div>
        <article v-if="selectedEpisode" class="episode-content">
          <header><span>{{ String(selectedEpisode.number).padStart(2, '0') }}</span><div><small>EPISODE {{ selectedEpisode.number }}</small><h3>第 {{ selectedEpisode.number }} 集 · {{ selectedEpisode.name }}</h3></div></header>
          <p v-if="selectedEpisodeLoading" class="episode-content-state">正在加载章节正文…</p>
          <p v-else-if="selectedEpisode.content">{{ selectedEpisode.content }}</p>
          <p v-else class="episode-content-state">该章节暂无正文内容</p>
          <footer><span><UsersRound :size="14" />{{ selectedEpisodeCharacters }}</span><span>第 {{ selectedEpisode.number }} 章</span></footer>
        </article>
      </section>

      <AppButton class="continue-button" variant="primary" size="lg" block type="button" @click="continueToSettings"><span><Sparkles :size="18" />确认分析，进入设定</span><ArrowRight :size="18" /></AppButton>
      </template>
    </section>
  </main>
</template>

<style scoped>
.agent-page { min-width: 0; min-height: 100%; overflow-x: clip; color: #303442; background: #f9fafc; }
.agent-topbar { position: sticky; top: 0; z-index: 30; display: grid; min-height: 74px; grid-template-columns: minmax(260px, 1fr) auto minmax(260px, 1fr); align-items: center; padding: 0 26px; background: rgb(255 255 255 / 94%); box-shadow: 0 8px 28px rgb(36 40 60 / 4%); backdrop-filter: blur(16px); }
.agent-project-nav { display: flex; min-width: 0; align-items: center; gap: 12px; }
.agent-project-nav > button { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border-radius: 9px; color: #686e7f; background: transparent; }
.agent-project-nav > button:hover { color: #4f51e8; background: #f0f0ff; }
.agent-project-nav > div { display: grid; min-width: 0; gap: 5px; }
.agent-project-nav strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.agent-project-nav span, .analysis-hero-copy p { display: flex; align-items: center; gap: 7px; color: #9297a6; font-size: 10px; }
.agent-project-nav i, .analysis-hero-copy i { width: 1px; height: 10px; background: #dfe1e8; }
.agent-phases { display: flex; align-items: center; }
.agent-phases button { display: grid; width: 64px; min-height: 54px; place-items: center; align-content: center; gap: 4px; border: 1px solid transparent; border-radius: 15px; color: #858a99; background: transparent; font-size: 10px; }
.agent-phases button.is-active { border-color: transparent; color: #5b5cf6; background: #f2f2ff; box-shadow: 0 7px 20px rgb(91 92 246 / 10%); }
.phase-line { width: 14px; height: 1px; background: transparent; }
.agent-content { width: min(1440px, 100%); min-width: 0; margin: 0 auto; padding: 36px 22px 80px; box-sizing: border-box; }
.analysis-hero { display: grid; grid-template-columns: 142px minmax(0, 1fr) auto; align-items: center; gap: 26px; padding: 24px; border-radius: 20px; background: #fff; box-shadow: 0 18px 52px rgb(42 46 64 / 8%); }
.project-cover-art { position: relative; display: grid; height: 180px; overflow: hidden; place-items: center; align-content: center; gap: 9px; border-radius: 13px; color: #fff; background: linear-gradient(145deg, #6f70f4, #4c3e91 58%, #201d45); box-shadow: 0 12px 25px rgb(48 42 105 / 22%); }
.project-cover-art > img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.project-cover-art svg, .project-cover-art small { position: relative; z-index: 2; }
.project-cover-art small { font-size: 8px; font-weight: 750; letter-spacing: .22em; }
.cover-orbit { position: absolute; border: 1px solid rgb(255 255 255 / 18%); border-radius: 50%; }
.orbit-one { width: 170px; height: 170px; transform: translate(45px, -45px); }
.orbit-two { width: 100px; height: 100px; transform: translate(-52px, 62px); }
.analysis-hero-copy { display: grid; justify-items: start; }
.analysis-ready { display: inline-flex; align-items: center; gap: 5px; margin-bottom: 9px; padding: 5px 8px; border-radius: 999px; color: #278363; background: #eaf7f1; font-size: 10px; font-weight: 600; }
.analysis-ready.is-processing { color: #5b5cf6; background: #f0f0ff; }
.analysis-ready.is-failed { color: #bb5b68; background: #fff0f2; }
.status-spinner { animation: status-spin 1.1s linear infinite; }
@keyframes status-spin { to { transform: rotate(360deg); } }
.analysis-hero h1 { margin: 0 0 10px; color: #282c3a; font-size: clamp(22px, 3vw, 30px); letter-spacing: -.035em; }
.analysis-hero-copy p { margin: 0; font-size: 11px; }
.genre-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }
.genre-tags span { padding: 5px 9px; border-radius: 7px; color: #6568dc; background: #f0f0ff; font-size: 10px; }
.genre-tags span:nth-child(2n) { color: #6b8568; background: #eef6ed; }
.secondary-action { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 0; border-radius: 9px; color: #626879; background: #f3f4f8; cursor: pointer; font-size: 11px; }
.secondary-action:hover { color: #4f51e8; background: #ededff; }
.secondary-action:disabled { opacity: .55; cursor: wait; }
.secondary-action.compact { min-height: 34px; }
.analysis-progress-card { display: grid; grid-template-columns: 52px minmax(0, 1fr) auto; align-items: center; gap: 16px; margin-top: 22px; padding: 20px; border-radius: 16px; background: #fff; box-shadow: 0 10px 34px rgb(45 49 68 / 6%); }
.analysis-progress-card > span { display: grid; width: 52px; height: 52px; place-items: center; border-radius: 14px; color: #5b5cf6; background: #f0f0ff; }
.analysis-progress-card h2 { margin: 0 0 6px; font-size: 15px; }
.analysis-progress-card p { margin: 0; color: #858a99; font-size: 11px; line-height: 1.7; }
.analysis-progress-card > button { min-height: 36px; padding: 0 15px; border: 0; border-radius: 9px; color: #fff; background: #5b5cf6; cursor: pointer; font-size: 11px; font-weight: 650; }
.analysis-progress-card.is-failed > span { color: #bb5b68; background: #fff0f2; }
.analysis-section { padding-top: 38px; }
.analysis-section > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 14px; }
.analysis-section > header > div { display: grid; gap: 4px; }
.analysis-section > header h2 { margin: 0; color: #303442; font-size: 17px; }
.analysis-section > header p { margin: 2px 0 0; color: #9297a7; font-size: 11px; }
.analysis-section > header > span { color: #999eac; font-size: 10px; }
.analysis-section > header > a { display: inline-flex; align-items: center; gap: 5px; color: #5b5cf6; font-size: 11px; }
.section-kicker { color: #7779ef; font-size: 8px; font-weight: 750; letter-spacing: .16em; }
.profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.profile-card { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 13px; padding: 16px; border-radius: 14px; background: #fff; box-shadow: 0 7px 24px rgb(45 49 68 / 5%); }
.profile-card > span { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 11px; color: #5b5cf6; background: #eff0ff; }
.profile-card > div { display: grid; gap: 4px; }
.profile-card small, .model-readiness-grid small { color: #969baa; font-size: 9px; }
.profile-card strong { font-size: 13px; }
.profile-card p { margin: 1px 0 0; color: #858a99; font-size: 10px; line-height: 1.55; }
.model-readiness-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.model-readiness-grid article { position: relative; display: grid; min-width: 0; grid-template-columns: 38px minmax(0, 1fr); align-items: center; gap: 11px; padding: 12px; border-radius: 13px; background: #fff; box-shadow: 0 7px 24px rgb(45 49 68 / 5%); }
.model-kind { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 10px; }
.model-kind.is-llm { color: #5e60ed; background: #eff0ff; }
.model-kind.is-image { color: #a16588; background: #f9edf4; }
.model-kind.is-video { color: #397f85; background: #eaf5f5; }
.model-readiness-grid article > div { display: grid; min-width: 0; gap: 3px; }
.model-readiness-grid strong { overflow: hidden; font-size: 10px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.model-readiness-grid article > i { position: absolute; top: 10px; right: 10px; width: 7px; height: 7px; border-radius: 50%; background: #d4d7df; }
.model-readiness-grid article > i.is-ready { background: #46af83; box-shadow: 0 0 0 3px #e6f5ef; }
.outline-card { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 14px; padding: 20px; border-radius: 14px; background: #fff; box-shadow: 0 7px 24px rgb(45 49 68 / 5%); }
.outline-card > span { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 11px; color: #5b5cf6; background: #eff0ff; }
.outline-card p { margin: 0; color: #5e6474; font-size: 12px; line-height: 1.9; }
.character-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.character-card { display: grid; gap: 12px; padding: 17px; border-radius: 14px; background: #fff; box-shadow: 0 7px 24px rgb(45 49 68 / 5%); }
.character-title { display: flex; align-items: center; gap: 11px; }
.character-title > span { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 50%; color: var(--character-accent); background: color-mix(in srgb, var(--character-accent) 12%, white); font-size: 13px; font-weight: 700; }
.character-title h3 { margin: 0 0 3px; font-size: 13px; }
.character-title small, .episode-appearances small { color: #979cab; font-size: 9px; }
.character-card > p { margin: 0; color: #707687; font-size: 11px; line-height: 1.7; }
.episode-appearances { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; padding-top: 4px; }
.episode-appearances small { margin-right: 3px; }
.episode-appearances span { padding: 4px 6px; border-radius: 5px; color: #7378a1; background: #f5f5f9; font-size: 8px; }
.show-more { display: flex; width: 100%; min-height: 35px; align-items: center; justify-content: center; gap: 6px; margin-top: 10px; border: 0; border-radius: 9px; color: #777c8c; background: transparent; cursor: pointer; font-size: 10px; }
.show-more:hover { background: #f1f2f6; }
.show-more svg { transition: transform .15s ease; }
.show-more svg.is-up { transform: rotate(180deg); }
.episode-section { min-width: 0; }
.episode-tabs { display: flex; width: 100%; max-width: 100%; gap: 7px; margin-bottom: 10px; padding: 2px 2px 8px; overflow-x: auto; overflow-y: hidden; overscroll-behavior-x: contain; scroll-behavior: smooth; scroll-snap-type: x proximity; scrollbar-color: #d9dbe6 transparent; scrollbar-width: thin; }
.episode-tabs::-webkit-scrollbar { height: 5px; }
.episode-tabs::-webkit-scrollbar-track { background: transparent; }
.episode-tabs::-webkit-scrollbar-thumb { border-radius: 999px; background: #d9dbe6; }
.episode-tabs:focus-visible { outline: 3px solid rgb(91 92 246 / 14%); outline-offset: 2px; border-radius: 10px; }
.episode-tabs button { display: grid; width: 34px; min-width: 34px; height: 34px; flex: 0 0 34px; place-items: center; scroll-snap-align: center; border: 0; border-radius: 9px; color: #777d8e; background: #f1f2f7; cursor: pointer; font-size: 11px; }
.episode-tabs button.is-active { color: #fff; background: #6768ef; box-shadow: 0 7px 18px rgb(91 92 246 / 20%); }
.episode-content { overflow: hidden; border-radius: 15px; background: #fff; box-shadow: 0 8px 28px rgb(45 49 68 / 6%); }
.episode-content > header { display: flex; align-items: center; gap: 12px; padding: 16px 18px; }
.episode-content > header > span { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 11px; color: #5b5cf6; background: #eff0ff; font-size: 16px; font-weight: 700; }
.episode-content > header small { color: #8b8ff1; font-size: 8px; font-weight: 700; letter-spacing: .12em; }
.episode-content h3 { margin: 4px 0 0; font-size: 14px; }
.episode-content > p { margin: 0; padding: 20px 22px; color: #5e6474; font-size: 12px; line-height: 2; overflow-wrap: anywhere; white-space: pre-wrap; }
.episode-content > p.episode-content-state { min-height: 100px; display: grid; place-items: center; color: #9a9ead; }
.episode-content > footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 11px 18px; color: #8b909f; background: #f5f6f9; font-size: 9px; }
.episode-content > footer span { display: inline-flex; align-items: center; gap: 5px; }
.continue-button { position: relative; display: flex; width: 100%; min-height: 52px; align-items: center; justify-content: center; margin-top: 28px; padding: 0 52px; border: 0; border-radius: 13px; color: #fff; background: #5b5cf6; box-shadow: 0 14px 30px rgb(91 92 246 / 22%); cursor: pointer; font-size: 13px; font-weight: 700; }
.continue-button > span { display: inline-flex; align-items: center; gap: 8px; }
.continue-button > svg { position: absolute; right: 20px; }
.continue-button:hover { background: #4d4ee9; transform: translateY(-1px); }
@media (max-width: 960px) {
  .agent-topbar { grid-template-columns: 1fr auto; }
  .agent-phases { justify-self: end; }
  .agent-project-nav { grid-row: 1; }
  .phase-line { width: 8px; }
  .agent-phases button { width: 52px; }
  .analysis-hero { grid-template-columns: 118px minmax(0, 1fr); }
  .project-cover-art { height: 150px; }
  .analysis-hero > .secondary-action { grid-column: 2; justify-self: start; }
}
@media (max-width: 720px) {
  .agent-topbar { position: static; display: flex; min-height: auto; align-items: stretch; flex-direction: column; gap: 12px; padding: 12px 14px; }
  .agent-phases { justify-content: center; }
  .agent-content { width: 100%; padding: 22px 14px 60px; }
  .analysis-hero { grid-template-columns: 86px minmax(0, 1fr); gap: 15px; padding: 15px; }
  .project-cover-art { height: 116px; }
  .analysis-hero h1 { font-size: 19px; }
  .genre-tags { margin-top: 11px; }
  .profile-grid, .character-grid { grid-template-columns: 1fr; }
  .model-readiness-grid { grid-template-columns: 1fr; }
  .analysis-section { padding-top: 30px; }
  .analysis-progress-card { grid-template-columns: 44px minmax(0, 1fr); }
  .analysis-progress-card > span { width: 44px; height: 44px; }
  .analysis-progress-card > button { grid-column: 2; justify-self: start; }
  .episode-content > footer { align-items: flex-start; flex-direction: column; }
}
@media (max-width: 480px) {
  .agent-project-nav strong { max-width: 250px; }
  .agent-phases button { width: 48px; }
  .analysis-hero { grid-template-columns: 1fr; }
  .project-cover-art { display: none; }
  .analysis-hero > .secondary-action { grid-column: 1; }
  .analysis-section > header { align-items: flex-start; flex-direction: column; }
}
</style>
