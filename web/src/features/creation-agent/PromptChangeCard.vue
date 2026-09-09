<script setup lang="ts">
import { ref } from 'vue'
import { CornerUpLeft, LocateFixed } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import type { AgentChange, AgentChangeItem } from './types'

const props = defineProps<{ change: AgentChange; canUndo: boolean }>()
const emit = defineEmits<{ undo: [id: number]; locate: [target: AgentChangeItem] }>()
const expanded = ref(false)
function text(value: Record<string, unknown>) {
  return String(value.prompt ?? value.base_traits ?? '')
}
</script>

<template>
  <section class="prompt-change-card" :aria-label="`修改记录 ${props.change.id}`">
    <div class="prompt-change-card__heading">
      <span>{{ change.reverted_at ? '已撤销' : '已保存' }} · {{ change.changes.length }} 个对象</span>
      <AppButton size="xs" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起差异' : '查看差异' }}</AppButton>
    </div>
    <div v-if="expanded" class="prompt-change-card__details">
      <div v-for="target in change.changes" :key="`${target.kind}-${target.target_id}`">
        <AppButton size="xs" @click="emit('locate', target)"><LocateFixed :size="13" />{{ target.target_label || (target.kind === 'scene' ? '查看分镜' : '查看图片设定') }}</AppButton>
        <label>修改前</label><pre>{{ text(target.before) || '空提示词' }}</pre>
        <label>修改后</label><pre>{{ text(target.after) }}</pre>
      </div>
    </div>
    <AppButton v-if="!change.reverted_at && canUndo" size="xs" @click="emit('undo', change.id)"><CornerUpLeft :size="13" />撤销这次修改</AppButton>
  </section>
</template>

<style scoped>
.prompt-change-card { margin-top: 8px; padding: 10px; border: 1px solid var(--app-border); border-radius: 11px; background: var(--app-surface); font-size: 12px; }
.prompt-change-card__heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.prompt-change-card__details { margin: 10px 0; }
label { display: block; margin: 8px 0 4px; color: var(--app-text-secondary); }
pre { max-height: 240px; overflow: auto; margin: 0; padding: 8px; background: var(--app-surface-muted); white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; }
</style>
