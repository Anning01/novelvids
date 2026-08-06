<script setup lang="ts">
import { AlertTriangle, CheckCircle2, LoaderCircle, X } from 'lucide-vue-next';
import { computed, ref, watch } from 'vue';
import { dismissWorkbenchNotice, isWorkbenchNoticeDismissed } from '../interaction/dismissedNotices';

const props = defineProps<{
  status?: string;
  progress?: number;
  error?: string | null;
  noticeKey?: string;
}>();

const normalizedStatus = computed(() => props.status?.toUpperCase() ?? 'IDLE');
const running = computed(() => ['PENDING', 'RUNNING'].includes(normalizedStatus.value));
const failed = computed(() => normalizedStatus.value === 'FAILED');
const failureKey = computed(() => failed.value ? props.noticeKey || `${normalizedStatus.value}:${props.error || ''}` : '');
const dismissedFailure = ref(false);
const visible = computed(() => !failed.value || !dismissedFailure.value);
watch(failureKey, key => dismissedFailure.value = isWorkbenchNoticeDismissed(key), { immediate: true });
function dismissFailure() {
  dismissedFailure.value = true;
  dismissWorkbenchNotice(failureKey.value);
}
const label = computed(() => {
  if (failed.value)
    return props.error || '运行失败';
  if (running.value)
    return `运行中 ${Math.round(props.progress ?? 0)}%`;
  if (normalizedStatus.value === 'SUCCEEDED')
    return '最近运行已完成';
  return '画布已就绪';
});
</script>

<template>
  <div
    v-if="visible"
    class="workbench-run-status"
    :class="{ 'is-error': failed }"
    :role="failed ? 'alert' : 'status'"
    :aria-live="failed ? 'assertive' : 'polite'"
  >
    <LoaderCircle v-if="running" class="workbench-run-status__spinner" :size="15" aria-hidden="true" />
    <AlertTriangle v-else-if="failed" :size="17" aria-hidden="true" />
    <CheckCircle2 v-else :size="15" aria-hidden="true" />
    <span>{{ label }}</span>
    <button v-if="failed" type="button" class="workbench-message-close" aria-label="关闭运行异常提示" @click="dismissFailure">
      <X :size="16" aria-hidden="true" />
    </button>
  </div>
</template>
