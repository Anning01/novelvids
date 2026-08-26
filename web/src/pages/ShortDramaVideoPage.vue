<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowDownToLine,
  ChevronLeft,
  Clapperboard,
  Download,
  Film,
  LoaderCircle,
  Maximize2,
  Pause,
  Play,
  Scissors,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  ZoomIn,
  ZoomOut,
} from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import ShortDramaWorkspaceShell from '@/components/ShortDramaWorkspaceShell.vue'
import { api, mediaUrl } from '@/api'
import { downloadFile } from '@/shared/downloadFile'
import { notice } from '@/shared/notice'
import { episodeDisplayLabel, stripChapterOrdinal } from '@/shared/chapterTitle'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { buildChapterVideoTimeline, chapterHasCompletedVideo, type ChapterVideoTimelineItem } from '@/shared/chapterVideoTimeline'
import { VirtualClipPlaybackClock } from '@/shared/virtualClipPlaybackClock'
import type { Chapter, Novel, Scene, Video as VideoResult } from '@/types'

interface ProjectView extends Novel {
  aspectRatio: string
  resolution: string
  style: string
  creationMode: 'agent' | 'manual'
}

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const project = ref<ProjectView | null>(null)
const chapters = ref<Chapter[]>([])
const activeChapter = ref<Chapter | null>(null)
const scenes = ref<Scene[]>([])
const videos = ref<Record<number, VideoResult[]>>({})
const activeSceneId = ref(0)
const loading = ref(true)
const loadError = ref('')
const player = ref<HTMLVideoElement | null>(null)
const stage = ref<HTMLElement | null>(null)
const timelineScroll = ref<HTMLElement | null>(null)
const playing = ref(false)
const muted = ref(false)
const playbackRate = ref(1)
const clipCurrentTime = ref(0)
const timelineScale = ref(1)
const downloadingChapter = ref(false)
let loadVersion = 0

const MIN_TIMELINE_SCALE = 1
const MAX_TIMELINE_SCALE = 5

const timelineItems = computed(() => buildChapterVideoTimeline(scenes.value, videos.value))
const videoEnabled = computed(() => chapterHasCompletedVideo(scenes.value, videos.value))
const playableItems = computed(() => timelineItems.value.filter(item => item.state === 'completed' && item.video?.url))
const activeItem = computed(() => timelineItems.value.find(item => item.scene.id === activeSceneId.value) || null)
const activeTimelineIndex = computed(() => timelineItems.value.findIndex(item => item.scene.id === activeSceneId.value))
const totalDuration = computed(() => timelineItems.value.reduce((sum, item) => sum + item.duration, 0))
const timelinePixelsPerSecond = computed(() => 10 + timelineScale.value * 12)
const timelineContentWidth = computed(() => Math.max(1, totalDuration.value * timelinePixelsPerSecond.value))
const timelineRulerTicks = computed(() => Array.from(
  { length: Math.ceil(totalDuration.value) + 1 },
  (_, second) => ({ second, isMajor: second % 10 === 0, isMiddle: second % 5 === 0 }),
))
const activeOffset = computed(() => {
  const index = timelineItems.value.findIndex(item => item.scene.id === activeSceneId.value)
  return index < 1 ? 0 : timelineItems.value.slice(0, index).reduce((sum, item) => sum + item.duration, 0)
})
const chapterCurrentTime = computed(() => Math.min(totalDuration.value, activeOffset.value + clipCurrentTime.value))
const progressPercent = computed(() => totalDuration.value > 0 ? chapterCurrentTime.value / totalDuration.value * 100 : 0)
const canGoPrevious = computed(() => activeTimelineIndex.value > 0)
const canGoNext = computed(() => activeTimelineIndex.value >= 0 && activeTimelineIndex.value < timelineItems.value.length - 1)

const gapPlaybackClock = new VirtualClipPlaybackClock(
  currentTime => { clipCurrentTime.value = currentTime },
  () => advanceTimeline(true),
)

