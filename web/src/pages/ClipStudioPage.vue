<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowUpRight, Film, Image, MessageSquare, Plus, RefreshCw, Wallet, AlertCircle } from 'lucide-vue-next'
import { api, mediaUrl, ApiRequestError } from '@/api'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import CreationAgentPanel from '@/features/creation-agent/CreationAgentPanel.vue'
import AgentActivity from '@/features/creation-agent/AgentActivity.vue'
import { displayClipPrompt } from '@/features/creation-agent/clipReferences'
import { clipApi, type ClipSession } from '@/features/creation-agent/clipApi'
import { useCreationAgentStore, isAgentRunning } from '@/features/creation-agent/store'
import { useAuthStore } from '@/features/auth/authStore'
import type { Asset, AssetGenerationRecord, Scene, Video } from '@/types'

const route = useRoute(), router = useRouter(), store = useCreationAgentStore(), auth = useAuthStore()
const session = ref<ClipSession | null>(null), scenes = ref<Scene[]>([]), assets = ref<Asset[]>([]), videos = ref<Video[]>([])
const imageHistory = ref<Record<number, AssetGenerationRecord[]>>({})
const loading = ref(true), starting = ref(false), startFailed = ref(false), refreshing = ref(false), error = ref(''), resultsError = ref(''), chatOpen = ref(true)
const startErrorCode = ref<number | null>(null)
const quotaBlocked = computed(() => startFailed.value && startErrorCode.value === 402)
const personalLimit = computed(() => quotaBlocked.value && /个人.*限额|personal.*(?:limit|quota)/i.test(error.value))
const canRecharge = computed(() => Boolean(auth.isSuperAdmin || ['admin','creator'].includes(auth.role || '')))
const quotaLink = computed(() => personalLimit.value && auth.canManageMembers ? '/members' : '/profile')
const quotaAction = computed(() => personalLimit.value ? auth.canManageMembers ? tr('管理成员额度') : tr('查看我的额度') : canRecharge.value ? tr('查看余额 / 充值') : tr('查看团队信息'))
let epoch = 0, timer: ReturnType<typeof setInterval> | undefined
const targets = computed(() => session.value ? [
  ...(session.value.scene_id ? [{ kind: 'scene' as const, id: session.value.scene_id }] : []),
  ...(session.value.asset_id ? [{ kind: 'asset' as const, id: session.value.asset_id }] : []),
] : [])
const statusText = (status: number) => tr(({ 1: '等待中', 2: '生成中', 3: '已完成', 4: '生成失败', 5: '已取消', 6: '排队中' } as Record<number, string>)[status] || '状态待确认')

