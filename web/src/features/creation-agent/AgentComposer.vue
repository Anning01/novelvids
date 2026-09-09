<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { XSender } from 'vue-element-plus-x'
import { ArrowUp, ChevronDown, Square } from 'lucide-vue-next'
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

function focus() { sender.value?.focus('last') }
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
    <slot name="context" />
    <XSender ref="sender" placeholder="说说你想怎么改…" :max-length="8000" :disabled="disabled || submitting" :loading="busy" submit-type="enter" :auto-focus="false" :tip-config="false" @change="changed" @submit="submit" @cancel="emit('stop')">
      <template #action-list><span /></template>
      <template #footer>
        <div class="agent-composer__tools">
          <div class="agent-composer__choices"><slot name="tools" />
            <label class="agent-composer__model">
              <select :value="modelId" aria-label="助手模型" :disabled="busy || submitting" @change="emit('update:modelId', ($event.target as HTMLSelectElement).value)">
                <option v-if="!models.length" value="">尚无可用模型</option>
                <option v-for="model in models" :key="model.id" :value="String(model.id)">{{ model.name }}</option>
              </select><ChevronDown :size="13" aria-hidden="true" />
            </label>
          </div>
          <AppButton v-if="busy" class="agent-composer__send" size="sm" variant="soft" icon-only aria-label="停止创作助手" @click="emit('stop')"><Square :size="14" /></AppButton>
          <AppButton v-else class="agent-composer__send" size="sm" variant="primary" icon-only aria-label="发送创作要求" :disabled="!canSend" @click="submit"><ArrowUp :size="18" /></AppButton>
        </div>
      </template>
    </XSender>
  </div>
</template>

<style scoped>
.agent-composer { min-width: 0; border: 1px solid var(--app-border-strong, var(--app-border)); border-radius: 16px; background: var(--app-surface); box-shadow: 0 3px 12px rgb(0 0 0 / 4%); transition: border-color .15s; }
.agent-composer:focus-within { border-color: color-mix(in srgb, var(--app-accent) 55%, var(--app-border)); }
.agent-composer :deep(.elx-x-sender) { border: 0; border-radius: inherit; background: transparent; box-shadow: none; }
.agent-composer :deep(.elx-x-sender::after) { display: none; }
.agent-composer :deep(.elx-x-sender__content) { padding: 4px 6px 0; }
.agent-composer :deep(.elx-x-sender__action-list) { display: none; }
.agent-composer :deep(.elx-x-sender__footer) { border: 0; }
.agent-composer :deep([contenteditable]) { color: var(--app-text); min-height: 68px; max-height: 180px; overflow-y: auto; font-size: 14px; font-weight: 400; line-height: 1.7; }
.agent-composer :deep(.chat-placeholder-wrap) { color: var(--app-text-muted) !important; font-weight: 400 !important; font-size: 14px; }
.agent-composer__tools { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 6px; padding: 4px 10px 10px; }
.agent-composer__choices { display: flex; min-width: 0; align-items: center; gap: 2px; }
.agent-composer__model { display: flex; min-width: 0; align-items: center; gap: 3px; padding: 0 7px; color: var(--app-text-secondary); border-radius: 8px; }
.agent-composer__model:hover { background: var(--app-surface-hover); }.agent-composer__model:focus-within { outline: 2px solid var(--app-accent); }
.agent-composer__model select { appearance: none; min-width: 0; max-width: 125px; height: 34px; padding: 0; border: 0; outline: 0; color: inherit; background: transparent; font: inherit; font-size: 12px; text-overflow: ellipsis; cursor: pointer; }
.agent-composer__model svg { flex-shrink: 0; pointer-events: none; }
.agent-composer__send { border-radius: 50%; box-shadow: none; }
</style>
