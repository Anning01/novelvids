<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Clock3, LoaderCircle, Mic2, Scissors, Search, Upload, X } from 'lucide-vue-next'
import { api } from '@/api'
import AudioRangeSlider from '@/components/AudioRangeSlider.vue'
import { trimLocalAudioFile } from '@/shared/audioTrim'
import type { AudioReference } from '@/types'

const props = defineProps<{
  open: boolean
  selectedId?: number | null
  startInUpload?: boolean
  novelId?: number
}>()
const emit = defineEmits<{ close: []; choose: [item: AudioReference] }>()
const items = ref<AudioReference[]>([])
const page = ref(1)
const pages = ref(1)
const search = ref('')
const loading = ref(false)
const error = ref('')
const uploadOpen = ref(false)
const uploadFile = ref<File | null>(null)
const uploadName = ref('')
const uploadGender = ref('未设置')
const uploading = ref(false)
const uploadPreviewUrl = ref('')
const uploadDuration = ref(0)
const uploadStart = ref(0)
const uploadEnd = ref(0)
const trimTarget = ref<AudioReference | null>(null)
const trimStart = ref(0)
const trimEnd = ref(0)
const trimming = ref(false)
let requestId = 0

const uploadClipDuration = computed(() => uploadEnd.value - uploadStart.value)
const uploadClipValid = computed(() => !uploadDuration.value || (
  uploadStart.value >= 0
  && uploadEnd.value <= uploadDuration.value + 0.05
  && uploadClipDuration.value >= 1
  && uploadClipDuration.value <= 30
))
const trimClipDuration = computed(() => trimEnd.value - trimStart.value)
const trimClipValid = computed(() => Boolean(trimTarget.value?.duration)
  && trimStart.value >= 0
  && trimEnd.value <= Number(trimTarget.value?.duration) + 0.05
  && trimClipDuration.value >= 1
  && trimClipDuration.value <= 30)

function formatDuration(value: number | null | undefined) {
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds <= 0) return '--:--'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds - minutes * 60
  const formatted = Math.abs(remainder - Math.round(remainder)) < 0.05
    ? String(Math.round(remainder)).padStart(2, '0')
    : remainder.toFixed(1).padStart(4, '0')
  return `${minutes}:${formatted}`
}

function roundedTime(value: number) {
  return Number(value.toFixed(1))
}

async function load(reset = false) {
  if (loading.value && !reset) return
  const currentRequestId = ++requestId
  if (reset) { page.value = 1; items.value = [] }
  loading.value = true
  error.value = ''
  try {
    const response = await api.audioReferences(page.value, search.value.trim(), {}, props.novelId)
    if (currentRequestId !== requestId) return
    items.value = reset ? response.data.items : [...items.value, ...response.data.items]
    pages.value = response.data.pagination.pages
  } catch (reason) {
    if (currentRequestId === requestId) error.value = reason instanceof Error ? reason.message : '音频库加载失败'
  } finally {
    if (currentRequestId === requestId) loading.value = false
  }
}

function releaseUploadPreview() {
  if (uploadPreviewUrl.value) URL.revokeObjectURL(uploadPreviewUrl.value)
  uploadPreviewUrl.value = ''
}

function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  releaseUploadPreview()
  if (file && file.size > 200 * 1024 * 1024) {
    uploadFile.value = null
    error.value = '原音频不能超过 200MB'
    return
  }
  error.value = ''
  uploadFile.value = file
  uploadDuration.value = 0
  uploadStart.value = 0
  uploadEnd.value = 0
  if (file) {
    uploadPreviewUrl.value = URL.createObjectURL(file)
    if (!uploadName.value) uploadName.value = file.name.replace(/\.(mp3|wav)$/i, '')
  }
}

function captureUploadDuration(duration: number) {
  if (!Number.isFinite(duration) || duration <= 0) return
  uploadDuration.value = roundedTime(duration)
  uploadStart.value = 0
  uploadEnd.value = roundedTime(Math.min(duration, 30))
}

function captureItemDuration(item: AudioReference, event: Event) {
  const duration = (event.currentTarget as HTMLAudioElement).duration
  if (!Number.isFinite(duration) || duration <= 0 || item.duration) return
  item.duration = roundedTime(duration)
}

