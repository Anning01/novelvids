<script setup lang="ts">
import { tr } from '@/i18n'
import AppSelect from '@/components/AppSelect.vue'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { XSender } from 'vue-element-plus-x'
import { ArrowUp, Square } from 'lucide-vue-next'
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
    editor.setAttribute('aria-label', tr('创作要求'))
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
    <XSender ref="sender" :placeholder="tr('说说你想怎么改…')" :custom-style="{ minHeight: '28px', maxHeight: '160px', padding: '4px 6px' }" :max-length="8000" :disabled="disabled || submitting" :loading="busy" submit-type="enter" :auto-focus="false" :tip-config="false" @change="changed" @submit="submit" @cancel="emit('stop')">
      <template #action-list><span /></template>
      <template #footer>
        <div class="agent-composer__tools">
          <div class="agent-composer__choices"><slot name="tools" />
            <AppSelect
              class="agent-composer__model"
              density="compact"
              :model-value="modelId"
              :options="models.length ? models.map(model => ({ value: String(model.id), label: model.name })) : [{ value: '', label: tr('尚无可用模型') }]"
              :ariaLabel="tr('助手模型')"
              :disabled="busy || submitting || !models.length"
              @update:model-value="emit('update:modelId', $event)"
            />
          </div>
          <AppButton v-if="busy" class="agent-composer__send" size="xs" variant="soft" icon-only :aria-label="tr('停止创作助手')" @click="emit('stop')"><Square :size="14" /></AppButton>
          <AppButton v-else class="agent-composer__send" size="xs" variant="primary" icon-only :aria-label="tr('发送创作要求')" :disabled="!canSend" @click="submit"><ArrowUp :size="18" /></AppButton>
        </div>
      </template>
    </XSender>
  </div>
</template>

<style scoped>
.agent-composer { min-width: 0; border: 1px solid var(--app-border-strong, var(--app-border)); border-radius: 12px; background: var(--app-surface); box-shadow: 0 2px 8px rgb(0 0 0 / 3%); transition: border-color .18s, box-shadow .18s; }
.agent-composer:focus-within { border-color: color-mix(in srgb, var(--app-accent) 45%, var(--app-border)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--app-accent) 7%, transparent); }
.agent-composer :deep(.elx-x-sender) { border: 0; border-radius: inherit; background: transparent; box-shadow: none; }
.agent-composer :deep(.elx-x-sender::after) { display: none; }
.agent-composer :deep(.elx-x-sender__content) { padding: 4px 6px 0; }
.agent-composer :deep(.elx-x-sender__chat-room) { min-height: 36px; }
.agent-composer :deep(.elx-x-sender__action-list) { display: none; }
.agent-composer :deep(.elx-x-sender__footer) { border: 0; }
.agent-composer :deep([contenteditable]) { color: var(--app-text); min-height: 28px; max-height: 160px; overflow-y: auto; font-size: 13px; font-weight: 400; line-height: 1.6; }
.agent-composer :deep(.chat-placeholder-wrap) { color: var(--app-text-muted) !important; font-weight: 400 !important; font-size: 14px; }
.agent-composer__tools { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 6px; padding: 2px 8px 6px; }
.agent-composer__choices { display: flex; min-width: 0; align-items: center; gap: 2px; }
.agent-composer__model { max-width: 160px; }
.agent-composer__send { border-radius: 50%; box-shadow: none; }
.agent-composer__send { min-width: 28px; min-height: 28px; width: 28px; height: 28px; transition: transform .18s cubic-bezier(.23,1,.32,1), background .15s; }
.agent-composer__send:active:not(:disabled) { transform: scale(.92); }
@media (prefers-reduced-motion: reduce) { .agent-composer, .agent-composer__send { transition: none; } }
</style>
