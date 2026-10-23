<script setup lang="ts">
import { tr } from '@/i18n'

import { computed, ref, watch } from 'vue'
import { Film, ImageIcon, LoaderCircle, Plus, X } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { libraryApi } from '@/features/resource-library/api'
import type { VideoGenerationModel, VideoReferenceMedia } from '@/types'
import ResourceLibraryPicker from '@/features/resource-library/ResourceLibraryPicker.vue'
import SaveVideoToLibrary from '@/features/resource-library/SaveVideoToLibrary.vue'
import ImageLightbox from './ImageLightbox.vue'
import { fallbackImage } from '@/shared/mediaFallback'

const props = defineProps<{
  sceneId?: number
  model: VideoGenerationModel | null
  media: VideoReferenceMedia[]
  assetImageCount: number
  highlightedMediaIndex?: number
  disabled?: boolean
  uploading?: boolean
}>()

const emit = defineEmits<{
  upload: [files: File[]]
  chooseLibrary: [references: VideoReferenceMedia[]]
  remove: [index: number]
}>()

const libraryOpen = ref(false)
const libraryStates = ref<Record<number, { url: string; failed: boolean }>>({})
let librarySequence = 0
watch(() => props.media.map(item => item.library_resource_id).filter(Boolean).join(','), async () => {
  const request = ++librarySequence
  const ids = [...new Set(props.media.flatMap(item => item.library_resource_id ? [item.library_resource_id] : []))]
  const states = await Promise.all(ids.map(async id => {
    try { const response = await libraryApi.get(id); return [id, { url: response.data.url, failed: false }] as const }
    catch { return [id, { url: '', failed: true }] as const }
  }))
  if (request === librarySequence) libraryStates.value = Object.fromEntries(states)
}, { immediate: true })
function referenceUrl(item: VideoReferenceMedia) { return mediaUrl((item.library_resource_id && libraryStates.value[item.library_resource_id]?.url) || item.url) }
function unavailableReference(item: VideoReferenceMedia) { return Boolean(item.library_resource_id && libraryStates.value[item.library_resource_id]?.failed) }
const input = ref<HTMLInputElement | null>(null)
const previewImage = ref<VideoReferenceMedia | null>(null)
const uploadedImages = computed(() => props.media.filter(item => item.type === 'image').length)
const uploadedVideos = computed(() => props.media.filter(item => item.type === 'video').length)
const totalVideoDuration = computed(() => props.media
  .filter(item => item.type === 'video')
  .reduce((total, item) => total + (item.duration || 0), 0))
const accept = computed(() => {
  const capabilities = props.model?.capabilities
  if (!capabilities) return 'image/*,video/mp4,video/quicktime'
  return [
    ...capabilities.reference_image_formats.map(format => `.${format}`),
    ...capabilities.reference_video_formats.map(format => `.${format}`),
  ].join(',')
})
const unavailable = computed(() => props.disabled || props.uploading || !props.model)

function chooseFiles() {
  if (!unavailable.value) input.value?.click()
}

function handleFiles(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  if (files.length) emit('upload', files)
}

function showFirstFrame(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  if (!Number.isFinite(video.duration) || video.duration <= 0) return
  video.currentTime = Math.min(0.01, video.duration)
}

function openImagePreview(item: VideoReferenceMedia) {
  if (item.type === 'image') previewImage.value = item
}

function closeImagePreview() {
  previewImage.value = null
}
</script>

<template>
  <section class="reference-media-bar" :class="{ 'is-disabled': disabled }">
    <input ref="input" type="file" multiple :accept="accept" @change="handleFiles" />
    <button
      type="button"
      class="reference-add"
      :disabled="unavailable"
      :title="disabled ? tr('首尾帧模式不能同时使用参考素材') : tr('上传参考图片或视频')"
      :aria-label="tr('上传参考图片或视频')"
      @click="chooseFiles"
    >
      <LoaderCircle v-if="uploading" :size="16" />
      <Plus v-else :size="16" />
    </button>
    <AppButton size="sm" :disabled="unavailable || !model?.capabilities.max_reference_videos" @click="libraryOpen = true">{{ tr('资源库') }}</AppButton>
    <ResourceLibraryPicker v-if="libraryOpen" :open="libraryOpen" :model-config-id="model?.config_id" :max-selection="Math.max(0, (model?.capabilities.max_reference_videos || 0) - uploadedVideos)" @close="libraryOpen = false" @choose="(_items, references) => { emit('chooseLibrary', references); libraryOpen = false }" />
    <div v-if="media.length" class="reference-list" :aria-label="tr('已上传参考素材')">
      <article
        v-for="(item, index) in media"
        :key="`${item.type}:${item.url}`"
        class="reference-item"
        :class="{ 'is-reference-highlighted': highlightedMediaIndex === index }"
        :data-reference-media-index="index"
      >
        <button
          v-if="item.type === 'image'"
          type="button"
          class="reference-image-preview"
          :aria-label="tr('放大查看 {p0}', { p0: item.name || '参考图片' })"
          :title="tr('点击放大')"
          @click="openImagePreview(item)"
        >
          <ImageIcon :size="16" aria-hidden="true" />
          <img :src="item.url" :alt="item.name || tr('参考图片')" @error="fallbackImage($event)" />
        </button>
        <video
          v-else-if="!unavailableReference(item)"
          class="reference-video"
          :src="referenceUrl(item)"
          :aria-label="item.name || tr('参考视频第一帧')"
          preload="metadata"
          muted
          playsinline
          @loadedmetadata="showFirstFrame"
        />
        <span v-else role="alert" :title="tr('资源视频已删除或不可用，请移除后重新选择')">{{ tr('已失效') }}</span>
        <span class="reference-name">
          <strong>{{ item.name || (item.type === 'image' ? tr('参考图片') : tr('参考视频')) }}</strong>
        </span>
        <button type="button" class="reference-remove" :aria-label="tr('移除 {p0}', { p0: item.name || '参考素材' })" :title="tr('移除')" @click="emit('remove', index)"><X :size="10" /></button>
      </article>
    </div>
    <div class="reference-summary">
      <ImageIcon :size="13" />
      <span>{{ tr('图片') }} {{ assetImageCount + uploadedImages }}/{{ model?.capabilities.max_reference_images || 0 }}</span>
      <i>·</i>
      <Film :size="13" />
      <span>{{ tr('视频') }} {{ uploadedVideos }}/{{ model?.capabilities.max_reference_videos || 0 }}</span>
      <small v-if="uploadedVideos">{{ totalVideoDuration.toFixed(1) }}/{{ model?.capabilities.reference_video_total_duration_max || 0 }}s</small>
      <small v-if="assetImageCount">{{ tr('资产图已计入') }}</small>
      <small v-else-if="!model">{{ tr('请先启用视频模型') }}</small>
      <small v-else>{{ tr('支持图片与 MP4/MOV') }}</small>
    </div>
    <div v-if="sceneId" class="reference-save-actions"><span v-for="item in media.filter(value => value.type === 'video' && !value.library_resource_id)" :key="item.url"><small>{{ item.name || tr('参考视频') }}</small><SaveVideoToLibrary :source="{ source: 'scene', source_id: sceneId, media_url: item.url, name: item.name || tr('参考视频') }" /></span></div>
    <ImageLightbox
      :open="Boolean(previewImage)"
      :src="previewImage?.url || ''"
      :alt="previewImage?.name || tr('参考图片')"
      @close="closeImagePreview"
    />
  </section>
