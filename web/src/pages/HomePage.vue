<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, Clapperboard, Film, FolderOpen, Image, Layers, Paperclip, Sparkles } from 'lucide-vue-next'
import { api } from '@/api'
import ShowcaseGallery from '@/features/showcase/ShowcaseGallery.vue'
import ClipReferencePrompt from '@/features/creation-agent/ClipReferencePrompt.vue'
import { useClipQuote } from '@/features/creation-agent/useClipQuote'
import { nameClipReference } from '@/features/creation-agent/clipReferences'
import { locale, localeSaving, tr } from '@/i18n'
import inspirationPrompts from '../../../prompts/home_inspirations.json'
import AppButton from '@/components/AppButton.vue'
import AppSegmentedSwitch from '@/components/AppSegmentedSwitch.vue'
import AppSelect from '@/components/AppSelect.vue'
import AgentActivity from '@/features/creation-agent/AgentActivity.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { clipApi, type ClipSummary } from '@/features/creation-agent/clipApi'
import type { ImageGenerationModel, VideoGenerationModel, VideoReferenceMedia, ShowcaseWork } from '@/types'

const router = useRouter(), auth = useAuthStore()
const taskType = ref<'video' | 'image'>('video')
const mode = ref<'direct' | 'agent'>('direct')
const prompt = ref(''), modelId = ref(''), ratio = ref(''), resolution = ref(''), duration = ref('5')
const outputFormat = ref<'png' | 'gif'>('png')
const frameCount = ref('9'), frameInterval = ref<number | string>(200)
const videoModels = ref<VideoGenerationModel[]>([]), imageModels = ref<ImageGenerationModel[]>([])
const loading = ref(true), entering = ref(false), uploading = ref(false), error = ref(''), galleryError = ref('')
const recent = ref<ClipSummary[]>([]), works = ref<ShowcaseWork[]>([])
const referencePrompt = ref<InstanceType<typeof ClipReferencePrompt> | null>(null)
const references = ref<VideoReferenceMedia[]>([]), uploadInput = ref<HTMLInputElement | null>(null)
let epoch = 0
let pending: { body: string; id: string } | null = null
const models = computed(() => taskType.value === 'video' ? videoModels.value : imageModels.value)
const model = computed(() => models.value.find(item => String(item.config_id) === modelId.value))
const videoModel = computed(() => videoModels.value.find(item => String(item.config_id) === modelId.value))
const imageModel = computed(() => imageModels.value.find(item => String(item.config_id) === modelId.value))
const imageFormats = computed(() => taskType.value === 'image' ? imageModel.value?.capabilities.output_formats?.filter(value => value === 'png' || value === 'gif') ?? ['png'] : ['png'])
const gifEnabled = computed(() => taskType.value === 'image' && outputFormat.value === 'gif')
const gifFrameCounts = computed(() => imageModel.value?.capabilities.frame_counts ?? [])
const gifIntervalMin = computed(() => imageModel.value?.capabilities.frame_duration_ms_min ?? 20)
const gifIntervalMax = computed(() => imageModel.value?.capabilities.frame_duration_ms_max ?? 655350)
const gifIntervalStep = computed(() => imageModel.value?.capabilities.frame_duration_ms_step ?? 10)
const gifIntervalValid = computed(() => Number.isInteger(Number(frameInterval.value)) && Number(frameInterval.value) >= gifIntervalMin.value && Number(frameInterval.value) <= gifIntervalMax.value)
const gifParametersValid = computed(() => !gifEnabled.value || (gifFrameCounts.value.includes(Number(frameCount.value)) && gifIntervalValid.value))
const gifParameters = computed(() => gifEnabled.value ? { frame_count: Number(frameCount.value), frame_duration_ms: Number(frameInterval.value) } : {})
const ratios = computed(() => model.value?.capabilities.aspect_ratios.filter(value => value !== 'adaptive') ?? [])
const resolutions = computed(() => taskType.value === 'video' ? videoModel.value?.capabilities.resolutions ?? []
  : imageModel.value?.capabilities.clarities_by_format?.[outputFormat.value] ?? imageModel.value?.capabilities.clarities ?? [])
