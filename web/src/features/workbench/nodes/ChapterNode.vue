<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { BookOpenText } from 'lucide-vue-next'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { Chapter } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()

const store = useWorkbenchStore()
const saving = ref(false)
const error = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const chapter = computed(() => props.data.chapter as Chapter)
const title = computed(() => props.label || `第 ${chapter.value.number} 章`)
const content = computed(() => chapter.value.content || '')
const draft = ref(content.value)

function resizeToContent() {
  const textarea = textareaRef.value
  if (!textarea) return
  textarea.style.height = 'auto'
  textarea.style.height = `${Math.ceil(textarea.scrollHeight)}px`
}

function updateContent(event: Event) {
  draft.value = (event.target as HTMLTextAreaElement).value
  resizeToContent()
}

async function saveContent() {
  if (saving.value || draft.value === content.value) return
  error.value = ''
  saving.value = true
  try {
    await store.saveChapter({ content: draft.value })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '章节保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => void nextTick(resizeToContent))
watch(content, (value) => {
  draft.value = value
  void nextTick(resizeToContent)
})
</script>

<template>
  <article
    class="workbench-note workbench-chapter-note"
    :class="{ 'is-selected': selected }"
    :aria-label="`${title}章节便签`"
  >
    <header class="workbench-node-drag-handle">
      <BookOpenText :size="16" aria-hidden="true" />
      <strong>{{ title }}</strong>
      <span v-if="saving">保存中…</span>
    </header>
    <textarea
      ref="textareaRef"
      class="nodrag nowheel"
      :value="draft"
      maxlength="100000"
      aria-label="章节正文"
      placeholder="本章暂无正文"
      @input="updateContent"
      @blur="saveContent"
      @keydown.stop
    />
    <p v-if="error" role="alert">
      {{ error }}
    </p>
  </article>
</template>