async function refresh() {
  if (!session.value || refreshing.value) return
  const current = epoch, value = session.value
  refreshing.value = true
  try {
    const [shotList, assetList] = await Promise.all([api.scenes(value.chapter_id), api.assets(value.project_id, 1, 100, value.chapter_id)])
    if (current !== epoch) return
    scenes.value = shotList.data.items; assets.value = assetList.data.items
    const [history, generatedImages] = await Promise.all([
      Promise.all(shotList.data.items.map(shot => api.videoGenerationHistory(shot.id))),
      Promise.all(assetList.data.items.map(async asset => [asset.id, (await api.assetGenerationHistory(asset.id)).data] as const)),
    ])
    if (current !== epoch) return
    imageHistory.value = Object.fromEntries(generatedImages)
    videos.value = history.flatMap(result => result.data)
    const active = videos.value.filter(video => isAgentRunning(video.status))
    if (active.length) {
      const updates = await Promise.all(active.map(video => api.queryVideo(video.id)))
      if (current !== epoch) return
      const byId = new Map(updates.map(result => [result.data.id, result.data]))
      videos.value = videos.value.map(video => byId.get(video.id) ?? video)
    }
    resultsError.value = ''
  } catch (caught) { if (current === epoch) resultsError.value = caught instanceof Error ? caught.message : tr('生成结果读取失败') }
  finally { if (current === epoch) refreshing.value = false }
}
async function start() {
  if (!session.value || starting.value) return
  const current = epoch
  starting.value = true; error.value = ''; startFailed.value = false; startErrorCode.value = null
  try {
    const response = await clipApi.start(session.value.project_id)
    if (current !== epoch) return
    session.value.conversation_id = response.data.conversation_id
    await router.replace({ name: 'clip-studio', params: { projectId: session.value.project_id } })
  } catch (caught) { if (current === epoch) { startFailed.value = true; startErrorCode.value = caught instanceof ApiRequestError ? caught.code : null; error.value = caught instanceof DOMException && caught.name === 'TimeoutError' ? tr('启动请求响应超时，请重试以确认任务状态') : caught instanceof Error ? caught.message : tr('创作未能开始，请重试') } }
  finally { if (current === epoch) starting.value = false }
}
async function load() {
  const current = ++epoch
  clearInterval(timer); store.disconnect()
  session.value = null; scenes.value = []; assets.value = []; videos.value = []
  loading.value = true; starting.value = false; imageHistory.value = {}; error.value = ''; resultsError.value = ''; refreshing.value = false; startFailed.value = false; startErrorCode.value = null
  try {
    const response = await clipApi.session(Number(route.params.projectId))
    if (current !== epoch) return
    session.value = response.data
    loading.value = false
    if (route.query.start === '1') await start()
    if (current !== epoch) return
    await refresh()
    timer = setInterval(() => { if (!document.hidden) void refresh() }, 4000)
  } catch (caught) { if (current === epoch) error.value = caught instanceof DOMException && caught.name === 'TimeoutError' ? tr('片段读取超时，请重试') : caught instanceof Error ? caught.message : tr('无法打开片段') }
  finally { if (current === epoch) loading.value = false }
}
async function generate(kind: 'image' | 'video', id: number) {
  const value = session.value
  if (!value || store.busy || store.loading || starting.value || quotaBlocked.value) return
  const modelId = kind === 'image' ? value.image_model_config_id : value.model_config_id
  const target = { kind: kind === 'video' ? 'scene' as const : 'asset' as const, id }
  const accepted = await store.send({ message: kind === 'video' ? '生成视频' : '生成图片', chapter_id: value.chapter_id,
    targets: [target], write_scope: 'selected', model_config_id: value.assistant_model_config_id,
    production_intents: [{ operation: kind, target_id: id, request_id: crypto.randomUUID(), media_model_config_id: modelId ?? undefined,
      ...(kind === 'video' ? {video_options: { aspect_ratio: value.aspect_ratio, resolution: value.resolution, duration: value.duration, reference_media: value.reference_media }} : {}),
    }],
  })
  if (accepted) void refresh()
}
watch([() => route.params.projectId, () => auth.activeTeamId], load, { immediate: true })
onBeforeUnmount(() => { ++epoch; clearInterval(timer); store.disconnect() })
</script>

