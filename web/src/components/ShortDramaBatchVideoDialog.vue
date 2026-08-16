<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ListChecks, Sparkles, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import BillingPriceTag from '@/components/BillingPriceTag.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import type { ModelPricing } from '@/types'

export interface BatchVideoSceneOption {
  id: number
  sequence: number
  disabled?: boolean
  disabledReason?: string
}

const props = defineProps<{
  open: boolean
  scenes: BatchVideoSceneOption[]
  costByScene?: Record<number, number>
  pricing?: ModelPricing | null
}>()

const emit = defineEmits<{
  close: []
  generate: [sceneIds: number[]]
}>()

const dialog = ref<HTMLElement | null>(null)
const selectedIds = ref<number[]>([])
const eligibleScenes = computed(() => props.scenes.filter(scene => !scene.disabled))
const allSelected = computed(() => (
  Boolean(eligibleScenes.value.length)
  && eligibleScenes.value.every(scene => selectedIds.value.includes(scene.id))
))
const estimatedTotal = computed(() => selectedIds.value.reduce((sum, id) => sum + (props.costByScene?.[id] || 0), 0))
function close() {
  emit('close')
}

function toggleScene(scene: BatchVideoSceneOption) {
  if (scene.disabled) return
  selectedIds.value = selectedIds.value.includes(scene.id)
    ? selectedIds.value.filter(id => id !== scene.id)
    : [...selectedIds.value, scene.id]
}

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : eligibleScenes.value.map(scene => scene.id)
}

function submit() {
  if (!selectedIds.value.length) return
  emit('generate', [...selectedIds.value])
}

function handleKeydown(event: KeyboardEvent) {
  if (!props.open || event.key !== 'Escape') return
  event.preventDefault()
  close()
}

watch(() => props.open, async open => {
  if (!open) return
  selectedIds.value = []
  await nextTick()
  dialog.value?.focus()
})

