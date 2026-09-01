<script setup lang="ts">
import { computed, ref } from 'vue';
import DeferredVideoPlayer from '@/components/DeferredVideoPlayer.vue';
import { parseMediaAspectRatio } from '../graph/mediaAspectRatio';
import WorkbenchMediaResultState from './WorkbenchMediaResultState.vue';

const props = withDefaults(defineProps<{
  src?: string;
  poster?: string;
  title: string;
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
  ratio: '',
  running: false,
  failed: false,
  error: '',
  progress: 0,
  emptyLabel: '视频结果尚未就绪',
  runningLabel: '正在生成视频',
  failureLabel: '视频生成失败',
});
const emit = defineEmits<{
  metadata: [value: { width: number; height: number }];
}>();

const measuredWidth = ref(0);
const measuredHeight = ref(0);

const displayRatio = computed<[number, number]>(() => {
  if (measuredWidth.value > 0 && measuredHeight.value > 0)
    return [measuredWidth.value, measuredHeight.value];
  return parseMediaAspectRatio(props.ratio) ?? [16, 9];
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
  if (video.videoWidth > 0 && video.videoHeight > 0)
    emit('metadata', { width: video.videoWidth, height: video.videoHeight });
}
</script>

<template>
  <div class="workbench-video-media workbench-video-result" :class="ratioClass">
    <DeferredVideoPlayer
      v-if="src"
      :src="src"
      :poster="poster"
      :title="title"
      :aspect-ratio="mediaStyle.aspectRatio"
      draggable="false"
      @loadedmetadata="captureVideoRatio"
    />
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
  </div>
</template>