<template>
  <main class="clip-studio">
    <header class="clip-studio-header"><RouterLink to="/" class="studio-back"><ArrowLeft :size="17" />{{ tr('首页') }}</RouterLink><div class="studio-title"><strong>{{ session?.name || tr('片段创作') }}</strong><span v-if="session">{{ session.aspect_ratio }} · {{ session.resolution }} · {{ session.model_name }}</span></div><RouterLink to="/" class="new-clip"><Plus :size="16" />{{ tr('新片段') }}</RouterLink></header>
    <div v-if="loading" class="studio-loading" aria-busy="true"><AgentActivity :active="true" :text="starting ? tr('正在启动创作助手…') : tr('正在恢复创作…')" /></div>
    <div v-else-if="!session" class="studio-loading"><p role="alert">{{ error }}</p><AppButton @click="load">{{ tr('重试') }}</AppButton><RouterLink to="/">{{ tr('返回首页') }}</RouterLink></div>
    <div v-else class="studio-layout" :class="{'chat-closed': !chatOpen, 'has-start-error': startFailed}">
      <CreationAgentPanel v-show="chatOpen" :suspended="quotaBlocked || starting" :key="session.project_id" :project-id="session.project_id" :chapter-id="session.chapter_id" :selected-targets="targets" :initial-conversation-id="session.conversation_id" :initial-user-text="session.prompt" :video-defaults="session.task_type === 'video' ? { model_config_id: session.model_config_id, aspect_ratio: session.aspect_ratio, resolution: session.resolution, duration: session.duration, reference_media: session.reference_media } : undefined" :chapter-label="tr('当前片段')" @changed="refresh" @close="chatOpen = false" />
      <section class="studio-results" :aria-label="tr('创作结果')">
        <header class="results-heading"><div><span>{{ tr('创作空间') }}</span><h1>{{ session.task_type === 'image' ? tr('把想法变成画面') : tr('让这个镜头发生') }}</h1></div><div><AppButton v-if="!chatOpen" :aria-label="tr('打开创作助手')" @click="chatOpen = true"><MessageSquare :size="16" />{{ tr('创作助手') }}</AppButton><AppButton icon-only :aria-label="tr('刷新生成结果')" :loading="refreshing" @click="refresh"><RefreshCw :size="16" /></AppButton></div></header>
        <section v-if="startFailed" class="studio-start-notice" :class="{'is-quota':quotaBlocked}" role="alert">
          <span class="start-notice-icon"><Wallet v-if="quotaBlocked" :size="24" /><AlertCircle v-else :size="24" /></span>
          <div><h2>{{ quotaBlocked ? personalLimit ? tr('个人额度已用完') : tr('余额不足，暂时无法开始') : tr('暂时无法开始创作') }}</h2><p>{{ error }}</p><p class="start-notice-preserved">{{ tr('你的描述、参考素材和生成参数已保存，处理后可以继续本次创作。') }}</p>
            <div class="start-notice-actions"><RouterLink v-if="quotaBlocked" :to="quotaLink">{{ quotaAction }}<ArrowUpRight :size="14" /></RouterLink><AppButton variant="secondary" size="sm" :loading="starting" @click="start">{{ quotaBlocked ? tr('处理后继续创作') : tr('重试') }}</AppButton><RouterLink v-if="!quotaBlocked" to="/settings">{{ tr('查看设置') }}</RouterLink></div>
          </div>
        </section>
        <AgentActivity v-if="starting" :active="true" :text="tr('正在继续本次创作…')" />
        <p v-if="resultsError" class="studio-error" role="alert">{{ resultsError }}</p>
        <section v-if="assets.length" class="result-group"><h2><Image :size="16" />{{ session.task_type === 'image' ? tr('图片') : tr('参考画面') }}</h2><div class="reference-grid"><article v-for="asset in assets" :key="asset.id" class="result-card">
          <img v-if="asset.main_image" :src="mediaUrl(asset.main_image)" :alt="asset.canonical_name" :style="{ aspectRatio: session.aspect_ratio.replace(':','/') }">
          <div v-else class="media-placeholder" :style="{ aspectRatio: session.aspect_ratio.replace(':','/') }"><Image :size="28" /><span>{{ tr('参考画面将在生成后显示') }}</span></div>
          <p v-if="imageHistory[asset.id]?.[0]" class="image-task-status" role="status">{{ statusText(imageHistory[asset.id]![0]!.status) }}<span v-if="imageHistory[asset.id]![0]!.error_message"> · {{ imageHistory[asset.id]![0]!.error_message }}</span></p>
          <footer><strong>{{ asset.canonical_name }}</strong><AppButton size="sm" :disabled="store.busy || store.loading || starting || quotaBlocked" @click="generate('image',asset.id)">{{ asset.main_image ? tr('重新生成') : tr('生成图片') }}</AppButton></footer>
          <details><summary>{{ tr('查看提示词') }}</summary><p>{{ asset.base_traits }}</p></details>
        </article></div></section>
        <section v-if="session.task_type === 'video'" class="result-group"><h2><Film :size="16" />{{ tr('镜头与视频') }}</h2>
          <article v-for="scene in scenes" :key="scene.id" class="result-card shot-card">
            <header><div><span>{{ tr('镜头') }} {{ scene.sequence }}</span><strong>{{ scene.description }}</strong></div><AppButton variant="secondary" size="sm" :disabled="store.busy || store.loading || starting || quotaBlocked" @click="generate('video', scene.id)">{{ tr('生成视频') }}<ArrowUpRight :size="14" /></AppButton></header>
            <div v-if="videos.some(video => video.scene_id === scene.id)" class="video-versions"><div v-for="video in videos.filter(item => item.scene_id === scene.id)" :key="video.id" class="video-result">
              <video v-if="video.status === 3 && video.url" :src="mediaUrl(video.url)" controls playsinline preload="metadata" :style="{aspectRatio: session.aspect_ratio.replace(':','/')}" />
              <div v-else class="media-placeholder"><AgentActivity :active="isAgentRunning(video.status)" :text="statusText(video.status)" /><p v-if="video.metadata?.error" role="alert">{{ video.metadata.error }}</p></div>
              <span class="version-status">{{ statusText(video.status) }} · #{{ video.id }}</span>
            </div></div>
            <div v-else class="shot-empty"><Film :size="26" /><p>{{ tr('在左侧完善镜头，确认后生成视频。') }}</p></div>
            <details><summary>{{ tr('查看完整提示词') }}</summary><p>{{ displayClipPrompt(scene.prompt || '', session.reference_media) }}</p></details>
          </article>
          <p v-if="!scenes.length" class="empty-results">{{ tr('当前还没有镜头，可以让助手帮你创建。') }}</p>
        </section>
        <footer class="studio-footnote">{{ tr('这是独立片段。连续剧和多集制作请前往') }} <RouterLink to="/projects">{{ tr('我的创作') }}</RouterLink>。</footer>
      </section>
    </div>
  </main>