watch(() => props.scenes, scenes => {
  const eligibleIds = new Set(scenes.filter(scene => !scene.disabled).map(scene => scene.id))
  selectedIds.value = selectedIds.value.filter(id => eligibleIds.has(id))
})

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="batch-video-dialog">
      <div v-if="open" class="batch-video-dialog__backdrop" @click.self="close">
        <section
          ref="dialog"
          class="batch-video-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="batch-video-dialog-title"
          tabindex="-1"
        >
          <header class="batch-video-dialog__header">
            <span class="batch-video-dialog__icon" aria-hidden="true"><ListChecks :size="22" /></span>
            <div>
              <h2 id="batch-video-dialog-title">批量生视频</h2>
            </div>
            <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭批量生视频" @click="close"><X :size="18" /></AppButton>
          </header>

          <AppScrollArea class="batch-video-dialog__scroller" aria-label="可选择的分镜列表">
            <div class="batch-video-dialog__grid">
              <label
                v-for="scene in scenes"
                :key="scene.id"
                class="batch-video-scene"
                :class="{
                  'is-selected': selectedIds.includes(scene.id),
                  'is-disabled': scene.disabled,
                }"
                :title="scene.disabledReason"
              >
                <input
                  type="checkbox"
                  :checked="selectedIds.includes(scene.id)"
                  :disabled="scene.disabled"
                  :aria-label="`选择分镜 ${scene.sequence}${scene.disabledReason ? `，${scene.disabledReason}` : ''}`"
                  @change="toggleScene(scene)"
                >
                <span class="batch-video-scene__checkbox" aria-hidden="true"><Check :size="15" /></span>
                <strong>分镜{{ scene.sequence }}</strong>
                <span v-if="scene.disabledReason" class="visually-hidden">{{ scene.disabledReason }}</span>
              </label>
            </div>
          </AppScrollArea>

          <footer class="batch-video-dialog__footer">
            <AppButton type="button" class="batch-video-dialog__select-all" variant="soft" :disabled="!eligibleScenes.length" @click="toggleAll">
              {{ allSelected ? '取消全选' : '全选' }}
            </AppButton>
            <div>
              <AppButton type="button" variant="soft" @click="close">取消</AppButton>
              <AppButton
                type="button"
                class="batch-video-dialog__submit"
                variant="primary"
                :disabled="!selectedIds.length"
                :aria-label="`生成所选 ${selectedIds.length} 条分镜视频`"
                @click="submit"
              >
                <Sparkles :size="15" />开始<BillingPriceTag :cost="estimatedTotal" :pricing="pricing" />
              </AppButton>
            </div>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.batch-video-dialog__backdrop {
  position: fixed;
  inset: 0;
  z-index: 130;
  display: grid;
  place-items: center;
  padding: 22px;
  background: rgb(31 34 44 / 48%);
  backdrop-filter: blur(8px);
}
.batch-video-dialog {
  display: grid;
  width: min(720px,100%);
  max-height: min(620px,calc(100vh - 44px));
  grid-template-rows: auto minmax(0,1fr) auto;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 22px;
  outline: 0;
  color: var(--app-text);
  background: var(--app-surface);
  box-shadow: 0 36px 110px rgb(19 22 34 / 34%);
}
.batch-video-dialog__header {
  display: grid;
  grid-template-columns: 48px minmax(0,1fr) 36px;
  align-items: center;
  gap: 14px;
  min-height: 82px;
  padding: 16px 22px;
  background: linear-gradient(135deg,var(--app-accent-soft),var(--app-surface));
}
.batch-video-dialog__icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: 14px;
  color: var(--app-text-secondary);
  background: var(--app-surface);
  box-shadow: inset 0 0 0 1px var(--app-border),var(--app-shadow);
}
.batch-video-dialog__header h2 { margin: 0; font-size: 20px; line-height: 1.2; letter-spacing: -.025em; }
.batch-video-dialog__header > button { color: var(--app-text-secondary); }
.batch-video-dialog :deep(.app-button--ghost) { color: var(--app-text-secondary); background: transparent; }
.batch-video-dialog :deep(.app-button--ghost:hover:not(:disabled)) { color: var(--app-text); background: var(--app-surface-hover); }
.batch-video-dialog__scroller { min-height: 0; margin: 0 16px; padding: 10px 4px 14px; }
.batch-video-dialog__grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px 12px; }
.batch-video-scene {
  position: relative;
  display: flex;
  min-height: 58px;
  align-items: center;
  gap: 11px;
  padding: 0 14px;
  border-radius: 11px;
  color: var(--app-text-secondary);
  background: var(--app-surface);
  box-shadow: inset 0 0 0 2px var(--app-border);
  cursor: pointer;
  transition: color .16s ease,background-color .16s ease,box-shadow .16s ease,transform .16s ease;
}
.batch-video-scene:hover:not(.is-disabled) { color: var(--app-text); background: var(--app-surface-hover); box-shadow: inset 0 0 0 2px var(--app-border-strong); transform: translateY(-1px); }
.batch-video-scene.is-selected { color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 2px var(--app-accent); }
.batch-video-scene.is-disabled { color: var(--app-text-muted); background: var(--app-surface-muted); opacity: .48; cursor: not-allowed; }
.batch-video-scene input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.batch-video-scene__checkbox {
  display: grid;
  width: 19px;
  height: 19px;
  flex: 0 0 19px;
  place-items: center;
  border-radius: 5px;
  color: transparent;
  background: var(--app-surface);
  box-shadow: inset 0 0 0 2px var(--app-border-strong);
}
.batch-video-scene.is-selected .batch-video-scene__checkbox { color: #fff; background: var(--app-accent); box-shadow: none; }
.batch-video-scene:focus-within { outline: 3px solid rgb(91 92 246 / 18%); outline-offset: 2px; }
.batch-video-scene strong { font-size: 13px; font-weight: 620; }
.batch-video-dialog__footer {
  display: flex;
  min-height: 76px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 20px 16px;
  background: var(--app-surface);
  box-shadow: 0 -12px 34px rgb(36 40 57 / 5%);
}
.batch-video-dialog__footer > div { display: flex; align-items: center; gap: 10px; }
.batch-video-dialog__footer :deep(.app-button) { min-width: 84px; min-height: 40px; border-radius: 10px; font-size: 12px; }
.batch-video-dialog__footer :deep(.app-button--soft) { color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); }
.batch-video-dialog__footer :deep(.app-button--soft:hover:not(:disabled)) { color: var(--app-text); background: var(--app-surface-hover); box-shadow: inset 0 0 0 1px var(--app-border-strong); }
.batch-video-dialog__select-all { justify-self: start; }
.batch-video-dialog__submit { min-width: 90px; }
.batch-video-cost { margin-left: 6px; font-size: 10px; font-weight: 600; opacity: .85; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.batch-video-dialog-enter-active,.batch-video-dialog-leave-active { transition: opacity .18s ease; }
.batch-video-dialog-enter-active .batch-video-dialog,.batch-video-dialog-leave-active .batch-video-dialog { transition: transform .18s ease,opacity .18s ease; }
.batch-video-dialog-enter-from,.batch-video-dialog-leave-to { opacity: 0; }
.batch-video-dialog-enter-from .batch-video-dialog,.batch-video-dialog-leave-to .batch-video-dialog { opacity: 0; transform: translateY(10px) scale(.985); }
@media (max-width: 680px) {
  .batch-video-dialog__backdrop { padding: 0; }
  .batch-video-dialog { width: 100%; max-height: 100vh; min-height: 100vh; border-radius: 0; }
  .batch-video-dialog__header { grid-template-columns: 44px minmax(0,1fr) 36px; min-height: 76px; gap: 11px; padding: 14px 16px; }
  .batch-video-dialog__icon { width: 44px; height: 44px; border-radius: 13px; }
  .batch-video-dialog__header h2 { font-size: 19px; }
  .batch-video-dialog__grid { grid-template-columns: 1fr; gap: 10px; }
  .batch-video-dialog__scroller { margin: 0 10px; }
  .batch-video-scene { min-height: 56px; }
  .batch-video-dialog__footer { min-height: 72px; padding: 12px 14px 14px; }
  .batch-video-dialog__footer :deep(.app-button) { min-width: 74px; min-height: 40px; }
}
@media (prefers-reduced-motion: reduce) {
  .batch-video-dialog-enter-active,.batch-video-dialog-leave-active,.batch-video-dialog-enter-active .batch-video-dialog,.batch-video-dialog-leave-active .batch-video-dialog,.batch-video-scene { transition: none; }
}
</style>