async function uploadReference() {
  if (!uploadFile.value || !uploadName.value.trim() || uploading.value) return
  uploading.value = true
  error.value = ''
  try {
    let file = uploadFile.value
    const needsTrim = uploadDuration.value > 0 && (
      uploadDuration.value > 30
      || uploadStart.value > 0.01
      || uploadEnd.value < uploadDuration.value - 0.05
    )
    if (needsTrim) file = await trimLocalAudioFile(file, uploadStart.value, uploadEnd.value)
    const response = await api.uploadAudioReference(
      file,
      uploadName.value.trim(),
      uploadGender.value,
      props.novelId,
    )
    items.value = [response.data, ...items.value.filter(item => item.id !== response.data.id)]
    uploadOpen.value = false
    emit('choose', response.data)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '参考音频上传失败'
  } finally {
    uploading.value = false
  }
}

function resetUpload() {
  releaseUploadPreview()
  uploadOpen.value = false
  uploadFile.value = null
  uploadName.value = ''
  uploadGender.value = '未设置'
  uploadDuration.value = 0
  uploadStart.value = 0
  uploadEnd.value = 0
}

function toggleUpload() {
  if (uploadOpen.value) resetUpload()
  else uploadOpen.value = true
}

function openTrim(item: AudioReference) {
  const duration = Number(item.duration)
  if (!Number.isFinite(duration) || duration <= 0) {
    error.value = '音频时长还在读取，请稍后重试'
    return
  }
  trimTarget.value = item
  trimStart.value = 0
  trimEnd.value = roundedTime(Math.min(duration, 30))
  uploadOpen.value = false
  error.value = ''
}

function closeTrim() {
  if (!trimming.value) trimTarget.value = null
}

async function createTrimmedReference() {
  if (!trimTarget.value || !trimClipValid.value || trimming.value) return
  trimming.value = true
  error.value = ''
  try {
    const response = await api.trimAudioReference(
      trimTarget.value.id,
      roundedTime(trimStart.value),
      roundedTime(trimEnd.value),
      props.novelId,
    )
    items.value = [response.data, ...items.value.filter(item => item.id !== response.data.id)]
    trimTarget.value = null
    emit('choose', response.data)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '音频裁剪失败'
  } finally {
    trimming.value = false
  }
}

watch(() => props.open, value => {
  if (value) {
    uploadOpen.value = Boolean(props.startInUpload)
    void load(true)
  }
  else {
    requestId += 1
    loading.value = false
    resetUpload()
  }
}, { immediate: true })

