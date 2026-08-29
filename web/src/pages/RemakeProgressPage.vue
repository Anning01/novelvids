<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Circle,
  Film,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { api } from '@/api'
import { TaskStatusEnum, type RemakeProgressSnapshot, type RemakeProgressSource } from '@/types'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const snapshot = ref<RemakeProgressSnapshot | null>(null)
const loading = ref(true)
const connectionState = ref<'connecting' | 'live' | 'reconnecting' | 'closed'>('connecting')
const errorMessage = ref('')
const retryingSourceIds = ref<Set<number>>(new Set())
let pageAlive = true
let streamGeneration = 0
let streamController: AbortController | null = null
let redirecting = false

const stages = [
  { key: 'queued', label: '进入拆解队列', description: '后台任务已创建，可以安全离开页面。', threshold: 0 },
  { key: 'preparing', label: '准备视频素材', description: '校验并转换为模型可分析的视频。', threshold: 10 },
  { key: 'extracting_assets', label: '识别全局设定', description: '提取角色、场景与关键道具。', threshold: 20 },
  { key: 'detecting_scenes', label: '检测并切分镜头', description: '分析转场和镜头边界。', threshold: 42 },
  { key: 'generating_storyboards', label: '生成专业分镜', description: '逐镜头生成画面、动作与运镜描述。', threshold: 55 },
  { key: 'persisting', label: '保存设定与分镜', description: '写入项目资产和分镜工作区。', threshold: 88 },
  { key: 'completed', label: '拆解完成', description: '即将进入设定与分镜页面。', threshold: 100 },
] as const

const isCompleted = computed(() => snapshot.value?.aggregate_status === 'completed')
const hasFailures = computed(() => Boolean(snapshot.value?.source_summary.failed))
const activeStage = computed(() => {
  const activeTask = snapshot.value?.sources
    .map(source => source.task)
    .find(task => task && ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(task.status))
  return activeTask?.stage || (isCompleted.value ? 'completed' : 'queued')
})
const statusTitle = computed(() => {
  if (isCompleted.value) return '视频拆解完成'
  if (snapshot.value?.aggregate_status === 'failed') return '视频拆解失败'
  if (snapshot.value?.aggregate_status === 'partial_failed') return '部分剧集拆解失败'
  if (snapshot.value?.aggregate_status === 'queued') return '等待开始拆解'
  return '正在拆解视频'
})
const statusDescription = computed(() => {
  if (isCompleted.value) return '设定和分镜已经生成，正在为你打开创作页面。'
  if (hasFailures.value) return '已完成的剧集会保留，可单独重试失败剧集。'
  return 'AI 正在识别设定、切分镜头并生成分镜。关闭或离开本页面不会中断后台任务。'
})

function isTerminalTask(source: RemakeProgressSource) {
  return source.task && [TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(source.task.status)
}

function sourceStatusLabel(source: RemakeProgressSource) {
  const status = source.task?.status
  if (status === TaskStatusEnum.COMPLETED) return '已完成'
  if (status === TaskStatusEnum.FAILED || status === TaskStatusEnum.CANCELLED) return '拆解失败'
  if (status === TaskStatusEnum.PROCESSING) return stageLabel(source.task?.stage)
  return '队列中'
}

function stageLabel(stage?: string | null) {
  return stages.find(item => item.key === stage)?.label || '正在处理'
}

function stageState(key: string, threshold: number) {
  if (isCompleted.value || (snapshot.value?.overall_progress ?? 0) > threshold) return 'completed'
  if (activeStage.value === key) return 'active'
  return 'pending'
}

function applySnapshot(next: RemakeProgressSnapshot) {
  snapshot.value = next
  connectionState.value = next.terminal ? 'closed' : 'live'
  errorMessage.value = ''
  if (next.aggregate_status === 'completed') void enterWorkspace(next.entry_path)
}

async function enterWorkspace(path = snapshot.value?.entry_path) {
  if (!path || redirecting) return
  redirecting = true
  streamController?.abort()
  await router.replace(path)
}

function waitForReconnect(milliseconds: number) {
  return new Promise<void>(resolve => window.setTimeout(resolve, milliseconds))
}

function startStream() {
  const generation = ++streamGeneration
  streamController?.abort()
  const controller = new AbortController()
  streamController = controller
  void (async () => {
    let attempt = 0
    while (pageAlive && generation === streamGeneration && !snapshot.value?.terminal) {
      try {
        connectionState.value = attempt ? 'reconnecting' : 'connecting'
        await api.streamRemakeProjectProgress(projectId.value, applySnapshot, controller.signal)
        if (snapshot.value?.terminal || controller.signal.aborted) return
        throw new Error('进度连接已断开')
      } catch (error) {
        if (controller.signal.aborted || !pageAlive || generation !== streamGeneration) return
        attempt += 1
        connectionState.value = 'reconnecting'
        errorMessage.value = error instanceof Error ? error.message : '拆解进度连接中断'
        await waitForReconnect(Math.min(5000, 1000 * attempt))
      }
    }
  })()
}

async function loadProgress() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) {
    errorMessage.value = '重制项目编号无效'
    loading.value = false
    return
  }
  loading.value = true
  try {
    applySnapshot((await api.remakeProjectProgress(projectId.value)).data)
    if (!snapshot.value?.terminal) startStream()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '无法读取拆解进度'
  } finally {
    loading.value = false
  }
}

