<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { Sparkles, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { videoPixelSize } from '@/features/workbench/graph/videoMedia'
import type { Video } from '@/types'
import { tr } from '@/i18n'
import ChapterExportPanel from './ChapterExportPanel.vue'

const props = defineProps<{ video: Video; pixelSize?: { width: number; height: number } | null }>()
const emit = defineEmits<{ applied: [videoId: number] }>()
const auth = useAuthStore()
const open = ref(false)
const dialog = ref<HTMLElement | null>(null)
const titleId = useId()
let previousFocus: HTMLElement | null = null
const alreadyHd = computed(() => {
  const size = props.pixelSize || videoPixelSize(props.video)
  return size ? Math.min(size.width, size.height) >= 1080 : false
})
const canWrite = computed(() => !auth.enabled || auth.isSuperAdmin || ['admin', 'creator'].includes(auth.role || ''))
watch(() => props.video.id, () => { open.value = false })
watch(open, async value => {
  if (value) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    dialog.value?.querySelector<HTMLButtonElement>('button')?.focus()
  } else { previousFocus?.focus(); previousFocus = null }
})
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); open.value = false }
  if (event.key !== 'Tab') return
  const controls = [...(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),video[controls]') || [])]
  const first = controls[0], last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onBeforeUnmount(() => previousFocus?.focus())
</script>

<template>
  <AppButton v-if="canWrite && video.status === 3 && video.url" class="video-enhance-trigger nodrag nowheel" variant="secondary" size="sm" :disabled="alreadyHd" :title="alreadyHd ? tr('已达1080p，无需高清化') : tr('单条视频高清化')" @click.stop="open = true"><Sparkles :size="14" />{{ alreadyHd ? tr('已达1080p') : tr('高清化') }}</AppButton>
  <Teleport to="body">
    <div v-if="open" class="video-enhance-backdrop" @click.self="open = false">
      <section ref="dialog" class="video-enhance-dialog nodrag nowheel" role="dialog" aria-modal="true" :aria-labelledby="titleId" @keydown="onKeydown">
        <header><h2 :id="titleId">{{ tr('视频高清化') }} · #{{ video.id }}</h2><AppButton variant="ghost" icon-only size="sm" :aria-label="tr('关闭')" @click="open = false"><X :size="18" /></AppButton></header>
        <ChapterExportPanel :video-id="video.id" @applied="emit('applied', $event)" />
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.video-enhance-trigger { color:var(--app-text-secondary);background:var(--app-surface-muted);box-shadow:inset 0 0 0 1px var(--app-border) }.video-enhance-trigger:hover:not(:disabled){color:var(--app-accent);background:var(--app-accent-soft)}.video-enhance-trigger:focus-visible{outline:2px solid var(--app-accent);outline-offset:2px}
.video-enhance-backdrop { position:fixed;inset:0;z-index:200;display:grid;place-items:center;padding:20px;background:rgb(0 0 0 / 50%);backdrop-filter:blur(5px) }
.video-enhance-dialog { width:min(920px,100%);max-height:90dvh;overflow:auto;box-sizing:border-box;padding:18px;border:1px solid var(--app-border);border-radius:18px;background:var(--app-surface);color:var(--app-text);box-shadow:0 24px 80px rgb(0 0 0 / 28%) }
header { display:flex;align-items:center;justify-content:space-between;gap:12px }h2 { margin:0;font-size:18px }@media(max-width:600px){.video-enhance-backdrop{padding:8px}.video-enhance-dialog{padding:12px;max-height:96dvh}}
</style>
