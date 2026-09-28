<script setup lang="ts">
import { tr } from '@/i18n'

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
  get queued() { return tr('等待任务调度') },
  get preparing() { return tr('准备来源视频') },
  get extracting_assets() { return tr('提取人物、场景与道具') },
  get detecting_scenes() { return tr('检测镜头切分') },
  get generating_storyboards() { return tr('生成分镜描述') },
  get persisting() { return tr('写入设定和分镜') },
  get completed() { return tr('拆解完成') },
  get failed() { return tr('拆解失败') },
}
const stageLabel = computed(() => stageLabels[task.value.stage || ''] || tr('分析来源视频'))

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
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'ai_decomposition', title: tr('AI 视频拆解'), status: failed ? 'failed' : 'running' }">
    <div class="workbench-remake-analysis" :class="{ 'is-failed': failed }">
      <div class="workbench-remake-analysis__hero">
        <span><AlertTriangle v-if="failed" :size="20" aria-hidden="true" /><LoaderCircle v-else :size="20" class="is-spinning" aria-hidden="true" /></span>
        <div><strong>{{ stageLabel }}</strong><small>{{ failed ? tr('本次结果未写入画布，可安全重试') : tr('页面关闭后任务仍会继续') }}</small></div>
        <b>{{ progress }}%</b>
      </div>
      <div class="workbench-remake-analysis__progress" role="progressbar" :aria-label="tr('拆解进度')" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="progress">
        <i :style="{ width: `${progress}%` }" />
      </div>
      <p v-if="failed" role="alert">{{ task.error_message || tr('视频拆解失败，请重试') }}</p>
      <button v-if="failed" type="button" :disabled="retrying" @click="retry">
        <RefreshCw v-if="!retrying" :size="14" aria-hidden="true" /><Sparkles v-else :size="14" aria-hidden="true" />
        {{ retrying ? tr('正在重试…') : tr('重新拆解') }}
      </button>
    </div>
  </WorkbenchNodeFrame>
</template>