onBeforeUnmount(releaseUploadPreview)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="audio-picker-backdrop" @mousedown.self="emit('close')">
      <section class="audio-picker" role="dialog" aria-modal="true" aria-label="选择音色" @keydown.esc.stop="emit('close')">
        <header>
          <div><span><Mic2 :size="18" /></span><div><h2>选择音色</h2><p>系统音色和上传音频都会在视频生成时保持角色声音一致。</p></div></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭" @click="emit('close')"><X :size="18" /></AppButton>
        </header>
        <div class="audio-picker__tools">
          <label><Search :size="15" /><input v-model="search" placeholder="搜索音色名称或性别" @keyup.enter="load(true)" /></label>
          <AppButton type="button" variant="secondary" size="sm" @click="toggleUpload"><Upload :size="14" />上传音频</AppButton>
        </div>
        <form v-if="uploadOpen" class="audio-picker__upload" @submit.prevent="uploadReference">
          <label><span>音色名称</span><input v-model="uploadName" maxlength="100" placeholder="例如：羽宁参考音色" /></label>
          <label><span>性别</span><select v-model="uploadGender"><option>未设置</option><option>男</option><option>女</option><option>其他</option></select></label>
          <label class="audio-picker__file"><input type="file" accept="audio/mpeg,audio/wav,.mp3,.wav" @change="chooseFile" /><span>{{ uploadFile?.name || '选择 MP3 / WAV，长音频可在上传前裁剪' }}</span></label>
          <section v-if="uploadPreviewUrl" class="audio-picker__clip-editor">
            <header><div><Scissors :size="14" /><strong>上传前裁剪</strong></div><span><Clock3 :size="12" />原始 {{ formatDuration(uploadDuration) }} · 已选 {{ uploadClipDuration > 0 ? `${uploadClipDuration.toFixed(1)}s` : '--' }}</span></header>
            <AudioRangeSlider
              v-model:start="uploadStart"
              v-model:end="uploadEnd"
              :src="uploadPreviewUrl"
              :duration="uploadDuration"
              @loaded-duration="captureUploadDuration"
            />
            <p v-if="uploadDuration > 30">原音频超过 30 秒，上传时会自动生成选中片段的 WAV 副本。</p>
            <p v-else-if="!uploadClipValid">裁剪片段需为 1-30 秒，且不能超出原音频时长。</p>
          </section>
          <AppButton type="submit" variant="primary" size="sm" :loading="uploading" :disabled="!uploadFile || !uploadName.trim() || !uploadClipValid">上传并选择</AppButton>
        </form>
        <section v-if="trimTarget" class="audio-picker__existing-trim">
          <header><div><Scissors :size="15" /><span><strong>裁剪音色副本</strong><small>{{ trimTarget.nickname }} · 原始 {{ formatDuration(trimTarget.duration) }}</small></span></div><AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭裁剪" @click="closeTrim"><X :size="15" /></AppButton></header>
          <AudioRangeSlider
            v-model:start="trimStart"
            v-model:end="trimEnd"
            :src="trimTarget.audio_url"
            :duration="trimTarget.duration || 0"
          />
          <footer><span>会创建新音色，不修改原音频及已有角色引用。</span><AppButton type="button" variant="primary" size="sm" :loading="trimming" :disabled="!trimClipValid" @click="createTrimmedReference">生成副本并选择</AppButton></footer>
        </section>
        <p v-if="error" class="audio-picker__error" role="alert">{{ error }}</p>
        <div
          v-if="items.length"
          class="audio-picker__list"
          tabindex="0"
          aria-label="音色列表，可滚动浏览"
          :aria-busy="loading"
        >
          <article v-for="item in items" :key="item.id" :class="{ 'is-selected': selectedId === item.id }">
            <button type="button" class="audio-picker__item-main" @click="emit('choose', item)">
              <img v-if="item.avatar_url" :src="item.avatar_url" alt="" />
              <span v-else class="audio-picker__avatar"><Mic2 :size="18" /></span>
              <span><strong>{{ item.nickname }}</strong><small>{{ item.gender }} · {{ item.source === 'upload' ? '用户上传' : '系统音色' }} · {{ formatDuration(item.duration) }}</small></span>
            </button>
            <div class="audio-picker__item-player">
              <audio :src="item.audio_url" controls preload="metadata" @loadedmetadata="captureItemDuration(item, $event)" />
              <AppButton v-if="item.source === 'upload'" type="button" variant="ghost" size="sm" icon-only :aria-label="`裁剪${item.nickname}`" title="裁剪并生成新音色" @click="openTrim(item)"><Scissors :size="15" /></AppButton>
            </div>
          </article>
        </div>
        <div v-if="loading && !items.length" class="audio-picker__state"><LoaderCircle class="is-spinning" :size="21" />正在加载音频库…</div>
        <div v-else-if="!items.length" class="audio-picker__state">没有匹配的音色</div>
        <footer><span>第 {{ page }} / {{ pages || 1 }} 页</span><AppButton v-if="page < pages" type="button" variant="ghost" size="sm" :loading="loading" @click="page += 1; load()">加载更多</AppButton></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.audio-picker-backdrop { position: fixed; z-index: 1500; inset: 0; display: grid; place-items: center; padding: 24px; background: rgb(12 15 30 / 72%); }
