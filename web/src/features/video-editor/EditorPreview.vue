<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Film, LoaderCircle, Music2 } from 'lucide-vue-next'
import BufferedVideoPlayer from '@/components/BufferedVideoPlayer.vue'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { activeAt, audioVolume, orderedVideos, sourceKey, subtitleLines, totalDuration } from './model'
import type { AudioClip, EditDocument, EditorMedia } from './types'

const props = defineProps<{ document: EditDocument; media: EditorMedia[]; time: number; playing: boolean; muted: boolean; selectedId: string }>()
const emit = defineEmits<{ 'update:time': [value: number]; 'update:playing': [value: boolean]; select: [id: string] }>()
const player = ref<InstanceType<typeof BufferedVideoPlayer> | null>(null), monitor = ref<HTMLElement | null>(null)
const error = ref(''), ready = ref(false), activated = ref(false), size = ref({ width: 640, height: 360 })
const isBuffering = ref(false)
const audioElements = new Map<string, HTMLAudioElement>()
const frameWidth = computed(() => Math.min(size.value.width, size.value.height * props.document.width / props.document.height))
const frameHeight = computed(() => frameWidth.value * props.document.height / props.document.width)
const video = computed(() => orderedVideos(props.document).find(clip => activeAt(clip, Math.min(props.time, Math.max(0, totalDuration(props.document) - .00001)))))
const indexed = computed(() => new Map(props.media.map(item => [item.key, item])))
const source = computed(() => video.value ? indexed.value.get(sourceKey(video.value.source)) : null)
const nextSource = computed(() => {
  const next = orderedVideos(props.document).find(clip => clip.start >= (video.value ? video.value.start + video.value.duration - .001 : props.time + .001) && clip.id !== video.value?.id && indexed.value.get(sourceKey(clip.source))?.url && !indexed.value.get(sourceKey(clip.source))?.missing)
  return next ? indexed.value.get(sourceKey(next.source)) : null
})
const overlays = computed(() => props.document.clips.filter(clip => (clip.type === 'subtitle' || clip.type === 'sticker') && activeAt(clip, props.time)))
const activeAudio = computed(() => props.document.clips.filter((clip): clip is AudioClip => clip.type === 'audio' && activeAt(clip, props.time)))
const audioOnly = computed(() => !orderedVideos(props.document).length && activeAudio.value.length > 0)
let animation = 0, lastNow = 0, command = 0, disposed = false, observer: ResizeObserver | null = null
function audioRef(id: string, value: unknown) { if (value instanceof HTMLAudioElement) audioElements.set(id, value); else audioElements.delete(id) }
function silenceAudio() { audioElements.forEach(el => el.pause()) }
async function positionPlayer(autoplay: boolean) {
  const version = ++command
  ready.value = false; error.value = ''; silenceAudio()
  if (!source.value?.url || source.value.missing) { player.value?.pause(); ready.value = true; return }
  activated.value = true
  await nextTick()
  try {
    await player.value?.start((video.value?.trim_in || 0) + Math.max(0, props.time - (video.value?.start || 0)) * (video.value?.speed || 1), autoplay)
    if (!disposed && command === version) ready.value = !isBuffering.value
  } catch (reason) {
    if (!disposed && command === version && !(reason instanceof DOMException && reason.name === 'AbortError')) {
      error.value = tr('视频读取失败，请检查素材或重新加载'); emit('update:playing', false)
    }
  }
}
function syncAudio() {
  for (const clip of activeAudio.value) {
    const element = audioElements.get(clip.id), media = indexed.value.get(sourceKey(clip.source))
    if (!element || !media?.duration) continue
    const span = Math.max(.01, media.duration - clip.trim_in)
    const elapsed = Math.max(0, props.time - clip.start)
    const target = clip.trim_in + (clip.loop ? elapsed % span : elapsed)
    if (element.readyState >= 1 && Math.abs(element.currentTime - target) > .12) element.currentTime = target
    element.muted = props.muted; element.volume = Math.min(1, audioVolume(clip, props.time))
    if (props.playing && ready.value && element.paused) void element.play().catch(() => { error.value = tr('音频播放失败，请检查素材或浏览器播放权限'); emit('update:playing', false) })
    if ((!props.playing || !ready.value) && !element.paused) element.pause()
  }
}
function tick(now: number) {
  if (props.playing && ready.value && lastNow) {
    let time = props.time
    if (video.value && source.value?.url && !source.value.missing) {
      time = video.value.start + Math.max(0, player.value!.time() - video.value.trim_in) / video.value.speed
      if (time >= video.value.start + video.value.duration - .005) time = video.value.start + video.value.duration
    } else time += (now - lastNow) / 1000
    const end = totalDuration(props.document)
    emit('update:time', Math.min(end, time))
    if (time >= end - .001) emit('update:playing', false)
  }
  syncAudio(); lastNow = now; animation = requestAnimationFrame(tick)
}
function ended() { if (video.value) emit('update:time', video.value.start + video.value.duration) }
function failed() { error.value = tr('视频读取失败，请检查素材或重新加载'); emit('update:playing', false) }
function buffering(value: boolean) { isBuffering.value = value; ready.value = !value; if (value) silenceAudio() }
function seek() { return positionPlayer(props.playing) }
function visibility() { if (document.visibilityState === 'hidden') emit('update:playing', false) }
watch(() => [video.value?.id, source.value?.url, video.value?.trim_in, video.value?.speed], () => { if (activated.value || props.playing) void positionPlayer(props.playing) })
watch(() => props.playing, playing => { if (playing) { lastNow = 0; void positionPlayer(true) } else { player.value?.pause(); silenceAudio() } })
watch(() => props.document, () => { if (activated.value) void positionPlayer(props.playing) })
onMounted(() => {
  animation = requestAnimationFrame(tick); document.addEventListener('visibilitychange', visibility)
  observer = new ResizeObserver(entries => { const entry = entries[0]; if (entry) size.value = { width: entry.contentRect.width, height: entry.contentRect.height } })
  if (monitor.value) observer.observe(monitor.value)
})
onBeforeUnmount(() => { disposed = true; ++command; cancelAnimationFrame(animation); observer?.disconnect(); silenceAudio(); document.removeEventListener('visibilitychange', visibility) })
defineExpose({ seek })
</script>

