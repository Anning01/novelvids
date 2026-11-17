<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Plus } from 'lucide-vue-next'
import type Vditor from 'vditor'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import type { TextTask } from './skillsApi'
import { loadVditor } from './vditorLoader'
import { atomicSelection, placeholderRanges, splitsPlaceholder, type TextSelection } from './placeholderEditing'

const props = withDefaults(defineProps<{ modelValue: string; disabled?: boolean; task?: TextTask; markdown?: boolean; label?: string }>(), { markdown: true })
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const host = ref<HTMLElement>()
const surface = ref<HTMLElement>()
const loading = ref(true)
const failed = ref(false)
const blocked = ref(false)
const variables = computed(() => [
  { key: 'input', label: tr('输入素材') }, { key: 'language', label: tr('输出语言') },
  ...(['screenplay', 'storyboard'].includes(props.task ?? '') ? [
    { key: 'episode_pacing', label: tr('本集节奏') }, { key: 'max_seconds', label: tr('参考时长') },
  ] : []),
])
let instance: Vditor | undefined
let disposed = false
let renderedValue = ''
const lineEnding = props.modelValue.match(/\r\n|\r|\n/)?.[0] ?? '\n'
let previousText = props.modelValue.replace(/\r\n|\r/g, '\n')
let editSelection: (TextSelection & { before: string }) | undefined
let historyEdit = false
const theme = () => document.documentElement.dataset.appTheme === 'dark' ? 'dark' : 'classic'
const observer = new MutationObserver(() => instance?.setTheme(theme()))
function sourceField() { return surface.value?.querySelector<HTMLTextAreaElement>('textarea') }
function exportedValue(value: string) {
  if (props.markdown) return value
  const raw = sourceField()?.value ?? value
  return lineEnding === '\n' ? raw : raw.replace(/\n/g, lineEnding)
}
function paste(event: ClipboardEvent) {
  if (props.markdown) { protectSelection(); return }
  if (!(event.target instanceof HTMLTextAreaElement) || !event.clipboardData?.types.includes('text/plain') || props.disabled) return
  event.preventDefault()
  event.stopImmediatePropagation()
  const text = event.clipboardData.getData('text/plain')
  if (instance) instance.updateValue(text)
  else {
    event.target.setRangeText(text, event.target.selectionStart, event.target.selectionEnd, 'end')
    emit('update:modelValue', exportedValue(event.target.value))
  }
}
function normalizeSelection(field: HTMLTextAreaElement) {
  const selection = atomicSelection(field.value, field.selectionStart, field.selectionEnd)
  if (selection.start !== field.selectionStart || selection.end !== field.selectionEnd) {
    field.setSelectionRange(selection.start, selection.end, field.selectionDirection)
  }
  editSelection = { before: field.value, ...selection }
}
function protectSelection() {
  if (!props.markdown) return
  const field = sourceField()
  if (field && document.activeElement === field) normalizeSelection(field)
}
function allowHistoryEdit() {
  // History contains accepted states; undo can move an intact token past another token.
  historyEdit = true
  queueMicrotask(() => { historyEdit = false })
}
function beforeToolbarClick(event: MouseEvent) {
  if (event.target instanceof Element && event.target.closest('button[data-type="undo"], button[data-type="redo"]')) allowHistoryEdit()
}
function beforeEdit(event: InputEvent) {
  if (!props.markdown) return
  if (!(event.target instanceof HTMLTextAreaElement)) return
  if (event.inputType === 'historyUndo' || event.inputType === 'historyRedo') allowHistoryEdit()
  const field = event.target
  normalizeSelection(field)
  if (field.selectionStart === field.selectionEnd && event.inputType.startsWith('delete')) {
    const token = placeholderRanges(field.value).find(token =>
      event.inputType.includes('Backward') ? token.end === field.selectionStart : token.start === field.selectionStart)
    if (token) field.setSelectionRange(token.start, token.end)
  }
  editSelection = { before: field.value, start: field.selectionStart, end: field.selectionEnd }
}
function keydown(event: KeyboardEvent) {
  if (!(event.target instanceof HTMLTextAreaElement)) return
  if ((event.ctrlKey || event.metaKey) && event.altKey && /^Digit[7-9]$/.test(event.code)) {
    event.preventDefault()
    event.stopImmediatePropagation()
    return
  }
  if (event.isComposing) return
  if ((event.ctrlKey || event.metaKey) && !event.altKey && ['z', 'y'].includes(event.key.toLowerCase())) {
    allowHistoryEdit()
    return
  }
  if (!props.markdown) return
  const field = event.target
  if (field.selectionStart !== field.selectionEnd) { normalizeSelection(field); return }
  const backward = event.key === 'ArrowLeft' || event.key === 'Backspace'
  const forward = event.key === 'ArrowRight' || event.key === 'Delete'
  if (!backward && !forward) return
  const token = placeholderRanges(field.value).find(token => backward ? token.end === field.selectionStart : token.start === field.selectionStart)
  if (!token) return
  if (event.key.startsWith('Arrow') && !event.shiftKey) {
    event.preventDefault()
    const edge = backward ? token.start : token.end
    field.setSelectionRange(edge, edge)
  } else {
    if (event.key.startsWith('Arrow')) event.preventDefault()
    field.setSelectionRange(token.start, token.end, backward ? 'backward' : 'forward')
  }
  normalizeSelection(field)
}
function acceptText(field: HTMLTextAreaElement): boolean {
  const selection = editSelection?.before === previousText ? editSelection : undefined
  if (props.markdown && !historyEdit && splitsPlaceholder(previousText, field.value, selection)) {
    const position = Math.min(selection?.start ?? field.selectionStart, previousText.length)
    field.value = previousText
    const safe = atomicSelection(previousText, position, position)
    field.setSelectionRange(safe.start, safe.end)
    blocked.value = true
    editSelection = undefined
    return false
  }
  previousText = field.value
  blocked.value = false
  editSelection = undefined
  return true
}
function checkInput(event: Event) {
  if (event.target instanceof HTMLTextAreaElement && !acceptText(event.target)) event.stopImmediatePropagation()
}
function insertVariable(key: string) {
  if (props.disabled || loading.value) return
  const field = sourceField()
  if (!field || !variables.value.some(variable => variable.key === key)) return
  field.setSelectionRange(field.value.length, field.value.length)
  normalizeSelection(field)
  const value = `{{${key}}}`
  if (instance) instance.updateValue(value)
  else {
    field.setRangeText(value, field.selectionStart, field.selectionEnd, 'end')
    if (acceptText(field)) emit('update:modelValue', field.value)
    field.focus()
  }
}
function labelEditor() {
  host.value?.querySelectorAll('[contenteditable="true"], textarea').forEach(element => {
    element.setAttribute('role', 'textbox')
    element.setAttribute('aria-multiline', 'true')
    element.setAttribute('aria-label', props.label ?? tr('创作方法'))
  })
}

