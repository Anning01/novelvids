<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { AlertTriangle, LoaderCircle, RefreshCw, Sparkles } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { TaskStatusEnum, type WorkbenchRemakeTask } from '@/types'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const retrying = ref(false)
const task = computed(() => props.data.task as WorkbenchRemakeTask)
const progress = computed(() => Math.max(0, Math.min(100, Number(task.value.progress) || 0)))
const failed = computed(() => [TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(task.value.status))
const stageLabels: Record<string, string> = {
  queued: '等待任务调度',
  preparing: '准备来源视频',
  extracting_assets: '提取人物、场景与道具',
  detecting_scenes: '检测镜头切分',
  generating_storyboards: '生成分镜描述',
  persisting: '写入设定和分镜',
  completed: '拆解完成',
  failed: '拆解失败',
}
const stageLabel = computed(() => stageLabels[task.value.stage || ''] || '分析来源视频')

async function retry() {
  if (retrying.value) return
  retrying.value = true
  try {
    await store.retryRemakeAnalysis()
  } finally {
    retrying.value = false
  }
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'ai_decomposition', title: 'AI 视频拆解', status: failed ? 'failed' : 'running' }">
    <div class="workbench-remake-analysis" :class="{ 'is-failed': failed }">
      <div class="workbench-remake-analysis__hero">
        <span><AlertTriangle v-if="failed" :size="20" aria-hidden="true" /><LoaderCircle v-else :size="20" class="is-spinning" aria-hidden="true" /></span>
        <div><strong>{{ stageLabel }}</strong><small>{{ failed ? '本次结果未写入画布，可安全重试' : '页面关闭后任务仍会继续' }}</small></div>
        <b>{{ progress }}%</b>
      </div>
      <div class="workbench-remake-analysis__progress" role="progressbar" aria-label="拆解进度" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="progress">
        <i :style="{ width: `${progress}%` }" />
      </div>
      <p v-if="failed" role="alert">{{ task.error_message || '视频拆解失败，请重试' }}</p>
      <button v-if="failed" type="button" :disabled="retrying" @click="retry">
        <RefreshCw v-if="!retrying" :size="14" aria-hidden="true" /><Sparkles v-else :size="14" aria-hidden="true" />
        {{ retrying ? '正在重试…' : '重新拆解' }}
      </button>
    </div>
  </WorkbenchNodeFrame>
</template>