const durations = computed(() => {
  const caps = videoModel.value?.capabilities
  if (!caps) return []
  return Array.from({ length: caps.duration_max - caps.duration_min + 1 }, (_, index) => String(index + caps.duration_min))
})
const quoteInput = computed(() => {
  if (!model.value || !ratio.value || !resolution.value || !gifParametersValid.value) return null
  const markers = references.value.filter(item => item.mention_name && prompt.value.includes(`@{${item.mention_name}}`)).map(item => `@{${item.mention_name}}`)
  return { task_type:taskType.value, mode:mode.value, model_config_id:Number(modelId.value),
    prompt:markers.join(' '), aspect_ratio:ratio.value, resolution:resolution.value, duration:Number(duration.value),
    output_format:outputFormat.value, ...gifParameters.value, reference_media:references.value, reference_binding:'mentions' as const }
})
const {quote, loading:quoteLoading, error:quoteError, allowed:quoteAllowed, refresh:refreshQuote} = useClipQuote(quoteInput, computed(() => JSON.stringify([auth.activeTeamId, auth.user?.id])))
const checkingFunds = ref(false)
const money = (value: string) => `¥${new Intl.NumberFormat('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:6}).format(Number(value))}`

const displayDiscountPrice = computed(() => {
  if (quote.value?.estimated_cost !== null && quote.value?.estimated_cost !== undefined) {
    return Number(quote.value.estimated_cost).toFixed(2)
  }
  return null
})

const displayOriginalPrice = computed(() => {
  if (quote.value?.original_cost !== null && quote.value?.original_cost !== undefined) {
    return Number(quote.value.original_cost).toFixed(2)
  }
  if (quote.value?.estimated_cost && quote.value?.discount && Number(quote.value.discount) < 1) {
    return (Number(quote.value.estimated_cost) / Number(quote.value.discount)).toFixed(2)
  }
  return null
})

const hasDiscount = computed(() => {
  if (!quote.value) return false
  return Boolean(quote.value.discount && Number(quote.value.discount) < 1)
})


const canCreate = computed(() => Boolean(prompt.value.trim() && prompt.value.length <= 4000 && model.value && ratio.value && resolution.value && gifParametersValid.value && quoteAllowed.value && !localeSaving.value && !checkingFunds.value && !loading.value && !entering.value && !uploading.value))


const inspirations = computed(() => inspirationPrompts[gifEnabled.value ? 'gif' : 'standard'][locale.value]
  .map(item => ({ title: item.title, text: item.prompt })))
function applyInspiration(item: { text: string }) {
  prompt.value = item.text
  void nextTick(() => referencePrompt.value?.focus?.())
}

watch([taskType, models], () => {
  if (!models.value.some(item => String(item.config_id) === modelId.value)) modelId.value = String(models.value[0]?.config_id ?? '')
  if (taskType.value === 'image') {
    references.value = references.value.filter(item => item.type === 'image')
  }
})
watch(modelId, () => { references.value = [] })
watch(imageFormats, values => { if (!values.includes(outputFormat.value)) outputFormat.value = 'png' })
watch(imageModel, value => {
  if (!gifFrameCounts.value.includes(Number(frameCount.value))) frameCount.value = String(value?.capabilities.default_frame_count ?? 9)
  if (!gifIntervalValid.value) frameInterval.value = value?.capabilities.default_frame_duration_ms ?? 200
})
function normalizeGifInterval() {
  if (gifIntervalValid.value) frameInterval.value = Math.min(gifIntervalMax.value, Math.round(Number(frameInterval.value) / gifIntervalStep.value) * gifIntervalStep.value)
}
watch([model, ratios, resolutions], () => {
  if (!ratios.value.includes(ratio.value)) ratio.value = model.value?.capabilities.default_aspect_ratio === 'adaptive' ? ratios.value[0] ?? '' : model.value?.capabilities.default_aspect_ratio ?? ''
  if (!resolutions.value.includes(resolution.value)) resolution.value = resolutions.value[0] ?? ''
  if (!durations.value.includes(duration.value)) duration.value = durations.value[0] ?? '5'
})
async function load() {
  const current = ++epoch
  entering.value = false; pending = null
  loading.value = true; error.value = ''; galleryError.value = ''; recent.value = []; works.value = []
  videoModels.value = []; imageModels.value = []; references.value = []
  const results = await Promise.allSettled([
    api.videoGenerationModels(),
    api.imageGenerationModels(),
    clipApi.recent(),
    api.experienceShowcase(),
  ])
  if (current !== epoch) return
  const [videos, images, sessions, showcase] = results
  if (videos.status === 'fulfilled') videoModels.value = videos.value.data
  if (images.status === 'fulfilled') imageModels.value = images.value.data
  if (sessions.status === 'fulfilled') recent.value = sessions.value.data
  if (showcase.status === 'fulfilled') works.value = showcase.value.data
  else galleryError.value = '作品暂时无法加载'
  if (videos.status === 'rejected' || images.status === 'rejected' || sessions.status === 'rejected') error.value = '部分创作配置未能加载，请重试。'
  loading.value = false
}
watch(() => auth.activeTeamId, load, { immediate: true })
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || !model.value || uploading.value) return
  const current = epoch, selected = modelId.value, isVideo = taskType.value === 'video'
  const caps = isVideo ? videoModel.value?.capabilities : null
  uploading.value = true; error.value = ''
  try {
    for (const file of files) {
      if (current !== epoch || selected !== modelId.value) return
      const kind = file.type.startsWith('video/') || /\.(mp4|mov)$/i.test(file.name) ? 'video' : 'image'
      if (!isVideo && kind !== 'image') {
        throw new Error('图片创作仅支持参考图片')
      }
      const maximum = isVideo ? (kind === 'image' ? (caps?.max_reference_images ?? 10) : (caps?.max_reference_videos ?? 3)) : 10
      if (references.value.filter(item => item.type === kind).length >= maximum || references.value.length >= 10) {
        throw new Error('已达到当前模型的参考素材数量上限')
      }
      const result = await api.uploadVideoReference(file, Number(selected))
      if (current !== epoch || selected !== modelId.value) return
      if (!references.value.some(item => item.type === result.type && item.url === result.url)) {
        references.value = [...references.value, nameClipReference(result, references.value)]
      }
    }
  } catch (caught) { if (current === epoch) error.value = caught instanceof Error ? caught.message : '参考素材上传失败' }
  finally { uploading.value = false }
}

