<script setup lang="ts">
import { computed, ref } from 'vue'
import { Film, ImageIcon, LoaderCircle, Plus, X } from 'lucide-vue-next'
import type { VideoGenerationModel, VideoReferenceMedia } from '@/types'

const props = defineProps<{
  model: VideoGenerationModel | null
  media: VideoReferenceMedia[]
  assetImageCount: number
  highlightedMediaIndex?: number
  disabled?: boolean
  uploading?: boolean
}>()

const emit = defineEmits<{
  upload: [files: File[]]
  remove: [index: number]
}>()

const input = ref<HTMLInputElement | null>(null)
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
</script>

<template>
  <section class="reference-media-bar" :class="{ 'is-disabled': disabled }">
    <input ref="input" type="file" multiple :accept="accept" @change="handleFiles" />
    <button
      type="button"
      class="reference-add"
      :disabled="unavailable"
      :title="disabled ? '首尾帧模式不能同时使用参考素材' : '上传参考图片或视频'"
      aria-label="上传参考图片或视频"
      @click="chooseFiles"
    >
      <LoaderCircle v-if="uploading" :size="16" />
      <Plus v-else :size="16" />
    </button>
    <div v-if="media.length" class="reference-list" aria-label="已上传参考素材">
      <article
        v-for="(item, index) in media"
        :key="`${item.type}:${item.url}`"
        class="reference-item"
        :class="{ 'is-reference-highlighted': highlightedMediaIndex === index }"
        :data-reference-media-index="index"
      >
        <img v-if="item.type === 'image'" :src="item.url" :alt="item.name || '参考图片'" />
        <video
          v-else
          class="reference-video"
          :src="item.url"
          :aria-label="item.name || '参考视频第一帧'"
          preload="metadata"
          muted
          playsinline
          @loadedmetadata="showFirstFrame"
        />
        <span class="reference-name">
          <strong>{{ item.name || (item.type === 'image' ? '参考图片' : '参考视频') }}</strong>
        </span>
        <button type="button" class="reference-remove" :aria-label="`移除 ${item.name || '参考素材'}`" title="移除" @click="emit('remove', index)"><X :size="10" /></button>
      </article>
    </div>
    <div class="reference-summary">
      <ImageIcon :size="13" />
      <span>图片 {{ assetImageCount + uploadedImages }}/{{ model?.capabilities.max_reference_images || 0 }}</span>
      <i>·</i>
      <Film :size="13" />
      <span>视频 {{ uploadedVideos }}/{{ model?.capabilities.max_reference_videos || 0 }}</span>
      <small v-if="uploadedVideos">{{ totalVideoDuration.toFixed(1) }}/{{ model?.capabilities.reference_video_total_duration_max || 0 }}s</small>
      <small v-if="assetImageCount">资产图已计入</small>
      <small v-else-if="!model">请先启用视频模型</small>
      <small v-else>支持图片与 MP4/MOV</small>
    </div>
  </section>
</template>

<style scoped>
.reference-media-bar { display: flex; min-width: 0; align-items: center; gap: 8px; padding: 0 16px 8px; color: #858b99; font-size: 9px; }
.reference-media-bar > input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.reference-add { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 0; border-radius: 9px; color: #5e60ed; background: #eeeefe; box-shadow: inset 0 0 0 1px #e1e2ff; cursor: pointer; transition: transform .16s ease, background .16s ease; }
.reference-add:hover:not(:disabled) { background: #e5e6ff; transform: translateY(-1px); }
.reference-add:disabled { color: #aeb2bf; background: #f2f3f6; cursor: not-allowed; }
.reference-add svg.is-spinning, .reference-add svg { animation: none; }
.reference-add svg:first-child:last-child:is(.lucide-loader-circle) { animation: spin 1s linear infinite; }
.reference-list { display: flex; min-width: 0; max-width: 56%; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.reference-list::-webkit-scrollbar { display: none; }
.reference-item { position: relative; width: 58px; height: 34px; flex: 0 0 58px; overflow: hidden; border-radius: 8px; background: #e7e9f1; box-shadow: inset 0 0 0 1px #e1e3ea; }
.reference-item.is-reference-highlighted { box-shadow: inset 0 0 0 2px #ff7a8c, 0 0 0 3px rgb(255 122 140 / 24%); animation: reference-pulse .7s ease 2; }
.reference-item > img, .reference-video { display: block; width: 100%; height: 100%; border-radius: inherit; background: #e7e9f1; object-fit: cover; }
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
@media (prefers-color-scheme: dark) {
  .reference-add { color: #a9aaff; background: #292943; box-shadow: inset 0 0 0 1px #3e3f68; }
  .reference-item, .reference-video { background: #30333d; box-shadow: inset 0 0 0 1px #414550; }
}
</style>