onMounted(async () => {
  document.addEventListener('selectionchange', protectSelection)
  try {
    const language = document.documentElement.lang.startsWith('en') ? 'en_US' : 'zh_CN'
    const Editor = await loadVditor(language)
    if (disposed || !host.value) return
    instance = new Editor(host.value, {
      lang: language, cdn: '/vditor', mode: 'sv', theme: theme(), value: props.modelValue,
      i18n: { ...window.VditorI18n, splitView: tr('Markdown 源码') },
      cache: { enable: false }, height: '100%', minHeight: 0,
      toolbar: props.markdown ? ['headings', 'bold', 'list', 'link', 'code', '|', 'undo', 'redo'] : ['undo', 'redo'],
      toolbarConfig: { pin: false }, resize: { enable: false },
      preview: { mode: 'editor', hljs: { enable: false }, actions: [], markdown: { codeBlockPreview: false, mathBlockPreview: false, sanitize: true } },
      hint: { emoji: {} },
      after: () => {
        if (disposed) { instance?.destroy(); return }
        renderedValue = exportedValue(instance?.getValue() ?? '')
        previousText = sourceField()?.value ?? props.modelValue
        loading.value = false
        if (props.disabled) instance?.disabled()
        labelEditor()
      },
      input: value => {
        if (disposed) return
        const field = sourceField()
        if (field && !acceptText(field)) return
        value = exportedValue(value)
        if (loading.value || value === renderedValue) return
        renderedValue = value
        emit('update:modelValue', value)
      },
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-app-theme'] })
  } catch { failed.value = true; loading.value = false }
})
watch(() => props.modelValue, value => {
  if (!instance || loading.value) { previousText = value.replace(/\r\n|\r/g, '\n'); editSelection = undefined; return }
  if (value === renderedValue) return
  instance.setValue(value)
  previousText = sourceField()?.value ?? value
  editSelection = undefined
  renderedValue = exportedValue(instance.getValue())
})
watch(() => props.disabled, disabled => {
  if (!loading.value) { if (disabled) instance?.disabled(); else instance?.enable() }
})
onBeforeUnmount(() => { disposed = true; observer.disconnect(); document.removeEventListener('selectionchange', protectSelection); if (instance && !loading.value) instance.destroy() })
</script>

<template>
  <div ref="surface" class="skill-markdown" @beforeinput.capture="beforeEdit" @input.capture="checkInput" @keydown.capture="keydown" @click.capture="beforeToolbarClick" @select.capture="protectSelection" @pointerup="protectSelection" @paste.capture="paste" @cut.capture="protectSelection">
    <p v-if="loading" role="status">{{ tr('正在加载编辑器…') }}</p>
    <template v-if="failed">
      <p role="status">{{ tr('编辑器暂不可用，可继续编辑 Markdown 源码') }}</p>
      <textarea :value="modelValue.replace(/\r\n|\r/g, '\n')" name="skill-instructions" :aria-label="label ?? tr('创作方法')" :disabled="disabled" @input="emit('update:modelValue', exportedValue(($event.target as HTMLTextAreaElement).value))" />
    </template>
    <div v-show="!failed" ref="host" class="markdown-host" @focusin="labelEditor" />
    <div v-if="markdown" class="placeholder-tools">
      <p>{{ tr('可直接编辑 Markdown，也可点击下方变量插入正文末尾。变量只能整体移除，不能修改名称。') }}</p>
      <div class="placeholder-buttons" role="group" :aria-label="tr('插入变量')">
        <AppButton v-for="variable in variables" :key="variable.key" type="button" variant="secondary" size="sm" :disabled="disabled || loading" :title="`{{${variable.key}}}`" @click="insertVariable(variable.key)"><Plus :size="14" aria-hidden="true" />{{ variable.label }}</AppButton>
      </div>
      <p v-if="blocked" role="status">{{ tr('占位符不可拆改，请整体删除后重新插入。') }}</p>
    </div>
  </div>
</template>

<style scoped>
.skill-markdown { min-inline-size: 0; min-block-size: 0; block-size: 100%; display: flex; flex-direction: column; }
.markdown-host { flex: 1; min-block-size: 0; }
.placeholder-tools { flex: none; border-block-start: 1px solid var(--app-border); padding: 10px 16px; }
.placeholder-tools p { margin: 0 0 8px; font-size: 12px; }
.placeholder-tools p[role='status'] { margin: 8px 0 0; color: var(--app-accent); }
.placeholder-buttons { display: flex; flex-wrap: wrap; gap: 6px; }
.placeholder-buttons :deep(.app-button--secondary) { color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); }
.placeholder-buttons :deep(.app-button--secondary:hover:not(:disabled)) { color: var(--app-text); background: var(--app-surface-hover); }
p { margin: 10px 16px; color: var(--app-text-secondary); font-size: 13px; }
textarea { flex: 1; resize: none; min-block-size: 240px; padding: 16px; color: var(--app-text); background: var(--app-surface); border: 0; font: 13px/1.8 monospace; }
.skill-markdown :deep(.vditor) { --panel-background-color: var(--app-surface); --toolbar-background-color: var(--app-surface-muted); --toolbar-icon-color: var(--app-text-secondary); --textarea-background-color: var(--app-surface); --textarea-text-color: var(--app-text); --border-color: var(--app-border); --toolbar-icon-hover-color: var(--app-accent); border: 0; border-radius: 0; }
.skill-markdown :deep(.vditor-reset) { color: var(--app-text); font-size: 14px; line-height: 1.85; }
.skill-markdown :deep(.vditor-ir .vditor-reset), .skill-markdown :deep(.vditor-sv) { padding: 20px !important; }
.skill-markdown :deep(.vditor-content) { min-block-size: 0; }
.skill-markdown :deep([contenteditable]) { scrollbar-width: thin; scrollbar-color: var(--app-border-strong) transparent; caret-color: var(--app-accent); }
.skill-markdown :deep(.vditor-toolbar) { padding-inline: 10px; border-block-end: 1px solid var(--app-border); }
.skill-markdown :deep(button:focus-visible), textarea:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; }
.skill-markdown :deep(.vditor-reset pre > code) { color: var(--app-text); background: var(--app-surface-muted); }
@media (pointer: coarse) { .skill-markdown :deep(.vditor-sv), textarea { font-size: 16px; } }
</style>
