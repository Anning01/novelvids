<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { Check, ChevronDown, ChevronUp, Monitor, TimerReset } from 'lucide-vue-next'
import type { VideoGenerationModel } from '@/types'

const props = defineProps<{
  model: VideoGenerationModel | null
  mode: 'reference' | 'keyframes'
  duration: number
  aspectRatio: string
  resolution: string
  returnLastFrame: boolean
}>()

const emit = defineEmits<{
  'update:duration': [value: number]
  'update:aspectRatio': [value: string]
  'update:resolution': [value: string]
  'update:returnLastFrame': [value: boolean]
}>()

const trigger = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const open = ref(false)
const panelStyle = ref<Record<string, string>>({})

const capabilities = computed(() => props.model?.capabilities)
const ratios = computed(() => capabilities.value?.aspect_ratios_by_mode[props.mode]
  || capabilities.value?.aspect_ratios
  || [])
const selectedRatio = computed(() => ratios.value.includes(props.aspectRatio)
  ? props.aspectRatio
  : ratios.value.includes(capabilities.value?.default_aspect_ratio || '')
    ? capabilities.value?.default_aspect_ratio || ratios.value[0] || 'adaptive'
    : ratios.value[0] || 'adaptive')
const selectedResolution = computed(() => capabilities.value?.resolutions.includes(props.resolution)
  ? props.resolution
  : capabilities.value?.default_resolution || capabilities.value?.resolutions[0] || '720p')
const selectedDuration = computed(() => {
  const minimum = capabilities.value?.duration_min || 4
  const maximum = capabilities.value?.duration_max || 30
  return Math.max(minimum, Math.min(maximum, Math.round(props.duration || minimum)))
})
const summary = computed(() => `${selectedDuration.value}秒 · ${selectedRatio.value === 'adaptive' ? '自适应' : selectedRatio.value} · ${selectedResolution.value}`)
const summaryIconStyle = computed(() => {
  if (selectedRatio.value === 'adaptive') return { width: '20px', height: '12px' }
  const [rawWidth, rawHeight] = selectedRatio.value.split(':').map(Number)
  if (!rawWidth || !rawHeight) return { width: '20px', height: '12px' }
  const ratio = rawWidth / rawHeight
  return ratio >= 1
    ? { width: `${Math.min(21, 12 * ratio)}px`, height: '12px' }
    : { width: '12px', height: `${Math.min(18, 12 / ratio)}px` }
})

function ratioShape(value: string) {
  const [rawWidth, rawHeight] = value.split(':').map(Number)
  if (!rawWidth || !rawHeight) return { width: '26px', height: '18px' }
  const ratio = rawWidth / rawHeight
  if (ratio >= 1) return { width: `${Math.min(30, 18 * ratio)}px`, height: '18px' }
  return { width: '18px', height: `${Math.min(30, 18 / ratio)}px` }
}

function positionPanel() {
  const anchor = trigger.value?.getBoundingClientRect()
  const element = panel.value
  if (!anchor || !element) return
  const margin = 10
  const gap = 8
  const width = Math.min(480, window.innerWidth - margin * 2)
  const height = element.getBoundingClientRect().height
  const left = Math.min(
    window.innerWidth - width - margin,
    Math.max(margin, anchor.left),
  )
  const above = anchor.top - height - gap
  const top = above >= margin
    ? above
    : Math.min(window.innerHeight - height - margin, anchor.bottom + gap)
  panelStyle.value = {
    top: `${Math.max(margin, top)}px`,
    left: `${left}px`,
    width: `${width}px`,
  }
}

async function toggle() {
  if (!props.model) return
  if (open.value) {
    close()
    return
  }
  open.value = true
  await nextTick()
  positionPanel()
  window.addEventListener('resize', positionPanel)
  window.addEventListener('scroll', positionPanel, true)
  window.addEventListener('pointerdown', closeFromOutside)
  window.addEventListener('keydown', closeFromEscape)
}

function close() {
  open.value = false
  window.removeEventListener('resize', positionPanel)
  window.removeEventListener('scroll', positionPanel, true)
  window.removeEventListener('pointerdown', closeFromOutside)
  window.removeEventListener('keydown', closeFromEscape)
}

function closeFromOutside(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Node)) return
  if (trigger.value?.contains(target) || panel.value?.contains(target)) return
  close()
}

function closeFromEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

function updateDuration(event: Event) {
  emit('update:duration', Number((event.target as HTMLInputElement).value))
}

onBeforeUnmount(close)
</script>