async function create() {
  if (!canCreate.value) return
  const current = epoch
  checkingFunds.value = true
  const affordable = await refreshQuote()
  checkingFunds.value = false
  if (!affordable || current !== epoch) return
  entering.value = true; error.value = ''
  const body = { task_type: taskType.value, mode: mode.value, model_config_id: Number(modelId.value), prompt: prompt.value.trim(), aspect_ratio: ratio.value, resolution: resolution.value, duration: Number(duration.value), output_format: outputFormat.value, ...gifParameters.value, reference_media: references.value, reference_binding: 'mentions' as const }
  const serialized = JSON.stringify(body)
  if (pending?.body !== serialized) pending = { body: serialized, id: crypto.randomUUID() }
  try {
    const session = await clipApi.create({ ...body, request_id: pending.id })
    if (current !== epoch) return
    pending = null
    await router.push({ name: 'clip-studio', params: { projectId: session.data.project_id }, query: { start: '1' } })
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '无法进入创作，请重试'; entering.value = false }
}
</script>

<template>
  <main class="clip-home">
    <div class="home-atmosphere" aria-hidden="true" />
    <Transition name="studio-entry" mode="out-in">
      <section v-if="entering" key="entering" class="entry-state" aria-live="polite" aria-busy="true">
        <div class="entry-mark"><Clapperboard :size="26" /></div>
        <h1>{{ tr('开始你的创作') }}</h1><p>{{ prompt }}</p>
        <AgentActivity :active="true" :text="tr('正在打开创作空间…')" />
      </section>
      <div v-else key="home" class="home-content">
        <header class="home-heading">
          <span class="home-eyebrow"><Sparkles :size="14" aria-hidden="true" />{{ tr('猫影 · 你的 AI 创作片场') }}</span>
          <h1>{{ tr('具现想象') }} <span>{{ tr('一镜成片') }}</span></h1>
          <p>{{ tr('从灵感到画面，让每一个好故事都有自己的镜头。') }}</p>
        </header>

        <section class="home-composer" :aria-label="tr('片段创作')">
          <header class="composer-top">
            <div class="composer-tabs" :class="{ 'is-image': taskType === 'image' }" role="group" :aria-label="tr('创作类型')">
              <button type="button" :aria-pressed="taskType === 'video'" @click="taskType = 'video'"><Film :size="15" aria-hidden="true" />{{ tr('视频生成') }}</button>
              <button type="button" :aria-pressed="taskType === 'image'" @click="taskType = 'image'"><Image :size="15" aria-hidden="true" />{{ tr('图片创作') }}</button>
            </div>
            <div class="composer-models">
              <span class="models-label">{{ tr('生成模型') }}</span>
              <AppSelect menu-class="home-select-menu" v-model="modelId" :options="models.length ? models.map(item => ({ value: String(item.config_id), label: item.name })) : [{ value: '', label: loading ? tr('读取模型…') : tr('无可用模型') }]" :ariaLabel="tr('生成模型')" density="compact" :disabled="loading || !models.length" />
            </div>
          </header>
          <div class="prompt-well">
            <ClipReferencePrompt ref="referencePrompt" v-model="prompt" :references="references" :uploading="uploading" :placeholder="gifEnabled ? tr('描述 GIF 的画面、运动与循环方式，输入 @ 引用已上传的素材…') : undefined" @remove="index => references = references.filter((_item,i) => i !== index)" @upload="uploadInput?.click()" @submit="create" />
            <div class="prompt-tools">
              <div class="inspiration-list"><span>{{ gifEnabled ? tr('试试这些动效') : tr('试试这些灵感') }}</span><button v-for="item in inspirations" :key="item.title" type="button" @click="applyInspiration(item)">{{ item.title }}<ArrowUpRight :size="12" aria-hidden="true" /></button></div>
              <input ref="uploadInput" type="file" multiple :accept="taskType === 'video' ? 'image/*,video/*' : 'image/*'" hidden @change="upload">
              <AppButton class="upload-reference" size="sm" :loading="uploading" :disabled="!model || loading" :aria-label="tr('上传参考素材')" @click="uploadInput?.click()"><Paperclip :size="15" />{{ tr('添加参考') }}</AppButton>
            </div>
          </div>
          <div class="composer-controls">
            <div class="composer-settings">
              <div><span>{{ tr('比例') }}</span><AppSelect menu-class="home-select-menu" v-model="ratio" :options="ratios.length ? ratios : [{ value: '', label: '—' }]" :ariaLabel="tr('画面比例')" density="compact" :disabled="!model" /></div>
              <div v-if="!gifEnabled"><span>{{ tr('清晰度') }}</span><AppSelect menu-class="home-select-menu" v-model="resolution" :options="resolutions.length ? resolutions : [{ value: '', label: '—' }]" :ariaLabel="tr('清晰度')" density="compact" :disabled="!model" /></div>
              <div v-if="taskType === 'image' && imageFormats.includes('gif')"><span>{{ tr('格式') }}</span><AppSelect menu-class="home-select-menu" v-model="outputFormat" :options="[{value:'png',label:tr('PNG 静态图')},{value:'gif',label:tr('GIF 动图')}]" :ariaLabel="tr('图片格式')" density="compact" :disabled="!model" /></div>
              <div v-if="taskType === 'video'"><span>{{ tr('时长') }}</span><AppSelect menu-class="home-select-menu" v-model="duration" :options="durations.length ? durations.map(value => ({value, label: `${value}s`})) : [{ value: duration, label: '—' }]" :ariaLabel="tr('片段时长')" density="compact" :disabled="!model" /></div>
              <div v-if="gifEnabled"><span>{{ tr('帧数') }}</span><AppSelect menu-class="home-select-menu" v-model="frameCount" :options="gifFrameCounts.map(value => ({value:String(value),label:tr('{p0}帧',{p0:value})}))" :ariaLabel="tr('动图帧数')" density="compact" :disabled="!model" /></div>
              <div v-if="gifEnabled"><span>{{ tr('每帧间隔') }}</span><label class="composer-frame-interval"><input v-model.number="frameInterval" type="number" :min="gifIntervalMin" :max="gifIntervalMax" :step="gifIntervalStep" :aria-label="tr('每帧间隔')" :aria-invalid="!gifIntervalValid" @change="normalizeGifInterval"><span>ms</span></label></div>
            </div>
            <div class="composer-actions">
              <AppSegmentedSwitch v-model="mode" class="composer-mode-switch" :class="{'is-direct':mode === 'direct'}" :items="[{value:'agent',label:'Agent'},{value:'direct',label:tr('直创')}]" :label="tr('创作方式')" />
              <button
                class="generate-action-btn"
                type="button"
                :disabled="!canCreate"
                :aria-busy="quoteLoading || checkingFunds"
                :aria-label="mode === 'direct' ? tr('立即生成') : tr('开始创作')"
                @click="create"
              >
                <Sparkles :size="17" class="generate-btn-sparkle" aria-hidden="true" />
                <span class="generate-btn-label">{{ tr('生成') }}</span>
                <span class="generate-btn-price">
                <span class="generate-btn-approx">{{ displayDiscountPrice !== null ? tr('约') : quoteLoading ? tr('报价中…') : tr('暂未报价') }}</span>
                <span v-if="hasDiscount && displayOriginalPrice !== null" class="generate-btn-original" :title="`¥${displayOriginalPrice}`">¥{{ displayOriginalPrice }}</span>
                <span v-if="displayDiscountPrice !== null" class="generate-btn-discount">¥{{ displayDiscountPrice }}</span>
                <span v-if="hasDiscount && displayDiscountPrice !== null" class="generate-btn-badge" :title="quote?.discount_description || tr('限时特惠')">
                  <svg class="discount-badge-svg" viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
                    <path
                      d="M12 2.2l1.6 2 2.5-.5.9 2.4 2.5.7.1 2.6 2.3 1.3-.7 2.4 1.7 2-1.5 2.1.8 2.5-2.5.7-.9 2.5-2.5-.6-1.7 2-1.7-2-2.5.6-.9-2.5-2.5-.7.8-2.5-1.5-2.1 1.7-2-.7-2.4 2.3-1.3.1-2.6 2.5-.7.9-2.4 2.5.5L12 2.2z"
                      stroke="#ff4d4f"
                      stroke-width="1.8"
                      stroke-linejoin="round"
                      fill="rgba(255, 77, 79, 0.14)"
                    />
                    <circle cx="9" cy="9" r="1.3" fill="#ff4d4f" />
                    <path d="M8.5 15.5l7-7" stroke="#ff4d4f" stroke-width="1.6" stroke-linecap="round" />
                    <circle cx="15" cy="15" r="1.3" fill="#ff4d4f" />
                  </svg>
                </span>
                </span>
              </button>
            </div>
          </div>
          <div v-if="(quote?.reason && !quote.allowed) || quoteError" class="composer-quote-warning composer-quote" aria-live="polite">
            <span v-if="quote?.reason && !quote.allowed" class="est-warning">
              {{ tr(quote.reason) }}<template v-if="quote.shortfall && Number(quote.shortfall) > 0"> · {{ tr('还差') }} {{ money(quote.shortfall) }}</template>
            </span>
            <span v-else-if="quoteError" class="est-error">
              {{ tr(quoteError) }} · <button type="button" class="est-retry-btn" @click="refreshQuote">{{ tr('重新报价') }}</button>
            </span>
          </div>
        </section>
        <p v-if="loading" class="home-status" role="status">{{ tr('正在读取可用模型…') }}</p>
        <p v-else-if="!models.length" class="home-status" role="status">{{ tr('暂未配置可用模型，请联系管理员。') }}</p>
        <div v-if="error" class="home-error" role="alert">{{ tr(error) }}<AppButton size="sm" @click="load">{{ tr('重新加载') }}</AppButton></div>

        <div class="shortcut-heading"><span>{{ tr('创作工具') }}</span></div>
        <nav class="home-shortcuts" :aria-label="tr('我的创作')">
          <RouterLink to="/create/short-drama"><picture class="shortcut-art" aria-hidden="true"><img src="/home-art/cloud-palace-v1.gif" alt="" width="216" height="144" loading="lazy"></picture><div><strong>{{ tr('短剧制作') }}</strong><p>{{ tr('从剧本到分镜，完整创作一部剧') }}</p></div><ArrowUpRight :size="18" class="shortcut-arrow" /></RouterLink>
          <RouterLink to="/create/remake"><picture class="shortcut-art" aria-hidden="true"><img src="/home-art/rain-street-v1.gif" alt="" width="216" height="144" loading="lazy"></picture><div><strong>{{ tr('重制工坊') }}</strong><p>{{ tr('拆解镜头，用新的风格重新演绎') }}</p></div><ArrowUpRight :size="18" class="shortcut-arrow" /></RouterLink>
          <RouterLink to="/projects"><span class="shortcut-icon is-blue"><FolderOpen :size="23" /></span><div><strong>{{ tr('我的创作') }}</strong><p>{{ tr('管理项目，继续你的故事') }}</p></div><ArrowUpRight :size="18" class="shortcut-arrow" /></RouterLink>
          <RouterLink to="/resource-library"><span class="shortcut-icon is-teal"><Layers :size="23" /></span><div><strong>{{ tr('资源库') }}</strong><p>{{ tr('收藏角色、音色与参考素材') }}</p></div><ArrowUpRight :size="18" class="shortcut-arrow" /></RouterLink>
        </nav>

        <section v-if="recent.length" class="recent-section"><header><h2>{{ tr('最近的片段') }}</h2><span>{{ tr('随时接着创作') }}</span></header><div class="recent-list"><RouterLink v-for="item in recent.slice(0, 3)" :key="item.project_id" :to="{name:'clip-studio',params:{projectId:item.project_id}}"><Film :size="18" /><span>{{ item.name }}</span><small>{{ item.aspect_ratio }}</small><ArrowUpRight :size="15" /></RouterLink></div></section>

        <ShowcaseGallery class="showcase-section" :works="works" :loading="loading" :error="tr(galleryError)" @retry="load" />
      </div>
    </Transition>
  </main>
