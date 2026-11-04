<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, useId, watch } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { Video } from '@/types'
import { tr } from '@/i18n'
import VideoEnhancementPanel from './VideoEnhancementPanel.vue'

const props = defineProps<{ video: Video; sceneSequence?: number; pixelSize?: { width: number; height: number } | null }>()
const emit = defineEmits<{ applied: [videoId: number] }>()
const auth = useAuthStore()
const open = ref(false)
const activeVideo = shallowRef<Video | null>(null)
const dialog = ref<HTMLElement | null>(null)
const titleId = useId()
let previousFocus: HTMLElement | null = null
let expectedVideoId = 0
const canWrite = computed(() => !auth.enabled || auth.isSuperAdmin || ['admin', 'creator'].includes(auth.role || ''))
watch(() => props.video.id, id => {
  if (id === expectedVideoId) return
  open.value = false; activeVideo.value = null
})
watch(() => [auth.activeTeamId, auth.user?.id, canWrite.value], () => { open.value = false; activeVideo.value = null })
function show() { activeVideo.value = props.video; expectedVideoId = 0; open.value = true }
function onApplied(id: number) { expectedVideoId = id; emit('applied', id) }
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
  const controls = [...(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),video[controls],summary') || [])]
    .filter(element => !element.closest('details:not([open])') || element.tagName === 'SUMMARY')
  const first = controls[0], last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onBeforeUnmount(() => previousFocus?.focus())
</script>

<template>
  <AppButton v-if="canWrite && video.status === 3 && video.url" class="video-enhance-trigger nodrag nowheel" variant="secondary" size="sm" :title="tr('单条视频高清化')" @click.stop="show"><Sparkles :size="14" />{{ tr('高清化') }}</AppButton>
  <Teleport to="body">
    <div v-if="activeVideo" v-show="open" class="video-enhance-backdrop" @click.self="open = false">
      <section ref="dialog" class="video-enhance-dialog nodrag nowheel" role="dialog" aria-modal="true" :aria-labelledby="titleId" @keydown="onKeydown">
        <VideoEnhancementPanel :key="activeVideo.id" :video="activeVideo" :visible="open" :title-id="titleId" :scene-sequence="sceneSequence" :pixel-size="pixelSize" @close="open = false" @applied="onApplied" />
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.video-enhance-trigger { color:var(--app-text-secondary);background:var(--app-surface-muted);box-shadow:inset 0 0 0 1px var(--app-border) }.video-enhance-trigger:hover:not(:disabled){color:var(--app-accent);background:var(--app-accent-soft)}.video-enhance-trigger:focus-visible{outline:2px solid var(--app-accent);outline-offset:2px}
.video-enhance-backdrop { position:fixed;inset:0;z-index:200;display:grid;place-items:center;padding:20px;background:rgb(0 0 0 / 50%);backdrop-filter:blur(5px) }
.video-enhance-dialog { width:min(820px,100%);max-height:90dvh;overflow:auto;box-sizing:border-box;border:1px solid var(--app-border);border-radius:18px;background:var(--app-surface);color:var(--app-text);box-shadow:0 24px 80px rgb(0 0 0 / 28%) }
@media(max-width:600px){.video-enhance-backdrop{padding:8px}.video-enhance-dialog{max-height:96dvh}}
</style>
