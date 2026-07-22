<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next'
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  running?: boolean
  failed?: boolean
  error?: string | null
  progress?: number
  runningLabel: string
  failureLabel: string
  emptyLabel: string
  aspectRatio?: string
}>(), {
  running: false,
  failed: false,
  error: '',
  progress: 0,
  aspectRatio: '16 / 9',
})

const normalizedProgress = computed(() => Math.min(100, Math.max(0, Number(props.progress) || 0)))
</script>

<template>
  <div class="workbench-media-placeholder" :class="{ 'is-generating': running, 'is-failed': failed }" :style="{ aspectRatio }" :role="failed ? 'alert' : 'status'" :aria-live="failed ? 'assertive' : 'polite'">
    <div class="workbench-media-placeholder__state">
      <LoaderCircle v-if="running" class="workbench-media-placeholder__spinner" :size="34" aria-hidden="true" />
      <strong>{{ failed ? failureLabel : running ? runningLabel : emptyLabel }}</strong>
      <span v-if="failed && error" class="workbench-media-placeholder__error">{{ error }}</span>
      <span v-if="running">{{ Math.round(normalizedProgress) }}%</span>
    </div>
  </div>
</template>