<template>
  <button
    ref="trigger"
    type="button"
    class="video-parameter-trigger"
    :disabled="!model"
    :aria-expanded="open"
    aria-haspopup="dialog"
    aria-label="设置视频时长、比例、分辨率和尾帧衔接"
    @click="toggle"
  >
    <span
      class="summary-icon"
      :class="{ 'is-adaptive': selectedRatio === 'adaptive' }"
      :style="summaryIconStyle"
      aria-hidden="true"
    />
    <span>{{ summary }}</span>
    <ChevronUp v-if="open" :size="13" />
    <ChevronDown v-else :size="13" />
  </button>

  <Teleport to="body">
    <Transition name="parameter-panel">
      <section
        v-if="open"
        ref="panel"
        class="video-parameter-panel"
        :style="panelStyle"
        role="dialog"
        aria-label="视频生成参数"
      >
        <header>
          <div><TimerReset :size="15" /><strong>视频时长</strong></div>
          <b>当前 {{ selectedDuration }} 秒</b>
        </header>
        <input
          class="duration-slider"
          type="range"
          :min="capabilities?.duration_min || 4"
          :max="capabilities?.duration_max || 30"
          :value="selectedDuration"
          :aria-label="`视频时长 ${selectedDuration} 秒`"
          @input="updateDuration"
        />
        <div class="duration-limits">
          <span>最短 {{ capabilities?.duration_min || 4 }} 秒</span>
          <span>最长 {{ capabilities?.duration_max || 30 }} 秒</span>
        </div>

        <div class="parameter-section">
          <h3>画面比例</h3>
          <div class="option-grid ratio-grid">
            <button
              v-for="ratio in ratios"
              :key="ratio"
              type="button"
              :class="{ 'is-selected': selectedRatio === ratio }"
              @click="emit('update:aspectRatio', ratio)"
            >
              <span v-if="ratio === 'adaptive'" class="adaptive-ratio">AUTO</span>
              <i v-else :style="ratioShape(ratio)" />
              <span>{{ ratio === 'adaptive' ? '自适应' : ratio }}</span>
            </button>
          </div>
        </div>

        <div class="parameter-section">
          <h3>分辨率</h3>
          <div class="option-grid resolution-grid">
            <button
              v-for="resolution in capabilities?.resolutions || []"
              :key="resolution"
              type="button"
              :class="{ 'is-selected': selectedResolution === resolution }"
              @click="emit('update:resolution', resolution)"
            >
              <Monitor :size="14" />
              <span>{{ resolution }}</span>
            </button>
          </div>
        </div>

        <button
          v-if="capabilities?.supports_return_last_frame"
          type="button"
          class="last-frame-toggle"
          :class="{ 'is-selected': returnLastFrame }"
          role="switch"
          :aria-checked="returnLastFrame"
          @click="emit('update:returnLastFrame', !returnLastFrame)"
        >
          <span><strong>返回尾帧</strong><small>完成后自动作为下一镜头的参考图，章节末尾会衔接下一章</small></span>
          <i><Check v-if="returnLastFrame" :size="13" /></i>
        </button>
      </section>
    </Transition>
  </Teleport>
</template>

