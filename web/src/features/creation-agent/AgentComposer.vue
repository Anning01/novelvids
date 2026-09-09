<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { XSender } from 'vue-element-plus-x'
import { ArrowUp, Sparkles, Square } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import type { AgentCapabilities } from './types'

const props = defineProps<{
  modelValue: string
  modelId: string
  models: AgentCapabilities['models']
  disabled: boolean
  busy: boolean
  submitting: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:modelId': [value: string]
  submit: [text: string]
  stop: []
}>()
const root = ref<HTMLElement | null>(null)
const sender = ref<InstanceType<typeof XSender> | null>(null)
const canSend = computed(() => !props.disabled && !props.busy && !props.submitting && Boolean(props.modelId && props.modelValue.trim()))
let observer: MutationObserver | null = null
let ready = false
let restoring = false

function changed() {
  if (ready && !restoring) emit('update:modelValue', sender.value?.getModelValue().text ?? '')
}

async function restore() {
  const editor = sender.value?.getSender()
  if (!ready || !editor || restoring || sender.value?.getModelValue().text === props.modelValue) return
  restoring = true
  try {
    // setText inserts at the caret. Reset replaces content and clears the previous
    // conversation's undo history without emitting its temporary empty state.
    while (ready) {
      const text = props.modelValue
      await editor.reset({ clearHistory: true, chatNode: text.split('\n').map(line => [{ type: 'Write', text: line }]) })
      if (props.modelValue === text) break
    }
  } finally {
    restoring = false
  }
}

function submit() {
  if (canSend.value) emit('submit', props.modelValue.trim())
}

function focus() { sender.value?.focus('end') }
defineExpose({ focus })
watch(() => props.modelValue, restore)

onMounted(async () => {
  await nextTick()
  // The library creates its editor asynchronously and has no accessible input props.
  function initialize() {
    const editor = root.value?.querySelector('[contenteditable]')
    if (!editor || !sender.value?.getSender()) return
    editor.setAttribute('role', 'textbox')
    editor.setAttribute('aria-label', '创作要求')
    editor.setAttribute('aria-multiline', 'true')
    ready = true
    observer?.disconnect()
    restore()
  }
  observer = new MutationObserver(initialize)
  if (root.value) observer.observe(root.value, { childList: true, subtree: true, attributes: true, attributeFilter: ['contenteditable'] })
  initialize()
})
onBeforeUnmount(() => { ready = false; observer?.disconnect() })
</script>

<template>
  <div ref="root" class="agent-composer">
    <XSender ref="sender" placeholder="描述你希望调整的画面…" :max-length="8000" :disabled="disabled || submitting" :loading="busy" submit-type="enter" :auto-focus="false" :tip-config="false" @change="changed" @submit="submit" @cancel="emit('stop')">
      <template #action-list>
        <AppButton v-if="busy" size="sm" icon-only aria-label="停止创作助手" @click="emit('stop')"><Square :size="15" /></AppButton>
        <AppButton v-else size="sm" variant="primary" icon-only aria-label="发送创作要求" :disabled="!canSend" @click="submit"><ArrowUp :size="17" /></AppButton>
      </template>
      <template #footer>
        <div class="agent-composer__tools">
          <label class="agent-composer__model">
            <Sparkles :size="13" aria-hidden="true" />
            <select :value="modelId" aria-label="助手模型" :disabled="busy || submitting" @change="emit('update:modelId', ($event.target as HTMLSelectElement).value)">
              <option v-if="!models.length" value="">尚无可用模型</option>
              <option v-for="model in models" :key="model.id" :value="String(model.id)">{{ model.name }}</option>
            </select>
          </label>
          <span title="Enter 发送，Shift + Enter 换行">Enter 发送 · ⇧ 换行</span>
        </div>
      </template>
    </XSender>
  </div>
</template>

<style scoped>
.agent-composer :deep(.elx-x-sender) { overflow: hidden; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); box-shadow: 0 4px 16px rgb(35 39 55 / 6%); }
.agent-composer :deep(.elx-x-sender:focus-within) { border-color: color-mix(in srgb,var(--app-accent) 52%,var(--app-border)); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.agent-composer :deep(.elx-x-sender::after) { display: none; }
.agent-composer :deep(.elx-x-sender__footer) { border-top-color: var(--app-border); }
.agent-composer :deep([contenteditable]) { color: var(--app-text); min-height: 48px; max-height: 160px; overflow-y: auto; font-size: 13px; font-weight: 400; line-height: 1.7; }
.agent-composer__tools { display: flex; min-width: 0; min-height: 38px; align-items: center; justify-content: space-between; gap: 6px; padding: 5px 10px; }
.agent-composer__model { display: flex; min-width: 0; max-width: 55%; align-items: center; gap: 5px; padding: 0 6px; border-radius: 7px; color: var(--app-text-secondary); background: var(--app-surface-muted); }
.agent-composer__model select { min-width: 0; max-width: 100%; height: 27px; border: 0; color: inherit; background: transparent; font: inherit; font-size: 11px; text-overflow: ellipsis; }
.agent-composer__tools > span { color: var(--app-text-muted); font-size: 10px; white-space: nowrap; }
</style>
