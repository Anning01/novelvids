<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type Vditor from 'vditor'
import { tr } from '@/i18n'
import { loadVditor } from './vditorLoader'

const props = defineProps<{ modelValue: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const host = ref<HTMLElement>()
const loading = ref(true)
const failed = ref(false)
let instance: Vditor | undefined
let disposed = false
let renderedValue = ''
const theme = () => document.documentElement.dataset.appTheme === 'dark' ? 'dark' : 'classic'
const observer = new MutationObserver(() => instance?.setTheme(theme()))
function labelEditor() {
  host.value?.querySelectorAll('[contenteditable="true"], textarea').forEach(element => {
    element.setAttribute('role', 'textbox')
    element.setAttribute('aria-multiline', 'true')
    element.setAttribute('aria-label', tr('创作方法'))
  })
}

onMounted(async () => {
  try {
    const language = document.documentElement.lang.startsWith('en') ? 'en_US' : 'zh_CN'
    const Editor = await loadVditor(language)
    if (disposed || !host.value) return
    instance = new Editor(host.value, {
      lang: language, cdn: '/vditor', mode: 'ir', theme: theme(), value: props.modelValue,
      i18n: { ...window.VditorI18n, splitView: tr('Markdown 源码') },
      cache: { enable: false }, height: '100%', minHeight: 240,
      toolbar: ['headings', 'bold', 'list', 'link', 'code', '|', 'undo', 'redo', '|', 'edit-mode'],
      toolbarConfig: { pin: false }, resize: { enable: false },
      preview: { mode: 'editor', hljs: { enable: false }, actions: [], markdown: { codeBlockPreview: false, mathBlockPreview: false, sanitize: true } },
      hint: { emoji: {} },
      after: () => {
        if (disposed) { instance?.destroy(); return }
        renderedValue = instance?.getValue() ?? ''
        loading.value = false
        if (props.disabled) instance?.disabled()
        labelEditor()
      },
      input: value => {
        if (loading.value || value === renderedValue) return
        renderedValue = value
        emit('update:modelValue', value)
      },
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-app-theme'] })
  } catch { failed.value = true; loading.value = false }
})
watch(() => props.modelValue, value => {
  if (!instance || loading.value || value === renderedValue) return
  instance.setValue(value)
  renderedValue = instance.getValue()
})
watch(() => props.disabled, disabled => {
  if (!loading.value) { if (disabled) instance?.disabled(); else instance?.enable() }
})
onBeforeUnmount(() => { disposed = true; observer.disconnect(); if (instance && !loading.value) instance.destroy() })
</script>

<template>
  <div class="skill-markdown">
    <p v-if="loading" role="status">{{ tr('正在加载编辑器…') }}</p>
    <template v-if="failed">
      <p role="status">{{ tr('编辑器暂不可用，可继续编辑 Markdown 源码') }}</p>
      <textarea :value="modelValue" name="skill-instructions" :aria-label="tr('创作方法')" :disabled="disabled" maxlength="32000" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" />
    </template>
    <div v-show="!failed" ref="host" class="markdown-host" @focusin="labelEditor" />
  </div>
</template>

<style scoped>
.skill-markdown { min-inline-size: 0; min-block-size: 0; block-size: 100%; display: flex; flex-direction: column; }
.markdown-host { flex: 1; min-block-size: 0; }
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
</style>
