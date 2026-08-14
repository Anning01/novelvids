<script setup lang="ts">
import { BookOpenText, X } from 'lucide-vue-next'
import { onBeforeUnmount, ref, watch } from 'vue'
import AppButton from './AppButton.vue'

const props = withDefaults(defineProps<{
  open: boolean
  chapterNumber: number
  title: string
  content?: string
  saving?: boolean
}>(), {
  content: '',
  saving: false,
})

const emit = defineEmits<{
  close: []
  save: [value: { name: string; content: string }]
}>()

const nameDraft = ref('')
const contentDraft = ref('')
let previousBodyOverflow = ''

function syncDraft() {
  nameDraft.value = props.title
  contentDraft.value = props.content
}

function close() {
  if (!props.saving) emit('close')
}

function submit() {
  const name = nameDraft.value.trim()
  if (!name || props.saving) return
  emit('save', { name, content: contentDraft.value.trim() })
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) close()
}

watch(() => [props.open, props.title, props.content] as const, ([open]) => {
  if (open) syncDraft()
}, { immediate: true })

watch(() => props.open, open => {
  if (open) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeydown)
    return
  }
  document.body.style.overflow = previousBodyOverflow
  window.removeEventListener('keydown', handleKeydown)
}, { immediate: true })

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="chapter-detail-backdrop">
      <div v-if="open" class="chapter-detail-backdrop" aria-hidden="true" @click="close" />
    </Transition>
    <Transition name="chapter-detail-drawer">
      <form
        v-if="open"
        class="chapter-detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chapter-detail-title"
        @submit.prevent="submit"
      >
        <header>
          <span class="chapter-detail-drawer__icon"><BookOpenText :size="18" /></span>
          <div>
            <span>CHAPTER DETAIL</span>
            <h2 id="chapter-detail-title">第 {{ chapterNumber }} 集 · 章节详情</h2>
          </div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭章节详情" @click="close"><X :size="18" /></AppButton>
        </header>

        <div class="chapter-detail-drawer__body">
          <label>
            <span><b aria-hidden="true">*</b>章节标题</span>
            <input v-model="nameDraft" type="text" maxlength="200" autocomplete="off" placeholder="请输入章节标题" />
          </label>
          <label class="is-content">
            <span>章节内容</span>
            <textarea v-model="contentDraft" placeholder="请输入章节内容" />
          </label>
        </div>

        <footer>
          <AppButton type="button" variant="secondary" :disabled="saving" @click="close">取消</AppButton>
          <AppButton type="submit" variant="primary" :loading="saving" :disabled="!nameDraft.trim()">保存章节</AppButton>
        </footer>
      </form>
    </Transition>
  </Teleport>
</template>

<style scoped>
.chapter-detail-backdrop { position: fixed; inset: 0; z-index: 124; background: rgb(34 37 51 / 42%); backdrop-filter: blur(6px); }
.chapter-detail-drawer { position: fixed; top: 0; right: 0; bottom: 0; z-index: 125; display: grid; width: min(680px,calc(100vw - 24px)); height: 100dvh; grid-template-rows: auto minmax(0,1fr) auto; overflow: hidden; border: 0; border-radius: 22px 0 0 22px; color: var(--app-text); background: var(--app-surface); box-shadow: -28px 0 90px rgb(25 28 45 / 24%); }
.chapter-detail-drawer > header { display: grid; grid-template-columns: 38px minmax(0,1fr) 34px; align-items: center; gap: 11px; padding: 13px 18px; background: linear-gradient(135deg,color-mix(in srgb,var(--app-surface) 95%,var(--app-accent)),color-mix(in srgb,var(--app-surface) 88%,var(--app-accent-soft))); }
.chapter-detail-drawer__icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 12px; color: var(--app-accent); background: var(--app-surface); box-shadow: 0 6px 16px rgb(73 75 159 / 9%); }
.chapter-detail-drawer > header > div { min-width: 0; }
.chapter-detail-drawer > header > div > span { color: var(--app-accent); font-size: 8px; font-weight: 800; letter-spacing: .13em; }
.chapter-detail-drawer h2 { margin: 2px 0 0; overflow: hidden; font-size: 17px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.chapter-detail-drawer__body { display: grid; min-height: 0; align-content: start; gap: 18px; overflow-y: auto; padding: 22px; scrollbar-width: none; }
.chapter-detail-drawer__body::-webkit-scrollbar { display: none; }
.chapter-detail-drawer__body label { display: grid; gap: 8px; }
.chapter-detail-drawer__body label > span { color: var(--app-text-secondary); font-size: 11px; font-weight: 700; }
.chapter-detail-drawer__body label b { margin-right: 6px; color: #d95563; }
.chapter-detail-drawer input,.chapter-detail-drawer textarea { width: 100%; min-width: 0; border: 1px solid transparent; border-radius: 12px; outline: 0; color: var(--app-text); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-border) 74%,transparent); font: inherit; font-size: 12px; transition: border-color .16s ease,box-shadow .16s ease,background-color .16s ease; }
.chapter-detail-drawer input { height: 44px; padding: 0 13px; }
.chapter-detail-drawer textarea { min-height: min(560px,calc(100dvh - 260px)); padding: 13px; line-height: 1.85; resize: vertical; }
.chapter-detail-drawer input:focus,.chapter-detail-drawer textarea:focus { border-color: color-mix(in srgb,var(--app-accent) 52%,var(--app-border)); background: var(--app-surface); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 9%,transparent); }
.chapter-detail-drawer > footer { display: flex; min-height: 68px; align-items: center; justify-content: flex-end; gap: 9px; padding: 10px 18px; border-top: 1px solid var(--app-border); background: color-mix(in srgb,var(--app-surface) 96%,var(--app-surface-muted)); }
.chapter-detail-backdrop-enter-active,.chapter-detail-backdrop-leave-active { transition: opacity .22s ease; }
.chapter-detail-backdrop-enter-from,.chapter-detail-backdrop-leave-to { opacity: 0; }
.chapter-detail-drawer-enter-active,.chapter-detail-drawer-leave-active { transition: transform .28s cubic-bezier(.2,.72,.2,1),box-shadow .28s ease; }
.chapter-detail-drawer-enter-from,.chapter-detail-drawer-leave-to { box-shadow: none; transform: translateX(100%); }
@media (max-width: 620px) { .chapter-detail-drawer { width: calc(100vw - 8px); border-radius: 18px 0 0 18px; }.chapter-detail-drawer__body { padding: 18px 14px; } }
@media (prefers-reduced-motion: reduce) { .chapter-detail-backdrop-enter-active,.chapter-detail-backdrop-leave-active,.chapter-detail-drawer-enter-active,.chapter-detail-drawer-leave-active { transition-duration: .01ms; } }
</style>