async function retrySource(source: RemakeProgressSource) {
  if (retryingSourceIds.value.has(source.source_id)) return
  const next = new Set(retryingSourceIds.value)
  next.add(source.source_id)
  retryingSourceIds.value = next
  try {
    await api.retryRemakeSource(projectId.value, source.source_id)
    applySnapshot((await api.remakeProjectProgress(projectId.value)).data)
    startStream()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重试失败'
  } finally {
    const remaining = new Set(retryingSourceIds.value)
    remaining.delete(source.source_id)
    retryingSourceIds.value = remaining
  }
}

onMounted(loadProgress)
onBeforeUnmount(() => {
  pageAlive = false
  streamGeneration += 1
  streamController?.abort()
})
</script>

<template>
  <main class="remake-progress-page">
    <header class="progress-header">
      <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="返回项目列表" @click="router.push('/projects')"><ArrowLeft :size="18" /></AppButton>
      <div>
        <small>AI REMAKE WORKSHOP</small>
        <strong>{{ snapshot?.name || '重制拆解' }}</strong>
      </div>
      <span class="background-badge"><span />后台持续运行</span>
    </header>

    <section v-if="loading" class="progress-loading" role="status" aria-live="polite">
      <LoaderCircle :size="30" />
      <strong>正在连接拆解任务…</strong>
      <p>正在读取后台保存的最新进度。</p>
    </section>

    <section v-else-if="!snapshot" class="progress-loading is-error" role="alert">
      <AlertTriangle :size="30" />
      <strong>暂时无法读取拆解进度</strong>
      <p>{{ errorMessage }}</p>
      <AppButton type="button" variant="primary" size="sm" @click="loadProgress"><RefreshCw :size="15" />重新连接</AppButton>
    </section>

    <div v-else class="progress-content">
      <section class="progress-hero" role="status" aria-live="polite">
        <div class="hero-icon" :class="{ 'is-complete': isCompleted, 'is-failed': snapshot.terminal && hasFailures }">
          <Check v-if="isCompleted" :size="28" />
          <AlertTriangle v-else-if="snapshot.terminal && hasFailures" :size="28" />
          <Sparkles v-else :size="28" />
        </div>
        <div class="hero-copy">
          <small>{{ connectionState === 'reconnecting' ? '正在重新连接实时进度' : 'AI VIDEO DECOMPOSITION' }}</small>
          <h1>{{ statusTitle }}</h1>
          <p>{{ statusDescription }}</p>
        </div>
        <div class="overall-progress" :aria-label="`总体进度 ${snapshot.overall_progress}%`">
          <strong>{{ snapshot.overall_progress }}<small>%</small></strong>
          <span>总体进度</span>
        </div>
        <div class="progress-track" aria-hidden="true"><span :style="{ width: `${snapshot.overall_progress}%` }" /></div>
        <p v-if="connectionState === 'reconnecting'" class="connection-message"><RefreshCw :size="13" />实时连接中断，正在自动重连；后台任务不受影响。</p>
      </section>

      <section class="progress-grid">
        <article class="pipeline-card">
          <header><div><small>PROCESS</small><h2>拆解过程</h2></div><span>{{ snapshot.source_summary.completed }}/{{ snapshot.source_summary.total }} 集完成</span></header>
          <ol class="pipeline-list">
            <li v-for="stage in stages" :key="stage.key" :class="`is-${stageState(stage.key, stage.threshold)}`">
              <span class="stage-marker">
                <Check v-if="stageState(stage.key, stage.threshold) === 'completed'" :size="14" />
                <LoaderCircle v-else-if="stageState(stage.key, stage.threshold) === 'active'" :size="15" />
                <Circle v-else :size="10" />
              </span>
              <div><strong>{{ stage.label }}</strong><p>{{ stage.description }}</p></div>
            </li>
          </ol>
        </article>

        <article class="episodes-card">
          <header><div><small>EPISODES</small><h2>剧集进度</h2></div></header>
          <div class="episode-list">
            <section v-for="source in snapshot.sources" :key="source.source_id" class="episode-item" :class="{ 'is-failed': source.task?.status === TaskStatusEnum.FAILED || source.task?.status === TaskStatusEnum.CANCELLED }">
              <span class="episode-icon"><Film :size="17" /></span>
              <div class="episode-copy">
                <strong>第 {{ source.episode_number }} 集</strong>
                <p>{{ source.original_filename }}</p>
                <div><span :style="{ width: `${source.task?.progress || 0}%` }" /></div>
              </div>
              <div class="episode-state">
                <strong>{{ source.task?.progress || 0 }}%</strong>
                <span>{{ sourceStatusLabel(source) }}</span>
              </div>
              <AppButton
                v-if="isTerminalTask(source) && source.task?.status !== TaskStatusEnum.COMPLETED"
                type="button"
                variant="soft"
                size="xs"
                :loading="retryingSourceIds.has(source.source_id)"
                @click="retrySource(source)"
              ><RotateCcw v-if="!retryingSourceIds.has(source.source_id)" :size="13" />重试</AppButton>
              <p v-if="source.task?.error_message" class="episode-error">{{ source.task.error_message }}</p>
            </section>
          </div>
        </article>
      </section>

      <footer class="progress-footer">
        <p><strong>可以放心离开</strong><span>任务状态和结果保存在后台，稍后从项目列表回来会继续显示最新进度。</span></p>
        <AppButton v-if="isCompleted" type="button" variant="primary" size="lg" @click="enterWorkspace()">进入设定与分镜</AppButton>
        <AppButton v-else type="button" variant="secondary" size="lg" @click="router.push('/projects')">返回项目列表</AppButton>
      </footer>
    </div>
  </main>