<template>
  <div ref="monitor" class="editor-preview-monitor">
    <div class="editor-preview-frame" :style="{ width: `${frameWidth}px`, height: `${frameHeight}px` }">
      <div class="editor-video-layer" :style="{ transform: `scale(${video?.scale || 1})`, '--editor-fit': video?.fit === 'cover' ? 'cover' : 'contain' }">
        <BufferedVideoPlayer v-if="activated" ref="player" :src="source?.missing ? '' : mediaUrl(source?.url)" :next-src="mediaUrl(nextSource?.url)" :poster="mediaUrl(source?.poster)" :title="video?.name || tr('视频预览')" :muted="muted" :volume="video?.volume || 0" :playback-rate="video?.speed || 1" @ended="ended" @error="failed" @buffering="buffering" />
        <VideoThumbnail v-else-if="source?.url && !source.missing" :src="mediaUrl(source.url)" :poster="mediaUrl(source.poster)" :fit="video?.fit === 'cover' ? 'cover' : 'contain'" />
      </div>
      <div v-if="audioOnly" class="video-stage-blackout editor-audio-preview"><Music2 :size="32" /><strong>{{ activeAudio[0]?.name }}</strong><span>{{ tr('音频预览') }}</span></div>
      <div v-else-if="source?.missing || (!video && !overlays.length)" class="video-stage-blackout"><Film :size="27" /><span>{{ video ? tr('这个分镜尚未生成或素材已失效') : tr('时间线空白') }}</span></div>
      <div v-if="playing && !ready" class="editor-buffer-state" role="status"><LoaderCircle :size="18" class="is-spinning" />{{ tr('正在缓冲视频') }}</div>
      <template v-for="clip in overlays" :key="clip.id">
        <button v-if="clip.type === 'subtitle'" type="button" class="editor-subtitle" :class="{ 'is-selected': selectedId === clip.id }" :style="{ bottom: `${clip.bottom}%`, color: clip.color, fontSize: `${clip.font_size * frameHeight / 1080}px`, lineHeight: 1.2, textShadow: '0 1px 2px black, 1px 0 black, -1px 0 black' }" :aria-label="tr('选择字幕')" @click="emit('select', clip.id)">{{ subtitleLines(clip, document) }}</button>
        <button v-else-if="clip.type === 'sticker'" class="editor-sticker" :class="{ 'is-selected': selectedId === clip.id }" :style="{ left: `${clip.x}%`, top: `${clip.y}%`, width: `${25 * clip.scale}%`, opacity: clip.opacity }" :aria-label="tr('选择贴纸')" @click="emit('select', clip.id)"><img :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" alt="" /></button>
      </template>
      <p v-if="error" class="editor-preview-error" role="alert">{{ error }}</p>
    </div>
    <audio v-for="clip in activeAudio" :key="clip.id" :ref="element => audioRef(clip.id, element)" :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" preload="auto" @loadedmetadata="syncAudio" @error="error = tr('音频读取失败，请检查素材'); emit('update:playing', false)" />
  </div>
</template>

<style scoped>
.editor-preview-monitor{display:flex;align-items:center;justify-content:center;min-width:0;min-height:0;height:100%;background:#101113;overflow:hidden}
.editor-preview-frame{position:relative;overflow:hidden;background:#000;width:100%;max-width:100%;max-height:100%;height:auto;container:editor-preview / size}
.editor-video-layer{position:absolute;inset:0;transform-origin:center}.editor-video-layer :deep(video),.editor-video-layer :deep(img){object-fit:var(--editor-fit)!important}
.editor-video-layer :deep(.video-thumbnail){background:#000}
.video-stage-blackout{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:#b9bdc7;font-size:12px;background:#000}
.editor-buffer-state{position:absolute;top:10px;left:10px;display:flex;align-items:center;gap:8px;color:#fff;background:#000a;padding:7px;border-radius:5px;font-size:11px}
.editor-subtitle{position:absolute;left:50%;transform:translateX(-50%);white-space:pre;width:max-content;max-width:94%;padding:0;border:1px solid transparent;text-align:center;background:transparent;font-family:'Noto Sans SC Variable',sans-serif;font-weight:500;cursor:pointer}
.editor-subtitle.is-selected,.editor-sticker.is-selected{outline:1px solid #b8a7ff;outline-offset:3px}.editor-sticker{position:absolute;transform:translate(-50%,-50%);padding:0;border:0;background:transparent;cursor:pointer}.editor-sticker img{width:100%;display:block}.editor-preview-error{position:absolute;inset:auto 10px 10px;margin:0;color:#ffd5d5;background:#411c23ed;padding:10px;font-size:12px;line-height:1.6}
.is-spinning{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.is-spinning{animation:none}}
</style>