.audio-picker { isolation: isolate; display: flex; width: min(760px, 100%); max-height: min(760px, calc(100vh - 48px)); flex-direction: column; overflow: hidden; border: 1px solid var(--app-border); border-radius: 18px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 28px 80px rgb(0 0 0 / 28%); }
.audio-picker > header { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px; border-bottom: 1px solid var(--app-border); }
.audio-picker > header > div { display: flex; align-items: center; gap: 11px; }
.audio-picker > header > div > span { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 11px; color: var(--app-accent); background: var(--app-accent-soft); }
.audio-picker h2, .audio-picker p { margin: 0; }
.audio-picker h2 { font-size: 15px; }.audio-picker header p { margin-top: 3px; color: var(--app-text-muted); font-size: 10px; }
.audio-picker__tools { display: flex; gap: 10px; padding: 14px 20px; }.audio-picker__tools > label { display: flex; min-height: 36px; flex: 1; align-items: center; gap: 7px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 9px; }.audio-picker__tools input { width: 100%; border: 0; outline: 0; color: inherit; background: transparent; }
.audio-picker__upload { display: grid; grid-template-columns: 1fr 120px; gap: 10px; margin: 0 20px 12px; padding: 13px; border: 1px solid var(--app-accent-border, var(--app-border-strong)); border-radius: 11px; background: var(--app-accent-soft); }.audio-picker__upload label { display: grid; gap: 5px; color: var(--app-text-secondary); font-size: 9px; }.audio-picker__upload input, .audio-picker__upload select { min-height: 34px; padding: 0 9px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text); background: var(--app-surface); }.audio-picker__file { grid-column: 1 / -1; }.audio-picker__file input { position: absolute; width: 1px; opacity: 0; }.audio-picker__file span { display: flex; min-height: 36px; align-items: center; padding: 0 10px; border: 1px dashed var(--app-border-strong); border-radius: 8px; background: var(--app-surface); cursor: pointer; }
.audio-picker__clip-editor { display: grid; grid-column: 1 / -1; gap: 9px; padding: 11px; border: 1px solid color-mix(in srgb,var(--app-accent) 18%,var(--app-border)); border-radius: 10px; background: var(--app-surface); }.audio-picker__clip-editor > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.audio-picker__clip-editor > header > div,.audio-picker__clip-editor > header > span { display: flex; align-items: center; gap: 6px; }.audio-picker__clip-editor > header > div { color: var(--app-text); font-size: 10px; }.audio-picker__clip-editor > header > span { color: var(--app-text-muted); font-size: 9px; }.audio-picker__clip-editor > audio { width: 100%; height: 32px; }.audio-picker__clip-editor > p { color: var(--app-text-muted); font-size: 9px; line-height: 1.5; }
.audio-picker__existing-trim { display: grid; gap: 10px; margin: 0 20px 12px; padding: 13px; border: 1px solid color-mix(in srgb,var(--app-accent) 24%,var(--app-border)); border-radius: 12px; background: color-mix(in srgb,var(--app-accent) 4%,var(--app-surface)); }.audio-picker__existing-trim > header,.audio-picker__existing-trim > footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.audio-picker__existing-trim > header > div { display: flex; min-width: 0; align-items: center; gap: 8px; color: var(--app-accent); }.audio-picker__existing-trim > header > div > span { display: grid; min-width: 0; gap: 2px; }.audio-picker__existing-trim strong { color: var(--app-text); font-size: 11px; }.audio-picker__existing-trim small,.audio-picker__existing-trim > footer > span { color: var(--app-text-muted); font-size: 9px; }.audio-picker__existing-trim > audio { width: 100%; height: 32px; }.audio-picker__existing-trim .audio-picker__clip-inputs input { min-height: 34px; padding: 0 26px 0 9px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text); background: var(--app-surface); }
.audio-picker__error { margin: 0 20px 10px !important; color: #d34f5d; font-size: 10px; }
.audio-picker__list { contain: layout paint; display: grid; min-height: 0; flex: 1 1 auto; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; gap: 8px; padding: 4px 20px 16px; outline: 0; background: var(--app-surface); }.audio-picker__list:focus-visible { box-shadow: inset 0 0 0 2px var(--app-accent); }.audio-picker__list > article { display: grid; grid-template-columns: minmax(170px,1fr) minmax(220px,300px); align-items: center; gap: 10px; padding: 8px; border: 1px solid var(--app-border); border-radius: 11px; background: var(--app-surface); }.audio-picker__list > article:hover,.audio-picker__list > article.is-selected { border-color: var(--app-accent); background: var(--app-accent-soft); }.audio-picker__item-main { display: grid; min-width: 0; grid-template-columns: 44px minmax(0,1fr); align-items: center; gap: 11px; padding: 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }.audio-picker__list img, .audio-picker__avatar { width: 44px; height: 44px; border-radius: 9px; object-fit: cover; }.audio-picker__avatar { display: grid; place-items: center; color: var(--app-accent); background: var(--app-surface-muted); }.audio-picker__item-main > span:last-child { display: grid; min-width: 0; gap: 4px; }.audio-picker__list strong,.audio-picker__list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.audio-picker__list strong { font-size: 12px; }.audio-picker__list small { color: var(--app-text-muted); font-size: 9px; }.audio-picker__item-player { display: grid; min-width: 0; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 4px; }.audio-picker__item-player audio { width: 100%; min-width: 0; height: 32px; }
.audio-picker__state { display: flex; min-height: 0; flex: 1 1 220px; align-items: center; justify-content: center; gap: 8px; color: var(--app-text-muted); font-size: 11px; }.audio-picker > footer { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; padding: 10px 20px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); font-size: 9px; }.is-spinning { animation: spin .9s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) { .audio-picker__list > article { grid-template-columns: 1fr; }.audio-picker__upload { grid-template-columns: 1fr; }.audio-picker__file,.audio-picker__clip-editor { grid-column: auto; }.audio-picker__existing-trim > footer { align-items: stretch; flex-direction: column; } }
</style>