</template>

<style scoped>
/* Beautiful UI Agent Screen: persistent conversation, compact live status, content-led results. */
.clip-studio { color: var(--app-text); background: var(--app-canvas); min-height: 100dvh; animation: studio-arrive 320ms cubic-bezier(.2,.8,.2,1); }
.clip-studio-header { height: 66px; box-sizing: border-box; display: flex; align-items: center; gap: 24px; padding: 0 26px; border-bottom: 1px solid var(--app-border); background: var(--app-surface); }
.studio-back, .new-clip { display: inline-flex; align-items: center; gap: 8px; color: var(--app-text-secondary); font-size: 12px; min-height: 44px; white-space: nowrap; }
.studio-title { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 3px; }.studio-title strong { font-size: 13px; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.studio-title span { font-size: 10px; color: var(--app-text-muted); }
.studio-layout { display: grid; grid-template-columns: minmax(340px, 390px) minmax(0, 1fr); min-height: calc(100dvh - 66px); }.studio-layout.chat-closed { grid-template-columns: 1fr; }
.studio-layout :deep(.creation-agent-panel) { width: 100%; top: 0; height: calc(100dvh - 66px); border-left: 0; border-right: 1px solid var(--app-border); }
.studio-results { min-width: 0; padding: 34px clamp(20px,4vw,64px) 48px; max-height: calc(100dvh - 66px); box-sizing: border-box; overflow: auto; }
.results-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; gap: 16px; }.results-heading > div:last-child { display: flex; }.results-heading span { font-size: 11px; color: var(--app-text-muted); }.results-heading h1 { font-size: 24px; letter-spacing: -.03em; font-weight: 550; margin: 8px 0 0; }
.result-group { margin: 0 0 30px; }.result-group h2 { display: flex; align-items: center; gap: 8px; margin: 0 0 14px; font-size: 13px; font-weight: 500; color: var(--app-text-secondary); }
.reference-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 18px; }
.result-card { background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 14px; overflow: hidden; min-width: 0; }
.result-card img, .result-card video { display: block; width: 100%; max-height: 480px; object-fit: contain; background: var(--app-surface-muted); }
.image-task-status { padding: 0 16px; font-size: 12px; color: var(--app-text-secondary); overflow-wrap: anywhere; }
.result-card footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; }.result-card strong { font-weight: 500; font-size: 13px; }
.result-card details { border-top: 1px solid var(--app-border); padding: 12px 16px; font-size: 12px; }.result-card summary { cursor: pointer; color: var(--app-text-secondary); }.result-card details p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; color: var(--app-text-secondary); max-height: 260px; overflow: auto; }
.shot-card { margin-bottom: 18px; }.shot-card > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px; }.shot-card header > div { display: flex; flex-direction: column; gap: 6px; }.shot-card header span { font-size: 10px; color: var(--app-text-muted); }
.video-versions { display: grid; grid-template-columns: repeat(auto-fit,minmax(240px,1fr)); gap: 12px; padding: 0 16px 16px; }.video-result { min-width: 0; }.version-status { display: block; font-size: 10px; color: var(--app-text-muted); margin-top: 8px; }
.media-placeholder, .shot-empty { width: 100%; box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 12px; min-height: 180px; max-height: 320px; color: var(--app-text-muted); background: var(--app-surface-muted); font-size: 12px; }.media-placeholder p { max-width: 90%; overflow-wrap: anywhere; }.shot-empty { width: auto; min-height: 200px; margin: 0 16px 16px; border-radius: 8px; }.studio-footnote { font-size: 11px; line-height: 1.8; color: var(--app-text-muted); }.studio-footnote a { color: var(--app-text-secondary); }
.studio-error { color: var(--app-danger, #c34a48); font-size: 13px; }.studio-loading { min-height: 65dvh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; }.studio-loading a { color: var(--app-text-secondary); font-size: 13px; }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
@keyframes studio-arrive { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@media(max-width: 850px) { .studio-layout { grid-template-columns: 320px minmax(0,1fr); }.studio-results { padding: 24px 16px; }.results-heading h1 { font-size: 20px; }.shot-card > header { flex-wrap: wrap; } }
@media(max-width: 650px) { .studio-results :deep(.app-button) { min-height: 44px; }  .clip-studio-header { padding: 0 14px; gap: 12px; }.studio-layout { display: flex; flex-direction: column; }.studio-layout :deep(.creation-agent-panel) { height: 65dvh; border-right: 0; border-bottom: 1px solid var(--app-border); position: relative; }.studio-results { max-height: none; }.reference-grid { grid-template-columns: 1fr; } }
@media(prefers-reduced-motion: reduce) { .clip-studio { animation: none; } }

.studio-start-notice { display: flex; align-items: flex-start; gap: 15px; margin: 0 0 26px; padding: 20px; border-radius: 14px; background: var(--app-surface); color: var(--app-text); }
.studio-start-notice.is-quota { background: color-mix(in srgb, var(--creation-warning, #b17d30) 9%, var(--app-surface)); }.start-notice-icon { display: grid; place-items: center; width: 44px; height: 44px; flex-shrink: 0; border-radius: 12px; color: var(--creation-warning, #b17d30); background: color-mix(in srgb, var(--creation-warning, #b17d30) 12%, transparent); }
.studio-start-notice h2 { margin: 0 0 8px; font-size: 17px; font-weight: 600; }.studio-start-notice p { margin: 5px 0; font-size: 13px; line-height: 1.7; color: var(--app-text-secondary); }.studio-start-notice .start-notice-preserved { font-size: 12px; color: var(--app-text-muted); }.start-notice-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 15px; }.start-notice-actions a { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; font-size: 12px; color: var(--app-accent); }
@media(max-width:650px) { .studio-layout.has-start-error .studio-results { order: -1; }.start-notice-actions a { min-height: 44px; }.studio-start-notice { padding: 16px; gap: 12px; }.studio-start-notice h2 { font-size: 15px; } }
</style>
