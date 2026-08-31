<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Focus, X } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import ScenePromptEditor, { type ScenePromptMentionOption } from './ScenePromptEditor.vue'

const props = withDefaults(defineProps<{
  open: boolean
  sceneSequence: number
  modelValue: string
  options: ScenePromptMentionOption[]
  placeholder?: string
}>(), {
  placeholder: '请输入分镜视频提示词。描述镜头、主体动作、运镜、光线、画面风格和声音。',
})

const emit = defineEmits<{
  close: []
  'update:modelValue': [value: string]
}>()

const dialog = ref<HTMLElement | null>(null)
let previousActiveElement: HTMLElement | null = null
let previousBodyOverflow = ''

function close() {
  emit('close')
}

function focusableElements() {
  if (!dialog.value) return []
  return [...dialog.value.querySelectorAll<HTMLElement>([
    'button:not([disabled])',
    'a[href]',
    'input:not([disabled])',
    'textarea:not([disabled])',
    'select:not([disabled])',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(','))].filter(element => element.getAttribute('aria-hidden') !== 'true')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    if (event.defaultPrevented) return
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const elements = focusableElements()
  if (!elements.length) {
    event.preventDefault()
    dialog.value?.focus()
    return
  }
  const first = elements[0]!
  const last = elements.at(-1)!
  const active = document.activeElement
  if (event.shiftKey && (active === first || !dialog.value?.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !dialog.value?.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => props.open, async open => {
  if (open) {
    previousActiveElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    dialog.value?.querySelector<HTMLElement>('[contenteditable="true"]')?.focus()
    return
  }
  document.body.style.overflow = previousBodyOverflow
  await nextTick()
  previousActiveElement?.focus()
  previousActiveElement = null
}, { immediate: true })

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  previousActiveElement?.focus()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="scene-prompt-focus">
      <div v-if="open" class="scene-prompt-focus__backdrop" @pointerdown.self="close">
        <section
          ref="dialog"
          class="scene-prompt-focus"
          role="dialog"
          aria-modal="true"
          aria-labelledby="scene-prompt-focus-title"
          tabindex="-1"
          @keydown="handleKeydown"
        >
          <header class="scene-prompt-focus__header">
            <span class="scene-prompt-focus__icon"><Focus :size="19" /></span>
            <div>
              <span>FOCUS MODE</span>
              <h2 id="scene-prompt-focus-title">分镜 {{ sceneSequence }} · 专注编辑</h2>
            </div>
            <kbd>Esc</kbd>
            <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="退出专注编辑" title="退出专注编辑" @click="close"><X :size="18" /></AppButton>
          </header>

          <main class="scene-prompt-focus__body">
            <ScenePromptEditor
              :model-value="modelValue"
              :options="options"
              :placeholder="placeholder"
              focus-mode
              @update:model-value="emit('update:modelValue', $event)"
            />
          </main>

          <footer class="scene-prompt-focus__footer">
            <span>输入 <kbd>@</kbd> 可继续引用角色、场景、道具与素材</span>
            <span>{{ modelValue.length.toLocaleString() }} 字符 · 修改自动保存</span>
            <AppButton type="button" variant="primary" size="sm" @click="close">完成编辑</AppButton>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.scene-prompt-focus__backdrop { position: fixed; inset: 0; z-index: 160; display: grid; place-items: center; padding: 28px; background: rgb(24 27 38 / 58%); backdrop-filter: blur(12px); }
.scene-prompt-focus { display: grid; width: min(1180px,100%); height: min(840px,calc(100dvh - 56px)); min-height: 460px; grid-template-rows: auto minmax(0,1fr) auto; overflow: hidden; border: 1px solid color-mix(in srgb,var(--app-border) 86%,transparent); border-radius: 22px; outline: 0; color: var(--app-text); background: var(--app-surface); box-shadow: 0 40px 120px rgb(12 16 30 / 36%); }
.scene-prompt-focus__header { display: grid; min-height: 78px; grid-template-columns: 44px minmax(0,1fr) auto 34px; align-items: center; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--app-border); background: linear-gradient(135deg,color-mix(in srgb,var(--app-surface) 94%,var(--app-accent)),var(--app-surface)); }
.scene-prompt-focus__icon { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 14px; color: var(--app-accent); background: var(--app-surface); box-shadow: inset 0 0 0 1px var(--app-border),0 8px 22px rgb(72 75 160 / 10%); }
.scene-prompt-focus__header > div { min-width: 0; }
.scene-prompt-focus__header > div > span { color: var(--app-accent); font-size: 8px; font-weight: 800; letter-spacing: .14em; }
.scene-prompt-focus__header h2 { margin: 4px 0 0; overflow: hidden; font-size: 18px; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.scene-prompt-focus__header > kbd { padding: 4px 7px; border-radius: 6px; color: var(--app-text-muted); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); font: inherit; font-size: 9px; }
.scene-prompt-focus__body { min-height: 0; overflow: hidden; padding: 14px 18px; background: color-mix(in srgb,var(--app-surface-muted) 72%,var(--app-surface)); }
.scene-prompt-focus__body :deep(.scene-prompt-editor) { border-radius: 15px; background: var(--app-surface); box-shadow: inset 0 0 0 1px var(--app-border),0 10px 30px rgb(22 27 45 / 4%); }
.scene-prompt-focus__body :deep(.scene-prompt-editor:focus-within) { box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 48%,var(--app-border)),0 0 0 3px color-mix(in srgb,var(--app-accent) 8%,transparent); }
.scene-prompt-focus__footer { display: grid; min-height: 66px; grid-template-columns: minmax(0,1fr) auto auto; align-items: center; gap: 18px; padding: 10px 18px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); background: var(--app-surface); font-size: 10px; }
.scene-prompt-focus__footer > span:first-child { color: var(--app-text-secondary); }
.scene-prompt-focus__footer kbd { padding: 2px 5px; border-radius: 5px; color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px var(--app-border); font: inherit; font-weight: 750; }
.scene-prompt-focus-enter-active,.scene-prompt-focus-leave-active { transition: opacity .2s ease; }
.scene-prompt-focus-enter-active .scene-prompt-focus,.scene-prompt-focus-leave-active .scene-prompt-focus { transition: transform .24s cubic-bezier(.2,.72,.2,1),opacity .2s ease; }
.scene-prompt-focus-enter-from,.scene-prompt-focus-leave-to { opacity: 0; }
.scene-prompt-focus-enter-from .scene-prompt-focus,.scene-prompt-focus-leave-to .scene-prompt-focus { opacity: 0; transform: translateY(10px) scale(.985); }
@media (max-width: 720px) {
  .scene-prompt-focus__backdrop { padding: 8px; }
  .scene-prompt-focus { width: 100%; height: calc(100dvh - 16px); min-height: 0; border-radius: 17px; }
  .scene-prompt-focus__header { min-height: 68px; grid-template-columns: 38px minmax(0,1fr) 34px; padding: 10px 12px; }
  .scene-prompt-focus__icon { width: 38px; height: 38px; border-radius: 12px; }
  .scene-prompt-focus__header > kbd { display: none; }
  .scene-prompt-focus__header h2 { font-size: 16px; }
  .scene-prompt-focus__body { padding: 8px; }
  .scene-prompt-focus__body :deep(.scene-prompt-editor__input) { padding: 18px 16px 32px; font-size: 13px; }
  .scene-prompt-focus__footer { min-height: 58px; grid-template-columns: minmax(0,1fr) auto; gap: 10px; padding: 8px 10px; }
  .scene-prompt-focus__footer > span:first-child { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .scene-prompt-focus-enter-active,.scene-prompt-focus-leave-active,.scene-prompt-focus-enter-active .scene-prompt-focus,.scene-prompt-focus-leave-active .scene-prompt-focus { transition-duration: .01ms; }
}
</style>