</template>

<style scoped>
.reference-save-actions { display:flex; gap:8px; flex-wrap:wrap; flex-basis:100%; }.reference-save-actions>span { display:flex; align-items:center; gap:6px; }
.reference-media-bar { display: flex; flex-wrap:wrap; min-width: 0; align-items: center; gap: 8px; padding: 0 16px 8px; color: var(--app-text-muted); font-size: 9px; }
.reference-media-bar > input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.reference-add { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 0; border-radius: 9px; color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 18%,var(--app-border)); cursor: pointer; transition: transform .16s ease, background .16s ease; }
.reference-add:hover:not(:disabled) { background: color-mix(in srgb,var(--app-accent) 16%,var(--app-surface)); transform: translateY(-1px); }
.reference-add:disabled { color: var(--app-text-muted); background: var(--app-surface-muted); cursor: not-allowed; }
.reference-add svg.is-spinning, .reference-add svg { animation: none; }
.reference-add svg:first-child:last-child:is(.lucide-loader-circle) { animation: spin 1s linear infinite; }
.reference-list { display: flex; min-width: 0; max-width: 56%; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.reference-list::-webkit-scrollbar { display: none; }
.reference-item { position: relative; display: grid; width: 58px; height: 34px; flex: 0 0 58px; overflow: hidden; place-items: center; border-radius: 8px; color: var(--app-text-muted); background: var(--app-fill-subtle); box-shadow: inset 0 0 0 1px var(--app-border); }
.reference-item.is-reference-highlighted { box-shadow: inset 0 0 0 2px #ff7a8c, 0 0 0 3px rgb(255 122 140 / 24%); animation: reference-pulse .7s ease 2; }
.reference-image-preview { position: relative; display: grid; width: 100%; height: 100%; padding: 0; overflow: hidden; place-items: center; border: 0; border-radius: inherit; color: inherit; background: transparent; cursor: zoom-in; }
.reference-image-preview img, .reference-video { position: absolute; inset: 0; display: block; width: 100%; height: 100%; border-radius: inherit; background: var(--app-fill-subtle); object-fit: cover; transition: transform .16s ease; }
.reference-image-preview:hover img { transform: scale(1.05); }
.reference-image-preview:focus-visible { outline: 2px solid #fff; outline-offset: -3px; }
.reference-name { position: absolute; right: 0; bottom: 0; left: 0; overflow: hidden; padding: 9px 4px 3px; opacity: 0; color: #fff; background: linear-gradient(transparent,rgb(20 23 31 / 78%)); pointer-events: none; transform: translateY(3px); transition: opacity .15s ease,transform .15s ease; }
.reference-name strong { display: block; overflow: hidden; color: inherit; font-size: 7px; font-weight: 600; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.reference-remove { position: absolute; top: 3px; right: 3px; display: grid; width: 14px; height: 14px; place-items: center; padding: 0; border: 0; border-radius: 50%; opacity: 0; color: #fff; background: rgb(32 35 44 / 72%); cursor: pointer; transform: scale(.82); transition: opacity .15s ease,transform .15s ease,background .15s ease; }
.reference-item:hover .reference-name, .reference-item:focus-within .reference-name { opacity: 1; transform: translateY(0); }
.reference-item:hover .reference-remove, .reference-item:focus-within .reference-remove { opacity: 1; transform: scale(1); }
.reference-remove:hover { background: #d94f5f; }
.reference-remove:focus-visible { opacity: 1; outline: 2px solid #fff; outline-offset: 1px; transform: scale(1); }
.reference-summary { display: flex; min-width: 0; align-items: center; gap: 4px; color: #848a99; white-space: nowrap; }
.reference-summary i { color: #c1c4cd; font-style: normal; }
.reference-summary small { margin-left: 4px; color: #a3a8b5; }
.is-disabled .reference-summary { color: #aeb2bd; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes reference-pulse { 50% { transform: scale(1.06); } }
</style>