</template>

<style scoped>
.remake-progress-page { height: 100vh; min-height: 100vh; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; color: #292d3b; background: radial-gradient(circle at 50% -10%, #eef0ff 0, transparent 36%), #f8f9fc; }
.progress-header { display: grid; min-height: 70px; grid-template-columns: 40px minmax(0,1fr) auto; align-items: center; gap: 12px; padding: 0 30px; border-bottom: 1px solid #e8eaf1; background: rgb(255 255 255 / 88%); backdrop-filter: blur(16px); }
.progress-header > div { display: grid; gap: 2px; }.progress-header small, .pipeline-card header small, .episodes-card header small { color: #6a6cf0; font-size: 8px; font-weight: 750; letter-spacing: .15em; }.progress-header strong { font-size: 13px; }
.background-badge { display: inline-flex; align-items: center; gap: 7px; padding: 7px 10px; border-radius: 999px; color: #3b8062; background: #eaf6f0; font-size: 10px; }.background-badge > span { width: 7px; height: 7px; border-radius: 50%; background: #39a677; box-shadow: 0 0 0 4px rgb(57 166 119 / 12%); }
.progress-loading { display: grid; min-height: calc(100vh - 70px); place-items: center; align-content: center; gap: 10px; padding: 24px; text-align: center; }.progress-loading > svg { color: #5b5cf6; animation: spin 1s linear infinite; }.progress-loading strong { font-size: 16px; }.progress-loading p { margin: 0; color: #858b9b; font-size: 11px; }.progress-loading.is-error > svg { color: #bf6570; animation: none; }
.progress-content { display: grid; width: min(1040px, calc(100% - 40px)); gap: 18px; margin: 0 auto; padding: 48px 0 56px; }
.progress-hero { display: grid; grid-template-columns: 58px minmax(0,1fr) auto; align-items: center; gap: 16px; padding: 26px; border: 1px solid #e4e6ef; border-radius: 20px; background: #fff; box-shadow: 0 18px 55px rgb(49 53 79 / 7%); }
.hero-icon { display: grid; width: 58px; height: 58px; place-items: center; border-radius: 17px; color: #5b5cf6; background: #eff0ff; }.hero-icon > svg { animation: pulse 1.8s ease-in-out infinite; }.hero-icon.is-complete { color: #2f8b68; background: #e9f6f0; }.hero-icon.is-complete > svg, .hero-icon.is-failed > svg { animation: none; }.hero-icon.is-failed { color: #bb5b68; background: #fff0f2; }
.hero-copy { min-width: 0; }.hero-copy small { color: #6b6df0; font-size: 8px; font-weight: 750; letter-spacing: .14em; }.hero-copy h1 { margin: 5px 0 7px; font-size: clamp(21px,3vw,30px); letter-spacing: -.035em; }.hero-copy p { max-width: 650px; margin: 0; color: #777e90; font-size: 11px; line-height: 1.7; }
.overall-progress { display: grid; justify-items: end; }.overall-progress strong { color: #4e50e9; font-size: 31px; line-height: 1; }.overall-progress strong small { font-size: 13px; }.overall-progress > span { margin-top: 5px; color: #969baa; font-size: 9px; }.progress-track { height: 7px; grid-column: 1 / -1; overflow: hidden; border-radius: 999px; background: #eef0f5; }.progress-track span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#6c6ef7,#9b82ff); transition: width .45s ease; }
.connection-message { display: inline-flex; grid-column: 1 / -1; align-items: center; gap: 6px; margin: 0; color: #9b742d; font-size: 9px; }.connection-message svg { animation: spin 1s linear infinite; }
.progress-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(360px,.85fr); gap: 18px; }.pipeline-card, .episodes-card { padding: 22px; border: 1px solid #e5e7ef; border-radius: 17px; background: #fff; box-shadow: 0 12px 36px rgb(49 53 79 / 5%); }.pipeline-card > header, .episodes-card > header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }.pipeline-card h2, .episodes-card h2 { margin: 3px 0 0; font-size: 15px; }.pipeline-card header > span { color: #858b9a; font-size: 9px; }
.pipeline-list { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }.pipeline-list li { position: relative; display: grid; min-height: 61px; grid-template-columns: 28px minmax(0,1fr); gap: 10px; color: #9a9fad; }.pipeline-list li:not(:last-child)::after { position: absolute; top: 28px; bottom: 0; left: 13px; width: 1px; background: #e5e7ed; content: ''; }.stage-marker { z-index: 1; display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; color: #a8adba; background: #f3f4f7; }.pipeline-list strong { display: block; padding-top: 2px; font-size: 11px; }.pipeline-list p { margin: 4px 0 0; font-size: 9px; line-height: 1.45; }.pipeline-list li.is-completed { color: #4e5668; }.pipeline-list li.is-completed .stage-marker { color: #fff; background: #58a583; }.pipeline-list li.is-completed:not(:last-child)::after { background: #9fd3ba; }.pipeline-list li.is-active { color: #4e50dd; }.pipeline-list li.is-active .stage-marker { color: #5b5cf6; background: #ededff; box-shadow: 0 0 0 5px rgb(91 92 246 / 8%); }.pipeline-list li.is-active .stage-marker svg { animation: spin 1s linear infinite; }
.episode-list { display: grid; max-height: 410px; gap: 9px; overflow: auto; }.episode-item { display: grid; grid-template-columns: 36px minmax(0,1fr) auto; align-items: center; gap: 10px; padding: 11px; border: 1px solid #eceef3; border-radius: 11px; background: #fafbfc; }.episode-item.is-failed { border-color: #f0d7db; background: #fff8f9; }.episode-icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 10px; color: #686af0; background: #eceeff; }.episode-copy { min-width: 0; }.episode-copy > strong { font-size: 10px; }.episode-copy > p { overflow: hidden; margin: 3px 0 7px; color: #959aa8; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }.episode-copy > div { height: 4px; overflow: hidden; border-radius: 999px; background: #e8eaf0; }.episode-copy > div span { display: block; height: 100%; border-radius: inherit; background: #7274f4; transition: width .4s ease; }.episode-state { display: grid; justify-items: end; gap: 3px; }.episode-state strong { color: #5759e8; font-size: 11px; }.episode-state span { color: #8f94a3; font-size: 8px; white-space: nowrap; }.episode-item > button { grid-column: 2 / -1; justify-self: end; }.episode-error { grid-column: 2 / -1; margin: 0; color: #b45b66; font-size: 8px; line-height: 1.45; }
.progress-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 17px 20px; border: 1px solid #e5e7ef; border-radius: 15px; background: rgb(255 255 255 / 85%); }.progress-footer p { display: grid; gap: 4px; margin: 0; }.progress-footer strong { font-size: 10px; }.progress-footer span { color: #858b9b; font-size: 9px; }
@keyframes spin { to { transform: rotate(360deg); } } @keyframes pulse { 50% { transform: scale(1.08); opacity: .72; } }
@media (max-width: 800px) { .progress-grid { grid-template-columns: 1fr; }.progress-content { padding-top: 26px; }.progress-header { padding: 0 16px; } }
@media (max-width: 560px) { .background-badge { display: none; }.progress-header { grid-template-columns: 40px 1fr; }.progress-content { width: min(100% - 24px,1040px); }.progress-hero { grid-template-columns: 48px minmax(0,1fr); padding: 19px; }.hero-icon { width: 48px; height: 48px; }.overall-progress { grid-column: 1 / -1; grid-template-columns: auto auto; align-items: end; justify-content: space-between; }.progress-footer { align-items: stretch; flex-direction: column; }.progress-footer button { width: 100%; }.pipeline-card, .episodes-card { padding: 17px; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; transition-duration: .01ms !important; } }
</style>
