<script setup lang="ts">
import { computed, ref } from 'vue';
import WorkbenchMediaResultState from './WorkbenchMediaResultState.vue';

const props = withDefaults(defineProps<{
  src?: string;
  poster?: string;
  title: string;
  durationSeconds?: number;
  ratio?: string;
  running?: boolean;
  failed?: boolean;
  error?: string | null;
  progress?: number;
  emptyLabel?: string;
  runningLabel?: string;
  failureLabel?: string;
}>(), {
  src: '',
  poster: '',
  durationSeconds: 0,
  ratio: '',
  running: false,
  failed: false,
  error: '',
  progress: 0,
  emptyLabel: '视频结果尚未就绪',
  runningLabel: '正在生成镜头视频',
  failureLabel: '视频生成失败',
});

const measuredWidth = ref(0);
const measuredHeight = ref(0);

function parseRatio(value: string): [number, number] | null {
  const match = value.trim().match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/);
  if (!match)
    return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  return width > 0 && height > 0 ? [width, height] : null;
}

const displayRatio = computed<[number, number]>(() => {
  if (measuredWidth.value > 0 && measuredHeight.value > 0)
    return [measuredWidth.value, measuredHeight.value];
  return parseRatio(props.ratio) ?? [16, 9];
});
const ratioValue = computed(() => displayRatio.value[0] / displayRatio.value[1]);
const ratioClass = computed(() => ratioValue.value <= 0.8
  ? 'is-portrait'
  : ratioValue.value >= 1.25
    ? 'is-landscape'
    : 'is-square');
const mediaStyle = computed(() => ({
  aspectRatio: `${displayRatio.value[0]} / ${displayRatio.value[1]}`,
}));

function captureVideoRatio(event: Event) {
  const video = event.currentTarget as HTMLVideoElement;
  measuredWidth.value = video.videoWidth;
  measuredHeight.value = video.videoHeight;
}
</script>

<template>
  <div class="workbench-video-media workbench-video-result" :class="ratioClass">
    <video v-if="src" :src="src" :poster="poster || undefined" :style="mediaStyle" controls playsinline preload="metadata" :aria-label="title" @loadedmetadata="captureVideoRatio" />
    <WorkbenchMediaResultState
      v-else
      :running="running"
      :failed="failed"
      :error="error"
      :progress="progress"
      :running-label="runningLabel"
      :failure-label="failureLabel"
      :empty-label="emptyLabel"
      :aspect-ratio="mediaStyle.aspectRatio"
    />
    <small>{{ durationSeconds || '—' }} 秒</small>
  </div>
</template>
