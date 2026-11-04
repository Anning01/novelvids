<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Film, LoaderCircle, Music2, RotateCw, Maximize2 } from 'lucide-vue-next'
import BufferedVideoPlayer from '@/components/BufferedVideoPlayer.vue'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { resizeSticker, scaleSticker, stickerRotation } from './stickerTransform'
import { subtitleAppearance, subtitleBlockWidth } from './subtitleStyle'
import { MediaGain } from '@/shared/mediaGain'
import { activeAt, audioVolume, orderedVideos, sourceKey, subtitleLines, totalDuration } from './model'
import type { AudioClip, ClipPatch, SubtitleClip, StickerClip, EditDocument, EditorMedia } from './types'

const props = defineProps<{ document: EditDocument; media: EditorMedia[]; time: number; playing: boolean; muted: boolean; selectedId: string; readOnly?: boolean }>()
const emit = defineEmits<{ 'update:time': [value: number]; 'update:playing': [value: boolean]; select: [id: string]; position: [id: string, patch: ClipPatch] }>()
const player = ref<InstanceType<typeof BufferedVideoPlayer> | null>(null), monitor = ref<HTMLElement | null>(null)
const error = ref(''), ready = ref(false), activated = ref(false), size = ref({ width: 640, height: 360 })
const isBuffering = ref(false)
const overlayDrag = ref<{id:string;x:number;vertical:number}|null>(null)
const stickerPreview=ref<{id:string;patch:ClipPatch}|null>(null)
const stickerSizes=ref<Record<string,{width:number;height:number}>>({})
let dragCleanup: (()=>void)|null=null
function overlayPosition(clip: SubtitleClip | StickerClip) {
  return overlayDrag.value?.id===clip.id ? overlayDrag.value : {x:clip.x??50,vertical:clip.type==='subtitle'?clip.bottom:clip.y}
}
function nudgeOverlay(event:KeyboardEvent,clip:SubtitleClip|StickerClip) {
  if(props.readOnly)return
  const position=overlayPosition(clip),step=event.shiftKey?5:1
  const x=Math.max(0,Math.min(100,position.x+(event.key==='ArrowLeft'?-step:event.key==='ArrowRight'?step:0)))
  const vertical=Math.max(0,Math.min(100,position.vertical+(event.key==='ArrowUp'?-step:event.key==='ArrowDown'?step:0)*(clip.type==='subtitle'?-1:1)))
  emit('position',clip.id,clip.type==='subtitle'?{x,bottom:vertical}:{x,y:vertical})
}
function dragOverlay(event:PointerEvent,clip:SubtitleClip|StickerClip) {
  emit('select',clip.id)
  if(props.readOnly||event.button!==0)return
  const element=event.currentTarget as HTMLElement,frame=element.parentElement!.getBoundingClientRect(),box=element.getBoundingClientRect()
  if(!frame.width||!frame.height)return
  event.preventDefault();element.focus({preventScroll:true});emit('update:playing',false);dragCleanup?.()
  const origin=overlayPosition(clip),x=event.clientX,y=event.clientY
  let moved=false
  const clamp=(value:number,min:number,max:number)=>Math.round(Math.max(min,Math.min(max,value))*100)/100
  const move=(current:PointerEvent)=>{
    if(current.pointerId!==event.pointerId)return
    if(Math.hypot(current.clientX-x,current.clientY-y)>3)moved=true
    if(!moved)return
    const halfWidth=Math.min(50,box.width/frame.width*50),halfHeight=Math.min(50,box.height/frame.height*50)
    overlayDrag.value={id:clip.id,x:clamp(origin.x+(current.clientX-x)/frame.width*100,halfWidth,100-halfWidth),vertical:clip.type==='subtitle'
      ?clamp(origin.vertical-(current.clientY-y)/frame.height*100,0,100-halfHeight*2)
      :clamp(origin.vertical+(current.clientY-y)/frame.height*100,halfHeight,100-halfHeight)}
  }
  const stop=(current:PointerEvent)=>{
    if(current.pointerId!==event.pointerId)return
    if(current.type==='pointerup'){move(current);const position=overlayDrag.value;if(moved&&position)emit('position',clip.id,clip.type==='subtitle'?{x:position.x,bottom:position.vertical}:{x:position.x,y:position.vertical})}
    dragCleanup?.()
  }
  dragCleanup=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);window.removeEventListener('pointercancel',stop);overlayDrag.value=null;dragCleanup=null}
  window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop);window.addEventListener('pointercancel',stop)
}
function stickerState(clip:StickerClip):StickerClip {
  return stickerPreview.value?.id===clip.id?{...clip,...stickerPreview.value.patch}:clip
}
function stickerDimensions(clip:StickerClip) {
  const source=indexed.value.get(sourceKey(clip.source)),measured=stickerSizes.value[sourceKey(clip.source)]
  return {width:source?.width||measured?.width||1,height:source?.height||measured?.height||1}
}
function stickerStyle(clip:StickerClip) {
  const current=stickerState(clip),dimensions=stickerDimensions(clip)
  return {left:`${overlayPosition(clip).x}%`,top:`${overlayPosition(clip).vertical}%`,width:`${25*current.scale}%`,
    aspectRatio:String(dimensions.width/dimensions.height*current.scale/(current.scale_y??current.scale)),
    transform:`translate(-50%,-50%) rotate(${current.rotation??0}deg)`}
}
function stickerLoaded(event:Event,clip:StickerClip) {
  const image=event.target as HTMLImageElement
  if(image.naturalWidth&&image.naturalHeight)stickerSizes.value[sourceKey(clip.source)]={width:image.naturalWidth,height:image.naturalHeight}
}
function transformSticker(event:PointerEvent,clip:StickerClip,mode:'resize'|'rotate') {
  if(props.readOnly||event.button!==0)return
  const handle=event.currentTarget as HTMLElement,frame=handle.parentElement!.parentElement!.getBoundingClientRect()
  if(!frame.width||!frame.height)return
  event.preventDefault();handle.focus({preventScroll:true});dragCleanup?.();emit('select',clip.id);emit('update:playing',false)
  const dimensions=stickerDimensions(clip),width=frame.width*.25*clip.scale,height=frame.width*.25*(clip.scale_y??clip.scale)*dimensions.height/dimensions.width
  const center={x:frame.left+frame.width*clip.x/100,y:frame.top+frame.height*clip.y/100}
  const angle=(clip.rotation??0)*Math.PI/180,x=event.clientX,y=event.clientY,origin=Math.atan2(y-center.y,x-center.x)
  let moved=false
  const move=(current:PointerEvent)=>{
    if(current.pointerId!==event.pointerId)return
    if(Math.hypot(current.clientX-x,current.clientY-y)>3)moved=true
    if(!moved)return
    const dx=current.clientX-x,dy=current.clientY-y
    const patch=mode==='rotate'?{rotation:stickerRotation((clip.rotation??0)+(Math.atan2(current.clientY-center.y,current.clientX-center.x)-origin)*180/Math.PI)}
      :resizeSticker(clip,Math.cos(angle)*dx+Math.sin(angle)*dy,-Math.sin(angle)*dx+Math.cos(angle)*dy,width,height)
    stickerPreview.value={id:clip.id,patch}
  }
  const stop=(current:PointerEvent)=>{
    if(current.pointerId!==event.pointerId)return
    if(current.type==='pointerup'){move(current);if(moved&&stickerPreview.value)emit('position',clip.id,stickerPreview.value.patch)}
    dragCleanup?.()
  }
  dragCleanup=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);window.removeEventListener('pointercancel',stop);stickerPreview.value=null;dragCleanup=null}
  window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop);window.addEventListener('pointercancel',stop)
}
function nudgeStickerTransform(event:KeyboardEvent,clip:StickerClip,mode:'resize'|'rotate') {
  if(props.readOnly)return
  const direction=event.key==='ArrowLeft'||event.key==='ArrowDown'?-1:1
  emit('position',clip.id,mode==='rotate'?{rotation:stickerRotation((clip.rotation??0)+direction*(event.shiftKey?15:1))}:scaleSticker(clip,clip.scale+direction*(event.shiftKey ? .1 : .01)))
}
const gain = new MediaGain()
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
    if ((video.value?.speed || 1) > 16) player.value?.pause()
    await player.value?.start((video.value?.trim_in || 0) + Math.max(0, props.time - (video.value?.start || 0)) * (video.value?.speed || 1), autoplay && (video.value?.speed || 1) <= 16)
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
    element.muted = props.muted; gain.set(element, audioVolume(clip, props.time))
    if (props.playing && ready.value && element.paused) void element.play().catch(() => { error.value = tr('音频播放失败，请检查素材或浏览器播放权限'); emit('update:playing', false) })
    if ((!props.playing || !ready.value) && !element.paused) element.pause()
  }
}
function tick(now: number) {
  if (props.playing && ready.value && lastNow) {
    let time = props.time
    if (video.value && source.value?.url && !source.value.missing) {
      if (video.value.speed > 16) {
        time += (now - lastNow) / 1000
        player.value?.seekFrame(video.value.trim_in + (time - video.value.start) * video.value.speed)
      } else time = video.value.start + Math.max(0, player.value!.time() - video.value.trim_in) / video.value.speed
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
onBeforeUnmount(() => { dragCleanup?.(); gain.dispose(); disposed = true; ++command; cancelAnimationFrame(animation); observer?.disconnect(); silenceAudio(); document.removeEventListener('visibilitychange', visibility) })
defineExpose({ seek })
</script>

<template>
  <div ref="monitor" class="editor-preview-monitor">
    <div class="editor-preview-frame" :style="{ width: `${frameWidth}px`, height: `${frameHeight}px` }">
      <div class="editor-video-layer" :style="{ transform: `rotate(${video?.rotation || 0}deg) scale(${video?.scale || 1})`, '--editor-fit': video?.fit === 'cover' ? 'cover' : 'contain' }">
        <BufferedVideoPlayer v-if="activated" ref="player" :src="source?.missing ? '' : mediaUrl(source?.url)" :next-src="mediaUrl(nextSource?.url)" :poster="mediaUrl(source?.poster)" :title="video?.name || tr('视频预览')" :muted="muted" :volume="video?.volume || 0" :audio-processing="true" :playback-rate="video?.speed || 1" @ended="ended" @error="failed" @buffering="buffering" />
        <VideoThumbnail v-else-if="source?.url && !source.missing" :src="mediaUrl(source.url)" :poster="mediaUrl(source.poster)" :fit="video?.fit === 'cover' ? 'cover' : 'contain'" />
      </div>
      <div v-if="audioOnly" class="video-stage-blackout editor-audio-preview"><Music2 :size="32" /><strong>{{ activeAudio[0]?.name }}</strong><span>{{ tr('音频预览') }}</span></div>
      <div v-else-if="source?.missing || (!video && !overlays.length)" class="video-stage-blackout"><Film :size="27" /><span>{{ video ? tr('这个分镜尚未生成或素材已失效') : tr('时间线空白') }}</span></div>
      <div v-if="playing && !ready" class="editor-buffer-state" role="status"><LoaderCircle :size="18" class="is-spinning" />{{ tr('正在缓冲视频') }}</div>
      <template v-for="clip in overlays" :key="clip.id">
        <button v-if="clip.type === 'subtitle'" type="button" class="editor-subtitle" :class="{ 'is-selected': selectedId === clip.id, 'is-dragging':overlayDrag?.id===clip.id, 'is-readonly':readOnly }" :style="{ left:`${overlayPosition(clip).x}%`, bottom: `${overlayPosition(clip).vertical}%`, ...subtitleAppearance(clip,frameHeight), width:`${subtitleBlockWidth(clip,document,frameHeight)}px` }" :aria-label="tr('选择字幕')" @keydown.left.prevent.stop="nudgeOverlay($event,clip)" @keydown.right.prevent.stop="nudgeOverlay($event,clip)" @keydown.up.prevent.stop="nudgeOverlay($event,clip)" @keydown.down.prevent.stop="nudgeOverlay($event,clip)" @pointerdown="dragOverlay($event,clip)" @dragstart.prevent @click="emit('select', clip.id)">{{ subtitleLines(clip, document) }}</button>
        <div v-else-if="clip.type === 'sticker'" class="editor-sticker" role="group" tabindex="0" :class="{ 'is-selected': selectedId === clip.id, 'is-dragging':overlayDrag?.id===clip.id||stickerPreview?.id===clip.id, 'is-readonly':readOnly }" :style="stickerStyle(clip)" :aria-label="tr('选择贴纸')" @keydown.left.prevent.stop="nudgeOverlay($event,clip)" @keydown.right.prevent.stop="nudgeOverlay($event,clip)" @keydown.up.prevent.stop="nudgeOverlay($event,clip)" @keydown.down.prevent.stop="nudgeOverlay($event,clip)" @keydown.enter.prevent.stop="emit('select',clip.id)" @keydown.space.prevent.stop="emit('select',clip.id)" @pointerdown="dragOverlay($event,clip)" @dragstart.prevent @click="emit('select', clip.id)">
          <img :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" :style="{opacity:clip.opacity}" alt="" draggable="false" @load="stickerLoaded($event,clip)"/>
          <template v-if="selectedId===clip.id&&!readOnly">
            <button type="button" class="editor-sticker-handle editor-sticker-resize" :aria-label="tr('缩放贴纸')" :title="tr('拖动缩放贴纸')" @pointerdown.stop="transformSticker($event,clip,'resize')" @click.stop @keydown.left.prevent.stop="nudgeStickerTransform($event,clip,'resize')" @keydown.right.prevent.stop="nudgeStickerTransform($event,clip,'resize')" @keydown.up.prevent.stop="nudgeStickerTransform($event,clip,'resize')" @keydown.down.prevent.stop="nudgeStickerTransform($event,clip,'resize')"><Maximize2 :size="13"/></button>
            <button type="button" class="editor-sticker-handle editor-sticker-rotate" :aria-label="tr('旋转贴纸')" :title="tr('拖动旋转贴纸')" @pointerdown.stop="transformSticker($event,clip,'rotate')" @click.stop @keydown.left.prevent.stop="nudgeStickerTransform($event,clip,'rotate')" @keydown.right.prevent.stop="nudgeStickerTransform($event,clip,'rotate')"><RotateCw :size="13"/></button>
          </template>
        </div>
      </template>
      <p v-if="error" class="editor-preview-error" role="alert">{{ error }}</p>
    </div>
    <audio v-for="clip in activeAudio" :key="clip.id" :ref="element => audioRef(clip.id, element)" :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" crossorigin="anonymous" preload="auto" @loadedmetadata="syncAudio" @error="error = tr('音频读取失败，请检查素材'); emit('update:playing', false)" />
  </div>
</template>

<style scoped>
.editor-preview-monitor{display:flex;align-items:center;justify-content:center;min-width:0;min-height:0;height:100%;background:#101113;overflow:hidden}
.editor-preview-frame{position:relative;overflow:hidden;background:#000;width:100%;max-width:100%;max-height:100%;height:auto;container:editor-preview / size}
.editor-video-layer{position:absolute;inset:0;transform-origin:center}.editor-video-layer :deep(video),.editor-video-layer :deep(img){object-fit:var(--editor-fit)!important}
.editor-video-layer :deep(.video-thumbnail){background:#000}
.video-stage-blackout{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:#b9bdc7;font-size:12px;background:#000}
.editor-buffer-state{position:absolute;top:10px;left:10px;display:flex;align-items:center;gap:8px;color:#fff;background:#000a;padding:7px;border-radius:5px;font-size:11px}
.editor-subtitle{position:absolute;left:50%;transform:translateX(-50%);white-space:pre;width:max-content;max-width:94%;padding:0;border:1px solid transparent;text-align:center;background:transparent;font-family:'Noto Sans SC Variable',sans-serif;font-weight:500;cursor:grab;touch-action:none;user-select:none}
.editor-subtitle.is-selected,.editor-sticker.is-selected{outline:1px solid #b8a7ff;outline-offset:3px}.editor-sticker{position:absolute;transform:translate(-50%,-50%);padding:0;border:0;background:transparent;cursor:grab;touch-action:none;user-select:none}.editor-sticker img{width:100%;height:100%;object-fit:fill;display:block}.editor-preview-error{position:absolute;inset:auto 10px 10px;margin:0;color:#ffd5d5;background:#411c23ed;padding:10px;font-size:12px;line-height:1.6}
.editor-subtitle.is-dragging,.editor-sticker.is-dragging{cursor:grabbing;z-index:2}.editor-subtitle.is-readonly,.editor-sticker.is-readonly{cursor:pointer}
.editor-sticker-handle{position:absolute;display:grid;place-items:center;width:24px;height:24px;border:1px solid var(--app-accent);border-radius:5px;background:var(--app-surface);color:var(--app-accent);touch-action:none}.editor-sticker-resize{right:-12px;bottom:-12px;cursor:nwse-resize}.editor-sticker-rotate{left:calc(50% - 12px);top:-34px;cursor:grab}.editor-sticker-rotate::after{content:"";position:absolute;top:23px;left:11px;height:10px;width:1px;background:var(--app-accent)}
.is-spinning{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.is-spinning{animation:none}}
</style>
