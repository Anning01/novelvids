<script setup lang="ts">
import { ref } from 'vue'
import { FileAudio, UploadCloud } from 'lucide-vue-next'
import { tr } from '@/i18n'

const props = withDefaults(defineProps<{
  accept?: string
  multiple?: boolean
  disabled?: boolean
  title?: string
  hint?: string
  fileName?: string
  meta?: string
}>(), {
  accept: '',
  multiple: false,
  disabled: false,
  title: '',
  hint: '',
  fileName: '',
  meta: '',
})

const emit = defineEmits<{ select: [files: File[]] }>()
const dragging = ref(false)

function onChange(event: Event) {
  const element = event.target as HTMLInputElement
  const files = Array.from(element.files || [])
  element.value = ''
  if (files.length) emit('select', files)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
  if (props.disabled) return
  dragging.value = true
}

function onDragLeave(event: DragEvent) {
  event.preventDefault()
  dragging.value = false
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  dragging.value = false
  if (props.disabled) return
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length) emit('select', files)
}
</script>

<template>
  <label
    class="app-dropzone"
    :class="{ 'is-dragging': dragging, 'is-disabled': disabled, 'has-file': !!fileName }"
    @dragover="onDragOver"
    @dragenter="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      class="app-dropzone__input"
      type="file"
      :accept="accept"
      :multiple="multiple"
      :disabled="disabled"
      :aria-label="fileName || title || tr('选择文件')"
      @change="onChange"
    />
    <span class="app-dropzone__icon" aria-hidden="true">
      <FileAudio v-if="fileName" :size="20" />
      <UploadCloud v-else :size="20" />
    </span>
    <span class="app-dropzone__title">{{ fileName || title }}</span>
    <span class="app-dropzone__hint">{{ fileName ? meta : hint }}</span>
  </label>
</template>

<style scoped>
.app-dropzone {
  position: relative;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 6px;
  padding: 22px 18px;
  border: 1.5px dashed var(--app-border-strong);
  border-radius: 12px;
  background: var(--app-surface-muted);
  color: var(--app-text);
  text-align: center;
  cursor: pointer;
  transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease;
}
.app-dropzone:hover {
  border-color: var(--app-accent);
  background: color-mix(in srgb, var(--app-accent) 4%, var(--app-surface-muted));
}
.app-dropzone:focus-within {
  border-color: var(--app-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-accent) 12%, transparent);
}
.app-dropzone.is-dragging {
  border-color: var(--app-accent);
  border-style: solid;
  background: var(--app-accent-soft);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-accent) 12%, transparent);
}
.app-dropzone.is-disabled {
  opacity: .55;
  cursor: not-allowed;
}
.app-dropzone.has-file {
  border-style: solid;
  border-color: color-mix(in srgb, var(--app-accent) 34%, var(--app-border));
}
.app-dropzone__input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
  opacity: 0;
}
.app-dropzone__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: var(--app-accent);
  background: var(--app-accent-soft);
}
.app-dropzone__title {
  max-width: 100%;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.app-dropzone__hint {
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.6;
}
</style>