function formatTime(seconds: number) {
  const value = Math.max(0, Math.round(seconds || 0))
  const minutes = Math.floor(value / 60)
  return `${String(minutes).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

function sceneLabel(item: ChapterVideoTimelineItem) {
  return `分镜 ${item.scene.sequence}`
}

function statusLabel(item: ChapterVideoTimelineItem) {
  if (item.state === 'completed') return '视频已生成'
  if (item.state === 'generating') return '视频生成中'
  if (item.state === 'failed') return '视频生成失败'
  return '视频尚未生成'
}

function timelineClipStyle(item: ChapterVideoTimelineItem) {
  return { width: `${Math.max(1, item.duration * timelinePixelsPerSecond.value)}px` }
}

function timelineTickStyle(second: number) {
  return { left: `${second * timelinePixelsPerSecond.value}px` }
}

function playheadStyle() {
  return { left: `${chapterCurrentTime.value * timelinePixelsPerSecond.value}px` }
}

function setTimelineScale(value: number) {
  timelineScale.value = Math.min(MAX_TIMELINE_SCALE, Math.max(MIN_TIMELINE_SCALE, value))
}

function revealPlayhead(center = false) {
  const viewport = timelineScroll.value
  if (!viewport) return
  const position = chapterCurrentTime.value * timelinePixelsPerSecond.value
  const edgePadding = 44
  if (center) {
    viewport.scrollLeft = Math.max(0, position - viewport.clientWidth / 2)
  } else if (position < viewport.scrollLeft + edgePadding) {
    viewport.scrollLeft = Math.max(0, position - edgePadding)
  } else if (position > viewport.scrollLeft + viewport.clientWidth - edgePadding) {
    viewport.scrollLeft = Math.max(0, position - viewport.clientWidth + edgePadding)
  }
}

async function loadChapter(chapterId: number) {
  const version = ++loadVersion
  loading.value = true
  loadError.value = ''
  pause()
  try {
    const response = await api.workbenchBootstrap(projectId.value, chapterId)
    if (version !== loadVersion) return
    activeChapter.value = response.data.chapter
    scenes.value = response.data.scenes
    videos.value = response.data.videos
    const items = buildChapterVideoTimeline(response.data.scenes, response.data.videos)
    const requestedSceneId = Number(route.query.scene)
    const requested = items.find(item => item.scene.id === requestedSceneId)
    activeSceneId.value = (requested || items.find(item => item.state === 'completed') || items[0])?.scene.id || 0
    clipCurrentTime.value = 0
  } catch (error) {
    if (version !== loadVersion) return
    loadError.value = error instanceof Error ? error.message : '视频工作区加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [projectResponse, chaptersResponse] = await Promise.all([
      api.novelMeta(projectId.value),
      api.chapters(projectId.value),
    ])
    const settings = readShortDramaSettings(projectResponse.data)
    project.value = {
      ...projectResponse.data,
      aspectRatio: settings.aspectRatio || '9:16',
      resolution: settings.resolution || '720p',
      style: settings.style || '写实通用',
      creationMode: settings.mode || 'agent',
    }
    chapters.value = chaptersResponse.data.items
    const requestedChapterId = Number(route.query.chapter)
    const chapter = chapters.value.find(item => item.id === requestedChapterId) || chapters.value[0]
    if (!chapter) {
      loading.value = false
      return
    }
    if (chapter.id !== requestedChapterId) {
      await router.replace({ query: { ...route.query, chapter: String(chapter.id) } })
    }
    await loadChapter(chapter.id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '视频工作区加载失败'
    loading.value = false
  }
}

async function selectChapter(chapter: Chapter) {
  if (chapter.id === activeChapter.value?.id) return
  await router.replace({ query: { chapter: String(chapter.id) } })
  await loadChapter(chapter.id)
}

function startVirtualClipPlayback(startTime = clipCurrentTime.value) {
  const item = activeItem.value
  if (!item || item.video?.url) return
  playing.value = true
  gapPlaybackClock.play({
    duration: item.duration,
    startTime,
    playbackRate: playbackRate.value,
  })
}

function startVideoPlayback(item: ChapterVideoTimelineItem, startTime: number, autoplay: boolean) {
  const video = player.value
  if (!video || activeSceneId.value !== item.scene.id) return
  const prepare = () => {
    video.currentTime = Math.min(startTime, Math.max(0, video.duration || item.duration))
    if (autoplay) void video.play().catch(() => { playing.value = false })
  }
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) prepare()
  else video.addEventListener('loadedmetadata', prepare, { once: true })
}

function selectTimelineItem(item: ChapterVideoTimelineItem, autoplay = false, startTime = 0) {
  gapPlaybackClock.stop()
  player.value?.pause()
  playing.value = false
  const changed = activeSceneId.value !== item.scene.id
  activeSceneId.value = item.scene.id
  clipCurrentTime.value = Math.min(item.duration, Math.max(0, startTime))
  if (changed) void router.replace({ query: { ...route.query, chapter: String(activeChapter.value?.id || ''), scene: String(item.scene.id) } })
  void nextTick(() => {
    revealPlayhead()
    if (item.video?.url) startVideoPlayback(item, clipCurrentTime.value, autoplay)
    else if (autoplay) startVirtualClipPlayback(clipCurrentTime.value)
  })
}

function previousClip() {
  const item = timelineItems.value[activeTimelineIndex.value - 1]
  if (item) selectTimelineItem(item, playing.value)
}

function advanceTimeline(autoplay = playing.value) {
  const item = timelineItems.value[activeTimelineIndex.value + 1]
  if (item) selectTimelineItem(item, autoplay)
  else playing.value = false
}

function nextClip(autoplay = playing.value) {
  advanceTimeline(autoplay)
}

function togglePlayback() {
  const item = activeItem.value
  if (!item) return
  if (!item.video?.url) {
    if (playing.value) pause()
    else startVirtualClipPlayback()
    return
  }
  if (!player.value) return
  if (player.value.paused) void player.value.play().catch(() => { playing.value = false })
  else player.value.pause()
}

function pause() {
  gapPlaybackClock.pause()
  player.value?.pause()
  playing.value = false
}

function cyclePlaybackRate() {
  const rates = [1, 1.25, 1.5, 2]
  const next = rates[(rates.indexOf(playbackRate.value) + 1) % rates.length] || 1
  playbackRate.value = next
  if (player.value) player.value.playbackRate = next
}

function updatePlayerMetadata() {
  if (!player.value) return
  player.value.muted = muted.value
  player.value.playbackRate = playbackRate.value
}

function updatePlaybackPosition() {
  clipCurrentTime.value = player.value?.currentTime || 0
}

function handlePlayerPlay() {
  if (activeItem.value?.video?.url) playing.value = true
}

function handlePlayerPause() {
  if (activeItem.value?.video?.url) playing.value = false
}

function seekChapter(event: Event) {
  const percentage = Number((event.target as HTMLInputElement).value)
  const target = totalDuration.value * percentage / 100
  const resumePlayback = playing.value
  let elapsed = 0
  const item = timelineItems.value.find(candidate => {
    elapsed += candidate.duration
    return target <= elapsed
  }) || timelineItems.value.at(-1)
  if (!item) return
  const localTime = Math.max(0, target - (elapsed - item.duration))
  selectTimelineItem(item, resumePlayback, localTime)
}

function toggleFullscreen() {
  const element = stage.value
  if (element && document.fullscreenElement !== element) void element.requestFullscreen()
  else if (document.fullscreenElement) void document.exitFullscreen()
}

function chapterDownloadFilename() {
  const projectName = project.value?.name || '短剧'
  const chapterTitle = stripChapterOrdinal(activeChapter.value?.name)
  const chapterName = activeChapter.value
    ? `第${activeChapter.value.number}集${chapterTitle ? `-${chapterTitle}` : ''}`
    : '当前集'
  const safeTitle = `${projectName}-${chapterName}-完整视频`.replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, ' ')
  return `${safeTitle}.mp4`
}

async function downloadCurrentChapterVideo() {
  const chapterId = activeChapter.value?.id
  if (!chapterId || playableItems.value.length === 0 || downloadingChapter.value) return
  downloadingChapter.value = true
  try {
    const result = (await api.mergeChapterVideos(chapterId)).data
    await downloadFile(mediaUrl(result.merged_url), chapterDownloadFilename())
    notice.success(`已按顺序合成并下载 ${result.video_count} 个分镜视频`)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '完整视频合成下载失败')
  } finally {
    downloadingChapter.value = false
  }
}

function returnToStoryboard(sceneId = activeSceneId.value) {
  void router.push({
    name: 'short-drama-storyboard',
    params: { projectId: projectId.value },
    query: { chapter: String(activeChapter.value?.id || ''), scene: sceneId > 0 ? String(sceneId) : undefined },
  })
}

watch(muted, value => {
  if (player.value) player.value.muted = value
})

watch(timelineScale, () => {
  void nextTick(() => revealPlayhead(true))
})

watch(chapterCurrentTime, () => {
  if (playing.value) void nextTick(() => revealPlayhead())
})

onMounted(load)
onUnmounted(() => gapPlaybackClock.stop())
</script>

<template>
  <main class="video-editor-page">
    <ShortDramaWorkspaceShell
      :project-id="projectId"
      :project-name="project?.name || '短剧项目'"
      :aspect-ratio="project?.aspectRatio || '9:16'"
      :resolution="project?.resolution || '720p'"
      :style-name="project?.style || '写实通用'"
      active-phase="video"
      :creation-mode="project?.creationMode || 'agent'"
      :chapters="chapters"
      :active-chapter-id="activeChapter?.id || 0"
      :video-enabled="videoEnabled"
      @select-chapter="selectChapter"
    >
      <template #header-end>
        <div class="video-header-actions">
          <AppButton variant="secondary" size="sm" @click="returnToStoryboard()"><Clapperboard :size="15" />返回分镜</AppButton>
          <AppButton variant="secondary" size="sm" :disabled="playableItems.length === 0 || downloadingChapter" :aria-busy="downloadingChapter" aria-label="合成并下载本集已有视频" title="合成并下载本集已有视频" @click="downloadCurrentChapterVideo"><LoaderCircle v-if="downloadingChapter" class="is-spinning" :size="15" /><Download v-else :size="15" />{{ downloadingChapter ? '正在合成' : '下载当前' }}</AppButton>
        </div>
      </template>

      <section class="video-editor-workspace">
        <div v-if="loading" class="video-page-state"><LoaderCircle class="is-spinning" :size="30" /><strong>正在加载本集视频</strong><span>准备分镜顺序和生成结果。</span></div>
        <div v-else-if="loadError" class="video-page-state is-error"><AlertTriangle :size="30" /><strong>视频工作区加载失败</strong><span>{{ loadError }}</span><AppButton variant="primary" size="sm" @click="load">重新加载</AppButton></div>
        <div v-else-if="!videoEnabled" class="video-page-state is-empty"><Film :size="34" /><strong>本集还没有可编辑的视频</strong><span>任意一个分镜视频生成成功后，即可进入视频编辑页。</span><AppButton variant="primary" size="sm" @click="returnToStoryboard()"><ChevronLeft :size="15" />返回分镜生成</AppButton></div>

        <template v-else>
          <section class="video-stage-card">
            <header class="video-stage-header">
              <div>
                <span>{{ activeChapter ? episodeDisplayLabel(activeChapter) : '当前集' }}</span>
                <strong>{{ activeItem ? sceneLabel(activeItem) : '选择分镜' }}</strong>
                <small v-if="activeItem?.scene.description">{{ activeItem.scene.description }}</small>
              </div>
              <AppButton variant="primary" size="sm" @click="returnToStoryboard(activeSceneId)"><Scissors :size="15" />编辑分镜</AppButton>
            </header>

            <div ref="stage" class="video-stage" :class="{ 'has-video': Boolean(activeItem?.video?.url), 'is-blackout': Boolean(activeItem && !activeItem.video?.url) }">
              <video
                v-if="activeItem?.video?.url"
                ref="player"
                :key="activeItem.video.id"
                :src="activeItem.video.url"
                :poster="activeItem.coverUrl || undefined"
                preload="metadata"
                playsinline
                :aria-label="`${sceneLabel(activeItem)} 视频预览`"
                @loadedmetadata="updatePlayerMetadata"
                @timeupdate="updatePlaybackPosition"
                @play="handlePlayerPlay"
                @pause="handlePlayerPause"
                @ended="advanceTimeline(true)"
                @click="togglePlayback"
              />
              <div v-else class="video-stage-blackout" role="img" :aria-label="activeItem ? `${sceneLabel(activeItem)}无视频，使用黑屏占位` : '黑屏占位'" />

              <div v-if="activeItem?.video?.url" class="video-stage-overlay">
                <AppButton variant="dark" size="sm" icon-only :aria-label="muted ? '打开声音' : '静音'" :title="muted ? '打开声音' : '静音'" @click="muted = !muted"><VolumeX v-if="muted" :size="16" /><Volume2 v-else :size="16" /></AppButton>
                <AppButton variant="dark" size="sm" :aria-label="`播放速度 ${playbackRate} 倍`" @click="cyclePlaybackRate">{{ playbackRate }}x</AppButton>
                <AppButton variant="dark" size="sm" icon-only :disabled="downloadingChapter" :aria-busy="downloadingChapter" aria-label="合成并下载本集已有视频" title="合成并下载本集已有视频" @click="downloadCurrentChapterVideo"><LoaderCircle v-if="downloadingChapter" class="is-spinning" :size="16" /><ArrowDownToLine v-else :size="16" /></AppButton>
                <AppButton variant="dark" size="sm" icon-only aria-label="全屏预览" title="全屏预览" @click="toggleFullscreen"><Maximize2 :size="16" /></AppButton>
              </div>
            </div>

            <footer class="video-player-controls">
              <div class="video-player-buttons">
                <AppButton variant="ghost" size="sm" icon-only aria-label="上一个分镜" :disabled="!canGoPrevious" @click="previousClip"><SkipBack :size="17" /></AppButton>
                <AppButton class="video-play-button" variant="dark" size="lg" icon-only :aria-label="playing ? '暂停' : '播放'" :disabled="!activeItem" @click="togglePlayback"><Pause v-if="playing" :size="18" fill="currentColor" /><Play v-else :size="18" fill="currentColor" /></AppButton>
                <AppButton variant="ghost" size="sm" icon-only aria-label="下一个分镜" :disabled="!canGoNext" @click="nextClip()"><SkipForward :size="17" /></AppButton>
              </div>
              <span>{{ formatTime(chapterCurrentTime) }} <i>/</i> {{ formatTime(totalDuration) }}</span>
              <input type="range" min="0" max="100" step="0.1" :value="progressPercent" aria-label="本集视频播放进度" @input="seekChapter" />
            </footer>
          </section>

          <section class="video-timeline" aria-label="本集分镜视频时间线">
            <header>
              <div><strong>本集时间线</strong><span>{{ playableItems.length }}/{{ timelineItems.length }} 条可用</span></div>
              <small>缺失和异常分镜会保留位置，可随时返回补充生成。</small>
            </header>
            <div class="video-timeline-body">
              <div class="video-timeline-scale" aria-label="时间轴刻度缩放">
                <button type="button" aria-label="放大时间轴刻度" :disabled="timelineScale >= MAX_TIMELINE_SCALE" @click="setTimelineScale(timelineScale + 1)"><ZoomIn :size="15" /></button>
                <input v-model.number="timelineScale" type="range" :min="MIN_TIMELINE_SCALE" :max="MAX_TIMELINE_SCALE" step="1" aria-label="时间轴刻度尺寸" :aria-valuetext="`刻度 ${timelineScale}`" />
                <output>{{ timelineScale }}</output>
                <button type="button" aria-label="缩小时间轴刻度" :disabled="timelineScale <= MIN_TIMELINE_SCALE" @click="setTimelineScale(timelineScale - 1)"><ZoomOut :size="15" /></button>
              </div>
              <div ref="timelineScroll" class="video-timeline-scroll">
                <div class="video-timeline-canvas" :style="{ '--timeline-width': `${timelineContentWidth}px` }">
                  <div class="video-timeline-ruler" aria-hidden="true">
                    <i
                      v-for="tick in timelineRulerTicks"
                      :key="tick.second"
                      :class="{ 'is-major': tick.isMajor, 'is-middle': tick.isMiddle }"
                      :style="timelineTickStyle(tick.second)"
                    ><small v-if="tick.isMajor">{{ formatTime(tick.second) }}</small></i>
                  </div>
                  <div class="video-timeline-track">
                    <button
                      v-for="item in timelineItems"
                      :key="item.scene.id"
                      type="button"
                      class="video-timeline-clip"
                      :class="[`is-${item.state}`, { 'is-active': activeSceneId === item.scene.id }]"
                      :style="timelineClipStyle(item)"
                      :aria-current="activeSceneId === item.scene.id ? 'true' : undefined"
                      :aria-label="`${sceneLabel(item)}，${statusLabel(item)}`"
                      @click="selectTimelineItem(item)"
                    >
                      <span class="video-timeline-copy"><strong>{{ sceneLabel(item) }}</strong><small>{{ formatTime(item.duration) }}</small></span>
                      <span class="video-timeline-thumb">
                        <video v-if="item.video?.url" :src="item.video.url" :poster="item.coverUrl || undefined" preload="metadata" muted playsinline />
                        <template v-else-if="item.state === 'failed'"><AlertTriangle :size="23" /><em>生成失败</em></template>
                        <template v-else-if="item.state === 'generating'"><LoaderCircle class="is-spinning" :size="23" /><em>生成中</em></template>
                        <template v-else><Film :size="23" /><em>待生成</em></template>
                      </span>
                    </button>
                  </div>
                  <span class="video-timeline-playhead" :style="playheadStyle()" aria-hidden="true"><i /></span>
                </div>
              </div>
            </div>
          </section>
        </template>
      </section>
    </ShortDramaWorkspaceShell>
  </main>
</template>

<style scoped>
.video-editor-page { min-height: 100vh; color: var(--app-text); background: var(--app-bg); }
.video-header-actions { display: flex; align-items: center; gap: 8px; }
.video-editor-workspace { display: grid; height: calc(100vh - 72px); min-height: 0; overflow: hidden; grid-template-rows: minmax(0,1fr) auto; gap: 14px; padding: 18px 22px 20px; }
.video-page-state { display: grid; min-height: calc(100vh - 150px); place-content: center; justify-items: center; gap: 10px; padding: 40px; color: var(--app-text-muted); text-align: center; }
.video-page-state strong { color: var(--app-text); font-size: 17px; }
.video-page-state span { max-width: 460px; font-size: 12px; line-height: 1.7; }
.video-page-state.is-error { color: #d75464; }
.video-page-state.is-empty svg { color: var(--app-accent); }
.is-spinning { animation: video-spin .9s linear infinite; }

.video-stage-card { display: grid; min-height: 0; overflow: hidden; grid-template-rows: auto minmax(230px,1fr) auto; border: 1px solid var(--app-border); border-radius: 18px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.video-stage-header { display: flex; min-height: 68px; align-items: center; justify-content: space-between; gap: 18px; padding: 12px 16px; border-bottom: 1px solid var(--app-border); }
.video-stage-header > div { display: grid; min-width: 0; grid-template-columns: auto auto minmax(0,1fr); align-items: center; gap: 8px; }
.video-stage-header span { color: var(--app-accent); font-size: 11px; font-weight: 700; }
.video-stage-header strong { font-size: 14px; }
.video-stage-header small { overflow: hidden; color: var(--app-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.video-stage { position: relative; display: grid; min-height: 0; place-items: center; overflow: hidden; background: #090a0d; }
.video-stage video { width: 100%; height: 100%; min-width: 0; min-height: 0; object-fit: contain; cursor: pointer; }
.video-stage-blackout { width: 100%; height: 100%; min-height: 230px; background: #000; }
.video-stage-overlay { position: absolute; right: 14px; bottom: 14px; display: flex; gap: 7px; opacity: .24; transition: opacity .16s ease,transform .16s ease; transform: translateY(4px); }
.video-stage:hover .video-stage-overlay,.video-stage:focus-within .video-stage-overlay { opacity: 1; transform: translateY(0); }
.video-player-controls { display: grid; grid-template-columns: auto auto minmax(160px,1fr); align-items: center; gap: 16px; min-height: 64px; padding: 9px 16px; border-top: 1px solid var(--app-border); background: var(--app-surface-raised); }
.video-player-buttons { display: flex; align-items: center; gap: 5px; }
.video-play-button { border-radius: 999px !important; }
.video-player-controls > span { color: var(--app-text-secondary); font-variant-numeric: tabular-nums; font-size: 12px; white-space: nowrap; }
.video-player-controls > span i { color: var(--app-text-muted); font-style: normal; }
.video-player-controls input { width: 100%; accent-color: var(--app-accent); cursor: pointer; }

.video-timeline { display: grid; min-width: 0; gap: 10px; padding: 13px 14px 14px; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.video-timeline > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.video-timeline > header > div { display: flex; align-items: baseline; gap: 9px; }
.video-timeline > header strong { font-size: 13px; }
.video-timeline > header span,.video-timeline > header small { color: var(--app-text-muted); font-size: 10px; }
.video-timeline-body { display: grid; min-width: 0; grid-template-columns: 30px minmax(0,1fr); align-items: stretch; gap: 8px; }
.video-timeline-scale { position: relative; display: flex; min-height: 130px; flex-direction: column; align-items: center; justify-content: space-between; color: var(--app-text-muted); }
.video-timeline-scale button { display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center; padding: 0; border: 0; border-radius: 7px; color: var(--app-text-secondary); background: transparent; cursor: pointer; }
.video-timeline-scale button:hover:not(:disabled),.video-timeline-scale button:focus-visible { color: var(--app-accent); background: var(--app-accent-soft); }
.video-timeline-scale button:disabled { opacity: .3; cursor: not-allowed; }
.video-timeline-scale input { width: 16px; min-height: 64px; flex: 1; margin: 3px 0; accent-color: var(--app-accent); cursor: ns-resize; direction: rtl; writing-mode: vertical-lr; appearance: slider-vertical; }
.video-timeline-scale output { position: absolute; top: 24px; left: 25px; z-index: 2; min-width: 24px; padding: 3px 5px; border: 1px solid var(--app-border); border-radius: 6px; color: var(--app-text-secondary); background: var(--app-surface-raised); box-shadow: var(--app-shadow); font-size: 9px; font-variant-numeric: tabular-nums; text-align: center; opacity: 0; transform: translateX(-3px); transition: opacity .14s ease,transform .14s ease; pointer-events: none; }
.video-timeline-scale:focus-within output,.video-timeline-scale:hover output { opacity: 1; transform: translateX(0); }
.video-timeline-scroll { min-width: 0; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }
.video-timeline-scroll::-webkit-scrollbar { display: none; }
.video-timeline-canvas { position: relative; width: max(100%,var(--timeline-width)); min-width: var(--timeline-width); padding-top: 25px; }
.video-timeline-ruler { position: absolute; top: 0; right: 0; left: 0; height: 21px; border-bottom: 1px solid var(--app-border); color: var(--app-text-muted); }
.video-timeline-ruler > i { position: absolute; bottom: 0; width: 1px; height: 5px; background: var(--app-border-strong); }
.video-timeline-ruler > i.is-middle { height: 8px; }
.video-timeline-ruler > i.is-major { height: 11px; background: var(--app-text-muted); }
.video-timeline-ruler small { position: absolute; bottom: 7px; left: 4px; font-size: 9px; font-style: normal; font-variant-numeric: tabular-nums; white-space: nowrap; }
.video-timeline-track { display: flex; width: var(--timeline-width); min-width: var(--timeline-width); gap: 0; }
.video-timeline-clip { display: grid; min-width: 0; flex: 0 0 auto; grid-template-rows: auto 88px; gap: 7px; overflow: hidden; padding: 9px; border: 1px solid var(--app-border); border-radius: 12px; outline: 0; color: var(--app-text); background: var(--app-surface-raised); cursor: pointer; text-align: left; transition: border-color .16s ease,box-shadow .16s ease; }
.video-timeline-clip:hover { border-color: var(--app-border-strong); }
.video-timeline-clip.is-active,.video-timeline-clip:focus-visible { border-color: var(--app-accent); box-shadow: inset 0 0 0 2px var(--app-accent-soft); }
.video-timeline-copy { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; }
.video-timeline-copy strong { overflow: hidden; min-width: 0; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.video-timeline-copy small { color: var(--app-text-muted); font-size: 9px; font-variant-numeric: tabular-nums; }
.video-timeline-thumb { display: grid; overflow: hidden; place-items: center; border-radius: 8px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.video-timeline-thumb video { width: 100%; height: 100%; object-fit: cover; }
.video-timeline-thumb em { margin-top: -18px; font-size: 10px; font-style: normal; }
.video-timeline-clip.is-failed .video-timeline-thumb { color: #df596c; background: color-mix(in srgb,#ef5c70 9%,var(--app-surface-muted)); }
.video-timeline-clip.is-generating .video-timeline-thumb { color: var(--app-accent); }
.video-timeline-playhead { position: absolute; z-index: 4; top: 14px; bottom: 0; width: 1px; background: color-mix(in srgb,var(--app-text) 72%,transparent); pointer-events: none; }
.video-timeline-playhead > i { position: absolute; top: 0; left: -3px; width: 7px; height: 7px; border-radius: 1px 1px 3px 3px; background: var(--app-text); }

@keyframes video-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .is-spinning { animation-duration: 1.8s; } .video-stage-overlay,.video-timeline-clip { transition: none; } }
@media (max-width: 900px) {
  .video-editor-workspace { height: auto; min-height: calc(100vh - 124px); overflow: visible; padding: 12px; }
  .video-stage-card { grid-template-rows: auto minmax(280px,1fr) auto; }
  .video-player-controls { grid-template-columns: auto 1fr; }
  .video-player-controls input { grid-column: 1 / -1; }
  .video-timeline > header small { display: none; }
}
</style>
