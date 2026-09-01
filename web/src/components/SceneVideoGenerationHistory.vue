<script setup lang="ts">
import { computed, ref } from 'vue'
import { LoaderCircle, RotateCcw, Sparkles, TriangleAlert, Video as VideoIcon, X } from 'lucide-vue-next'
import { formatVideoGenerationError } from '@/shared/videoGenerationError'
import { videoPosterUrl } from '@/shared/mediaDerivatives'
import { TaskStatusEnum } from '@/types'
import type { Video } from '@/types'

const props = defineProps<{
  records: Video[]
  currentId?: number
  busy?: boolean
}>()

const emit = defineEmits<{
  refresh: []
  select: [record: Video]
  retry: []
}>()

const errorRecord = ref<Video | null>(null)

const sortedRecords = computed(() => [...props.records].sort((left, right) => right.id - left.id))

function errorMessage(record: Video) {
  const metadata = record.metadata || {}
  for (const key of ['error_message', 'error', 'message', 'detail']) {
    const value = metadata[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return record.status === TaskStatusEnum.CANCELLED ? '生成任务已取消' : '视频生成失败'
}

function displayTime(value: string) {
  if (!value) return ''
  const normalized = value.replace('T', ' ')
  return normalized.length >= 16 ? normalized.slice(5, 16) : normalized
}

function isSelectable(record: Video) {
  return record.status === TaskStatusEnum.COMPLETED && Boolean(record.url)
}

function isRunning(record: Video) {
  return [TaskStatusEnum.PENDING, TaskStatusEnum.PROCESSING, TaskStatusEnum.QUEUED].includes(record.status)
}

function showError(record: Video) {
  errorRecord.value = record
}

function isFailed(record: Video) {
  return record.status === TaskStatusEnum.FAILED || record.status === TaskStatusEnum.CANCELLED
}

function selectVersion(record: Video) {
  if (isFailed(record)) {
    showError(record)
    return
  }
  if (isSelectable(record) && record.id !== props.currentId) emit('select', record)
}

function versionLabel(record: Video, index: number) {
  if (isFailed(record)) return '生成失败'
  if (record.id === props.currentId) return '当前分镜'
  if (isRunning(record)) return '生成中'
  return `版本 ${sortedRecords.value.length - index}`
}

function closeError() {
  errorRecord.value = null
}

function retryFailedRecord() {
  closeError()
  emit('retry')
}
</script>

<template>
  <section class="video-history" aria-label="视频生成版本">
    <div v-if="sortedRecords.length" class="video-history__rail">
      <button
        v-for="(record, index) in sortedRecords"
        :key="record.id"
        type="button"
        class="video-history__version"
        :class="{
          'is-current': record.id === currentId,
          'is-failed': isFailed(record),
          'is-running': isRunning(record),
        }"
        :disabled="(record.id === currentId && !isFailed(record)) || (!isSelectable(record) && !isFailed(record))"
        :aria-label="isFailed(record) ? `查看视频版本 ${record.id} 的失败原因` : record.id === currentId ? '当前分镜视频' : `切换到视频版本 ${record.id}`"
        :title="`${versionLabel(record, index)} · ${displayTime(record.created_at)}`"
        @click="selectVersion(record)"
      >
        <span class="video-history__thumb">
          <img
            v-if="videoPosterUrl(record, 'thumbnail')"
            :src="videoPosterUrl(record, 'thumbnail')"
            alt=""
            loading="lazy"
            decoding="async"
          >
          <LoaderCircle v-else-if="isRunning(record)" :size="18" class="is-spinning" />
          <TriangleAlert v-else-if="isFailed(record)" :size="18" />
          <VideoIcon v-else :size="18" />
        </span>
        <span class="video-history__label">
          <Sparkles v-if="record.id === currentId" :size="10" />
          {{ versionLabel(record, index) }}
        </span>
      </button>
    </div>
    <p v-else class="video-history__empty"><VideoIcon :size="15" />生成后会在这里保留视频版本</p>

    <Teleport to="body">
      <div v-if="errorRecord" class="video-history-error-backdrop" @click.self="closeError">
        <section class="video-history-error-dialog" role="dialog" aria-modal="true" aria-labelledby="video-history-error-title" @keydown.esc="closeError">
          <header>
            <span><TriangleAlert :size="18" /></span>
            <div>
              <strong id="video-history-error-title">{{ formatVideoGenerationError(errorMessage(errorRecord)).title }}</strong>
              <small>视频版本 {{ errorRecord.id }} · {{ displayTime(errorRecord.created_at) }}</small>
            </div>
            <button type="button" aria-label="关闭失败原因" @click="closeError"><X :size="16" /></button>
          </header>
          <p>{{ formatVideoGenerationError(errorMessage(errorRecord)).message }}</p>
          <p class="video-history-error-dialog__suggestion">{{ formatVideoGenerationError(errorMessage(errorRecord)).suggestion }}</p>
          <footer>
            <button type="button" class="video-history-error-dialog__cancel" @click="closeError">关闭</button>
            <button type="button" class="video-history-error-dialog__retry" :disabled="busy" @click="retryFailedRecord"><RotateCcw :size="13" />重新生成</button>
          </footer>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.video-history { min-width: 0; min-height: 76px; padding: 8px 12px 10px; border-top: 1px solid var(--app-border,#e7e9f0); background: var(--app-surface,#fff); }
.video-history__rail { display: flex; min-width: 0; align-items: flex-start; justify-content: center; gap: 8px; overflow-x: auto; overscroll-behavior-x: contain; scrollbar-width: none; }
.video-history__rail::-webkit-scrollbar { display: none; }
.video-history__version { display: grid; flex: 0 0 72px; width: 72px; min-width: 0; justify-items: center; padding: 0; border: 0; color: var(--app-text-secondary,#5f6574); background: transparent; cursor: pointer; }
.video-history__version:disabled { cursor: default; opacity: 1; }
.video-history__version:focus-visible { outline: 2px solid color-mix(in srgb,var(--app-accent,#5b5cf6) 38%,transparent); outline-offset: 3px; border-radius: 8px; }
.video-history__thumb { display: grid; width: 54px; height: 48px; overflow: hidden; place-items: center; border: 1px solid var(--app-border,#dfe3eb); border-radius: 6px; color: #9298a8; background: var(--app-fill-subtle,#eef0f5); transition: border-color .16s ease,box-shadow .16s ease; }
.video-history__version:not(:disabled):hover .video-history__thumb { border-color: color-mix(in srgb,var(--app-accent,#5b5cf6) 55%,var(--app-border,#dfe3eb)); box-shadow: 0 2px 8px rgb(24 29 44 / 10%); }
.video-history__version.is-current .video-history__thumb { border-color: var(--app-accent,#5b5cf6); box-shadow: 0 0 0 2px color-mix(in srgb,var(--app-accent,#5b5cf6) 14%,transparent); }
.video-history__version.is-failed .video-history__thumb { color: #df6074; border-color: rgb(226 91 111 / 22%); background: rgb(226 91 111 / 7%); }
.video-history__thumb img { width: 100%; height: 100%; object-fit: cover; }
.video-history__label { display: inline-flex; max-width: 72px; min-height: 18px; align-items: center; justify-content: center; gap: 2px; margin-top: -2px; padding: 3px 6px; overflow: hidden; border-radius: 0 0 6px 6px; color: var(--app-text-muted,#818796); background: var(--app-fill-subtle,#f1f2f6); font-size: 8px; font-weight: 650; line-height: 1; text-overflow: ellipsis; white-space: nowrap; }
.video-history__version.is-current .video-history__label { color: #fff; background: var(--app-accent,#5b5cf6); }
.video-history__version.is-failed .video-history__label { color: #cf5265; background: rgb(226 91 111 / 10%); }
.video-history__version.is-running .video-history__label { color: var(--app-accent,#5b5cf6); }
.video-history__empty { display: flex; min-height: 56px; align-items: center; justify-content: center; gap: 5px; margin: 0; color: var(--app-text-muted,#a0a5b2); font-size: 9px; }
.is-spinning { animation: video-history-spin 1s linear infinite; }
@keyframes video-history-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .is-spinning { animation-duration: 1.8s; } }
</style>

<style>
.video-history-error-backdrop { position: fixed; z-index: 1800; inset: 0; display: grid; padding: 20px; place-items: center; background: rgb(24 27 36 / 32%); backdrop-filter: blur(2px); }
.video-history-error-dialog { width: min(400px,100%); overflow: hidden; color: var(--app-text,#313542); border: 1px solid var(--app-border,#e3e6ee); border-radius: 13px; background: var(--app-surface,#fff); box-shadow: 0 18px 55px rgb(23 28 43 / 20%); }
.video-history-error-dialog > header { display: grid; grid-template-columns: 36px minmax(0,1fr) 28px; gap: 10px; align-items: center; padding: 14px 15px 11px; }
.video-history-error-dialog > header > span { display: grid; width: 36px; height: 36px; place-items: center; color: #d65367; border-radius: 9px; background: rgb(222 82 104 / 9%); }
.video-history-error-dialog > header div { display: grid; min-width: 0; gap: 2px; }
.video-history-error-dialog > header strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.video-history-error-dialog > header small { color: var(--app-text-muted,#9298a7); font-size: 10px; }
.video-history-error-dialog > header button { display: grid; width: 28px; height: 28px; padding: 0; place-items: center; border: 0; border-radius: 7px; color: var(--app-text-muted,#858b99); background: transparent; cursor: pointer; }
.video-history-error-dialog > header button:hover { color: var(--app-text,#313542); background: var(--app-fill-subtle,#f3f4f8); }
.video-history-error-dialog > p { margin: 0; padding: 0 15px; color: var(--app-text-secondary,#5f6574); font-size: 11px; line-height: 1.65; }
.video-history-error-dialog > .video-history-error-dialog__suggestion { margin-top: 7px; color: #bd4d60; }
.video-history-error-dialog > footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 13px; padding: 11px 15px; border-top: 1px solid var(--app-border,#eceef3); background: var(--app-fill-subtle,#fafbfc); }
.video-history-error-dialog > footer button { display: inline-flex; min-height: 32px; align-items: center; justify-content: center; gap: 5px; padding: 0 12px; border: 0; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer; }
.video-history-error-dialog__cancel { color: var(--app-text-secondary,#5d6371); background: #fff; box-shadow: inset 0 0 0 1px var(--app-border,#e1e4eb); }
.video-history-error-dialog__retry { color: #fff; background: var(--app-accent,#5b5cf6); }
.video-history-error-dialog__retry:disabled { cursor: wait; opacity: .55; }
@media (prefers-color-scheme: dark) {
  .video-history-error-dialog__cancel { background: var(--app-surface,#252834); }
}
</style>