<style scoped>
.video-parameter-trigger { display: inline-flex; min-height: 34px; align-items: center; gap: 6px; padding: 0 10px; border: 0; border-radius: 9px; color: var(--app-text-secondary,#656b7b); background: var(--app-surface,#fff); box-shadow: 0 1px 3px rgb(35 39 55 / 8%); font-family: inherit; font-size: 10px; font-weight: 500; line-height: 1; white-space: nowrap; cursor: pointer; }
.video-parameter-trigger:hover:not(:disabled), .video-parameter-trigger[aria-expanded='true'] { color: var(--app-accent,#5b5cf6); box-shadow: inset 0 0 0 1px var(--app-accent,#5b5cf6),0 3px 12px rgb(55 57 112 / 10%); }
.video-parameter-trigger:disabled { color: var(--app-text-muted,#9398a8); cursor: not-allowed; }
.summary-icon { display: inline-block; box-sizing: border-box; flex: 0 0 auto; border: 1.5px solid currentColor; border-radius: 2px; transition: width .16s ease,height .16s ease; }
.summary-icon.is-adaptive { border-style: dashed; }
.video-parameter-panel { position: fixed; z-index: 1400; box-sizing: border-box; max-height: calc(100vh - 20px); overflow-y: auto; padding: 15px 16px; border: 1px solid var(--app-border-strong,#d3d6e0); border-radius: 15px; color: var(--app-text,#303442); background: var(--app-surface-raised,#fff); box-shadow: 0 14px 40px rgb(28 31 46 / 18%); scrollbar-width: none; transform-origin: bottom left; }
.video-parameter-panel::-webkit-scrollbar { display: none; }
.video-parameter-panel > header { display: flex; align-items: center; justify-content: space-between; }
.video-parameter-panel > header > div { display: flex; align-items: center; gap: 8px; }
.video-parameter-panel > header strong, .video-parameter-panel > header b { font-size: 12px; }
.video-parameter-panel > header b { color: var(--app-accent,#5b5cf6); }
.duration-slider { width: 100%; height: 4px; margin: 15px 0 5px; border-radius: 999px; accent-color: var(--app-accent,#5b5cf6); cursor: pointer; }
.duration-limits { display: flex; justify-content: space-between; color: var(--app-text-muted,#9398a8); font-size: 10px; }
.parameter-section { margin-top: 15px; }
.parameter-section h3 { margin: 0 0 8px; color: var(--app-text-secondary,#656b7b); font-size: 11px; }
.option-grid { display: grid; gap: 9px; }
.ratio-grid { grid-template-columns: repeat(4,minmax(0,1fr)); }
.resolution-grid { grid-template-columns: repeat(auto-fit,minmax(120px,1fr)); }
.option-grid button { display: grid; min-height: 57px; place-items: center; align-content: center; gap: 5px; padding: 7px; border: 1px solid var(--app-border-strong,#d3d6e0); border-radius: 10px; color: var(--app-text-secondary,#656b7b); background: var(--app-surface,#fff); font-family: inherit; font-size: 10px; font-weight: 500; cursor: pointer; transition: transform .16s ease,border-color .16s ease,background .16s ease; }
.option-grid button:hover { border-color: var(--app-accent,#5b5cf6); transform: translateY(-1px); }
.option-grid button.is-selected { border-color: var(--app-accent,#5b5cf6); color: var(--app-accent,#5b5cf6); background: var(--app-accent-soft,#eeefff); box-shadow: inset 0 0 0 1px var(--app-accent,#5b5cf6); }
.option-grid button i { display: block; box-sizing: border-box; border: 2px solid currentColor; border-radius: 2px; }
.adaptive-ratio { display: grid; width: 32px; height: 20px; place-items: center; border: 1px dashed currentColor; border-radius: 4px; font-size: 8px; font-weight: 800; }
.resolution-grid button { min-height: 50px; grid-auto-flow: column; }
.last-frame-toggle { display: flex; width: 100%; min-height: 52px; align-items: center; justify-content: space-between; gap: 12px; margin-top: 15px; padding: 9px 11px; border: 1px solid var(--app-border,#e3e5ec); border-radius: 10px; color: var(--app-text-secondary,#656b7b); background: var(--app-surface-muted,#f2f3f7); text-align: left; cursor: pointer; }
.last-frame-toggle > span { display: grid; gap: 4px; }
.last-frame-toggle strong { color: var(--app-text,#303442); font-size: 11px; }
.last-frame-toggle small { color: var(--app-text-muted,#9398a8); font-size: 8px; line-height: 1.45; }
.last-frame-toggle > i { display: flex; width: 34px; height: 20px; flex: 0 0 34px; align-items: center; justify-content: flex-start; padding: 3px; border-radius: 999px; color: #fff; background: var(--app-border-strong,#d3d6e0); transition: background .18s ease; }
.last-frame-toggle > i::before { width: 14px; height: 14px; border-radius: 50%; background: #fff; content: ''; }
.last-frame-toggle.is-selected { border-color: color-mix(in srgb,var(--app-accent,#5b5cf6) 35%,transparent); background: var(--app-accent-soft,#eeefff); }
.last-frame-toggle.is-selected > i { justify-content: flex-end; background: var(--app-accent,#5b5cf6); }
.last-frame-toggle.is-selected > i::before { display: none; }
.parameter-panel-enter-active, .parameter-panel-leave-active { transition: opacity .16s ease,transform .16s ease; }
.parameter-panel-enter-from, .parameter-panel-leave-to { opacity: 0; transform: translateY(6px) scale(.985); }
@media (max-width: 620px) { .video-parameter-panel { padding: 16px; border-radius: 16px; }.ratio-grid { grid-template-columns: repeat(3,minmax(0,1fr)); }.resolution-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (prefers-reduced-motion: reduce) { .parameter-panel-enter-active,.parameter-panel-leave-active,.option-grid button { transition-duration: .01ms; } }
</style>