</template>

<style scoped>
.clip-home { --home-accent: var(--app-accent); position: relative; isolation: isolate; min-height: 100%; padding: 26px clamp(20px,3vw,48px) 48px; color: var(--app-text); background: var(--app-canvas); }
.clip-home :deep(.app-select) { --app-accent: var(--home-accent); }
:global(:root[data-app-theme='dark'] .clip-home .home-atmosphere) { background: none; }
:global(:root[data-app-theme='dark'] .clip-home .shortcut-icon) { color: var(--app-text-secondary); background: var(--app-surface-muted); }
.home-content { max-width: 1140px; margin: 0 auto; }
.home-atmosphere { position: absolute; inset: 0 0 auto; height: 260px; z-index: -1; pointer-events: none; background: radial-gradient(ellipse at 50% 0%,color-mix(in srgb,var(--home-accent) 9%,transparent),transparent 70%); }
.home-heading { text-align: center; margin: 0 auto 20px; }
.home-eyebrow { display: inline-flex; align-items: center; gap: 7px; padding: 0; border: 0; border-radius: 20px; font-size: 11px; color: var(--home-accent); background: transparent; }
.home-heading h1 { margin: 10px 0 8px; font-size: clamp(26px,2.4vw,33px); font-weight: 750; letter-spacing: -.04em; line-height: 1.25; }.home-heading h1 > span { color: var(--home-accent); margin-left: 10px; }
.home-heading p { text-wrap: balance; margin: 0; color: var(--app-text-secondary); font-size: 14px; line-height: 1.7; }
.home-composer { max-width: 1040px; margin: 0 auto; padding: 18px 20px 14px; border: 0; border-radius: 20px; background: var(--app-surface); box-shadow: none; }
.composer-top { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 10px; }
.composer-tabs { position: relative; isolation: isolate; display: inline-grid; grid-template-columns: repeat(2,minmax(0,1fr)); min-width: 0; max-width: 100%; gap: 0; padding: 3px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.composer-tabs::before { position: absolute; z-index: -1; top: 3px; bottom: 3px; left: 3px; width: calc((100% - 6px) / 2); border-radius: 8px; background: var(--home-accent); box-shadow: 0 2px 6px color-mix(in srgb,var(--home-accent) 16%,transparent); content: ''; transform: translateX(0); transition: transform 280ms cubic-bezier(.22,1,.36,1); }
.composer-tabs.is-image::before { transform: translateX(100%); }
.composer-tabs button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 30px; padding: 0 11px; border: 0; border-radius: 8px; color: var(--app-text-secondary); background: transparent; font: inherit; font-size: 12px; font-weight: 600; white-space: nowrap; cursor: pointer; transition: color 160ms ease; }
.composer-tabs button:hover:not([aria-pressed='true']) { color: var(--app-text); }
.composer-tabs button[aria-pressed='true'] { color: var(--app-surface); }
.composer-tabs button:focus-visible { outline: 2px solid var(--home-accent); outline-offset: -3px; }
.composer-tabs button[aria-pressed='true']:focus-visible { outline-color: var(--app-surface); }
.composer-models { display: flex; align-items: center; gap: 12px; min-width: 0; }.models-label { color: var(--app-text-muted); font-size: 12px; }.composer-models :deep(.app-select) { max-width: 300px; }
.composer-frame-interval { display: inline-flex; align-items: center; gap: 4px; min-width: 0; max-width: 100%; padding: 5px 7px; border-radius: 7px; background: var(--app-surface-muted); color: var(--app-text-secondary); font-size: 11px; }.composer-frame-interval input { flex: 1; width: 60px; min-width: 0; padding: 0; border: 0; background: transparent; color: var(--app-text); font: inherit; }.composer-frame-interval input[aria-invalid='true'] { color: var(--app-danger, var(--creation-danger)); }
.prompt-well { border: 0; background: transparent; overflow: visible; }.prompt-well:focus-within { box-shadow: none; }
.prompt-tools { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0; padding: 4px 0; border: 0; }.inspiration-list { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }.inspiration-list > span { color: var(--app-text-muted); font-size: 11px; margin-right: 4px; }.inspiration-list button { display: inline-flex; align-items: center; gap: 4px; padding: 5px 9px; min-height: 30px; border: 0; border-radius: 6px; color: var(--app-text-secondary); background: transparent; font-size: 11px; cursor: pointer; }.inspiration-list button:hover { border-color: var(--home-accent); color: var(--home-accent); }
.upload-reference { flex-shrink: 0; color: var(--app-text-secondary); }
.composer-controls { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 10px; }.composer-settings, .composer-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; }.composer-settings > div { display: flex; align-items: center; gap: 7px; }.composer-settings > div > span { font-size: 11px; color: var(--app-text-muted); }
.generate-action-btn { display: inline-grid; flex: none; grid-template-columns: 17px max-content minmax(0,1fr); align-items: center; gap: 5px; width: 224px; max-width: 100%; height: 42px; padding: 0 12px; border: 0; border-radius: 9999px; background: #5c5bd6; color: #ffffff; font-family: inherit; font-size: 14px; font-weight: 500; cursor: pointer; transition: background-color .16s ease,box-shadow .16s ease; box-shadow: 0 4px 14px rgba(92, 91, 214, 0.28); user-select: none; white-space: nowrap; }
.generate-action-btn:hover:not(:disabled) { background: #6d6ce6; box-shadow: 0 6px 20px rgba(92, 91, 214, 0.38); }
.generate-action-btn:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
.generate-btn-sparkle { color: #ffffff; flex-shrink: 0; margin-right: 2px; }
.generate-btn-label { color: #ffffff; font-weight: 600; font-size: 15px; letter-spacing: 0.02em; }

.generate-btn-price { display: inline-flex; align-items: center; justify-content: center; gap: 3px; min-width: 0; font-variant-numeric: tabular-nums; }
.generate-btn-approx { color: rgba(255, 255, 255, 0.9); font-size: 13px; margin-left: 2px; margin-right: 3px; }
.generate-btn-original { min-width: 0; overflow: hidden; text-overflow: ellipsis; color: rgba(255, 255, 255, 0.52); text-decoration: line-through; font-size: 13px; font-weight: 400; margin-right: 4px; }
.generate-btn-discount { color: #ffffff; font-size: 16px; font-weight: 750; letter-spacing: -0.01em; margin-right: 2px; }
.generate-btn-badge { display: inline-flex; align-items: center; justify-content: center; margin-left: 1px; }
.discount-badge-svg { display: block; }
.composer-quote-warning { display: flex; justify-content: flex-end; margin-top: 8px; font-size: 12px; }
.est-warning { color: #ef4444; font-weight: 500; }
.est-error { color: var(--creation-warning); }
.est-retry-btn { border: 0; background: transparent; color: var(--app-accent); cursor: pointer; padding: 0; font: inherit; }
@media(max-width:600px) {
  .composer-quote-warning { justify-content: flex-start; }
  .generate-action-btn { width: 100%; }
}
.home-shortcuts { max-width: 1040px; display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; margin: 10px auto 30px; }.home-shortcuts a { display: flex; align-items: center; gap: 12px; padding: 12px; min-width: 0; border: 0; border-radius: 14px; color: var(--app-text); background: var(--app-surface); transition: transform .18s,border-color .18s,background .18s; }.home-shortcuts a:hover { transform: translateY(-3px); border-color: var(--home-accent); background: var(--app-surface-hover); }.shortcut-icon { display: grid; place-items: center; width: 38px; height: 42px; flex-shrink: 0; border-radius: 12px; color: var(--home-accent); background: color-mix(in srgb,var(--home-accent) 12%,transparent); }.shortcut-icon.is-rose { color: #b085d9; background: rgb(157 98 204 / 12%); }.shortcut-icon.is-blue { color: #75a4e8; background: rgb(86 146 222 / 12%); }.shortcut-icon.is-teal { color: #65aea9; background: rgb(66 157 150 / 12%); }.home-shortcuts a > div { min-width: 0; }.home-shortcuts strong { font-size: 14px; font-weight: 650; }.home-shortcuts p { margin: 6px 0 0; color: var(--app-text-secondary); font-size: 11px; line-height: 1.65; }.shortcut-arrow { margin-left: auto; flex-shrink: 0; color: var(--app-text-muted); }
.home-status, .home-error { margin: 12px 0; font-size: 12px; color: var(--app-text-secondary); }.home-error { color: var(--creation-danger); }
.recent-section { margin-bottom: 34px; }.recent-section header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }.recent-section h2 { margin: 0; font-size: 16px; }.recent-section header > span { font-size: 11px; color: var(--app-text-muted); }.recent-list { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; }.recent-list a { display: flex; align-items: center; gap: 10px; padding: 14px; border: 0; border-radius: 9px; color: var(--app-text-secondary); background: var(--app-surface); }.recent-list a:hover { border-color: var(--home-accent); }.recent-list a > span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }.recent-list small { font-size: 10px; }
.entry-state { min-height: 70dvh; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }.entry-mark { width: 60px; height: 60px; display: grid; place-items: center; background: var(--app-surface); border: 0; border-radius: 18px; }.entry-state h1 { font-size: 24px; font-weight: 500; }.entry-state p { max-width: 600px; color: var(--app-text-secondary); line-height: 1.8; margin-bottom: 26px; }
.studio-entry-enter-active, .studio-entry-leave-active { transition: opacity 220ms ease, transform 280ms cubic-bezier(.2,.8,.2,1); }.studio-entry-enter-from { opacity: 0; transform: translateY(20px); }.studio-entry-leave-to { opacity: 0; transform: translateY(-14px); }button:focus-visible, a:focus-visible { outline: 2px solid var(--home-accent); outline-offset: 4px; }
@media(max-width:1200px) { .home-shortcuts { gap: 12px; }.home-shortcuts a { padding: 18px 14px; gap: 10px; }.shortcut-arrow { display: none; }.home-shortcuts p { font-size: 10px; }.composer-settings, .composer-actions { gap: 9px; }.composer-settings > div > span { display: none; } }
@media(max-width:900px) { .clip-home { padding: 24px 20px 40px; }.home-shortcuts { grid-template-columns: repeat(2,minmax(0,1fr)); }.home-shortcuts p { font-size: 12px; }.prompt-tools { flex-wrap: wrap; }.inspiration-list > span { display: none; }.recent-list { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media(max-width:600px) { .clip-home { padding: 24px 14px 40px; }.home-heading { margin-bottom: 24px; }.home-heading h1 { font-size: 29px; }.home-heading p { max-width: 260px; margin: auto; font-size: 12px; }.home-composer { padding: 14px; border-radius: 16px; }.composer-top { flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }.composer-tabs { flex: 1; }.composer-tabs button { flex: 1; min-height: 34px; padding: 0 10px; }.composer-models { width: 100%; justify-content: space-between; }.composer-models :deep(.app-select) { max-width: 220px; }.prompt-tools { margin: 0 12px; }.inspiration-list { display: grid; width: 100%; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px; }.inspiration-list button { justify-content: space-between; min-height: 40px; }.composer-controls { gap: 14px; margin-top: 14px; }.composer-settings { width: 100%; justify-content: space-between; }.composer-settings > div { flex: 1; min-width: 0; }.composer-settings :deep(.app-select) { min-width: 0; width: 100%; }.composer-settings :deep(.app-select__trigger) { min-width: 0; }.composer-actions { width: 100%; justify-content: space-between; }.composer-send { padding: 0 14px; }.home-composer :deep(.app-select__trigger) { min-height: 40px; }.composer-hint { text-align: left; font-size: 10px; }.home-shortcuts { gap: 9px; margin: 8px 0 26px; }.home-shortcuts a { flex-wrap: wrap; padding: 12px; gap: 8px; }.shortcut-icon { width: 35px; height: 36px; border-radius: 9px; }.home-shortcuts strong { font-size: 13px; }.home-shortcuts p { font-size: 10px; }.recent-list { grid-template-columns: 1fr; } }
@media(prefers-reduced-motion:reduce) {  .studio-entry-enter-active, .studio-entry-leave-active, .home-shortcuts a, .composer-tabs::before, .composer-tabs button { transition: none; }.home-shortcuts a:hover { transform: none; } }

/* No persistent outlines: separation comes from spacing, quiet fills and artwork. */
.clip-home :deep(.app-select__trigger), .clip-home :deep(.app-select.is-open .app-select__trigger) { border: 0 !important; box-shadow: none !important; background: transparent; }
.clip-home :deep(.app-select__trigger:hover) { background: var(--app-surface-hover); }
:global(.home-select-menu) { border: 0 !important; box-shadow: 0 10px 32px rgb(0 0 0 / 18%); }
.shortcut-heading { max-width: 1040px; margin: 24px auto 0; display: flex; align-items: center; justify-content: space-between; color: var(--app-text-muted); font-size: 11px; }

.shortcut-art { display: block; flex: 0 0 78px; width: 78px; height: 60px; overflow: hidden; border-radius: 8px; }
.shortcut-art img { display: block; width: 100%; height: 100%; object-fit: cover; }
.home-shortcuts a:has(.shortcut-art) { gap: 10px; }
.home-shortcuts a:has(.shortcut-art) .shortcut-arrow { display: none; }
.inspiration-list button:hover { background: var(--app-surface-hover); }
.home-eyebrow { border: 0; border-radius: 0; }
.composer-settings :deep(.app-select) { min-width: 82px; }
@media(max-width:600px) { .shortcut-heading { margin-top: 18px; }.shortcut-art { width: 100%; flex-basis: 100%; height: 76px; }.home-shortcuts a:has(.shortcut-art) { align-content: start; }.home-shortcuts a:not(:has(.shortcut-art)) { align-content: center; }.composer-tabs button { min-height: 34px; }.composer-settings :deep(.app-select) { min-width: 0; } }


</style>
