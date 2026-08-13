<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import type { ImageGenerationCapabilities } from '@/types'

export interface ImageGenerationParameters {
  clarity: string
  aspectRatio: string
  outputFormat: string
  generationCount: number
}

const props = withDefaults(defineProps<{
  modelValue: ImageGenerationParameters
  capabilities?: ImageGenerationCapabilities | null
  disabled?: boolean
  compact?: boolean
}>(), {
  capabilities: null,
  disabled: false,
  compact: false,
})

const emit = defineEmits<{ 'update:modelValue': [value: ImageGenerationParameters] }>()
const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const open = ref(false)
const opensUp = ref(true)
const placement = ref({ top: 0, left: 0, width: 520 })
const panelStyle = computed(() => ({
  top: `${placement.value.top}px`,
  left: `${placement.value.left}px`,
  width: `${placement.value.width}px`,
}))
const summary = computed(() => [
  props.modelValue.aspectRatio,
  clarityLabel(props.modelValue.clarity),
  '1张',
  props.modelValue.outputFormat.toUpperCase(),
].filter(Boolean).join(' · '))

function clarityLabel(value: string) {
  return ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[value] || value
}

function ratioStyle(value: string, maxWidth = 31, maxHeight = 22, minSize = 8) {
  const [width = 1, height = 1] = value.split(':').map(Number)
  const scale = Math.min(maxWidth / width, maxHeight / height)
  return {
    width: `${Math.max(minSize, width * scale)}px`,
    height: `${Math.max(minSize, height * scale)}px`,
  }
}

function update<K extends keyof ImageGenerationParameters>(key: K, value: ImageGenerationParameters[K]) {
  emit('update:modelValue', { ...props.modelValue, generationCount: 1, [key]: value })
}

function updatePlacement() {
  const rect = root.value?.getBoundingClientRect()
  if (!rect) return
  const width = Math.min(520, window.innerWidth - 24)
  const height = panel.value?.offsetHeight || 430
  const roomBelow = window.innerHeight - rect.bottom
  opensUp.value = roomBelow < height + 12 && rect.top > roomBelow
  placement.value = {
    width,
    left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    top: opensUp.value ? Math.max(12, rect.top - height - 8) : Math.min(window.innerHeight - height - 12, rect.bottom + 8),
  }
}

async function toggle() {
  if (props.disabled || !props.capabilities) return
  open.value = !open.value
  if (open.value) {
    await nextTick()
    updatePlacement()
  }
}

function closeFromOutside(event: PointerEvent) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !panel.value?.contains(target)) open.value = false
}

onMounted(() => {
  window.addEventListener('pointerdown', closeFromOutside)
  window.addEventListener('resize', updatePlacement)
  window.addEventListener('scroll', updatePlacement, true)
})
onUnmounted(() => {
  window.removeEventListener('pointerdown', closeFromOutside)
  window.removeEventListener('resize', updatePlacement)
  window.removeEventListener('scroll', updatePlacement, true)
})
</script>

<template>
  <div ref="root" class="image-parameters" :class="{ 'is-open': open, 'is-compact': compact }">
    <button type="button" class="image-parameters__trigger" :disabled="disabled || !capabilities" aria-haspopup="dialog" :aria-expanded="open" @click="toggle">
      <i class="image-parameters__trigger-ratio" :style="ratioStyle(modelValue.aspectRatio, 20, 15, 6)" data-ratio-icon aria-hidden="true" />
      <span>{{ summary }}</span>
      <ChevronDown :size="15" aria-hidden="true" />
    </button>
    <Teleport to="body">
      <section v-if="open && capabilities" ref="panel" class="image-parameters__panel" :class="{ 'is-up': opensUp }" :style="panelStyle" role="dialog" aria-label="图片生成参数">
        <fieldset>
          <legend>清晰度</legend>
          <div class="image-parameters__segments">
            <button v-for="value in capabilities.clarities" :key="value" type="button" :class="{ 'is-selected': modelValue.clarity === value }" :aria-pressed="modelValue.clarity === value" @click="update('clarity', value)">{{ clarityLabel(value) }}</button>
          </div>
        </fieldset>
        <fieldset>
          <legend>比例</legend>
          <div class="image-parameters__ratios">
            <button v-for="value in capabilities.aspect_ratios" :key="value" type="button" :class="{ 'is-selected': modelValue.aspectRatio === value }" :aria-pressed="modelValue.aspectRatio === value" @click="update('aspectRatio', value)">
              <i :style="ratioStyle(value)" aria-hidden="true" />
              <span>{{ value }}</span>
            </button>
          </div>
        </fieldset>
        <fieldset>
          <legend>图片格式</legend>
          <div class="image-parameters__segments">
            <button v-for="value in capabilities.output_formats" :key="value" type="button" :class="{ 'is-selected': modelValue.outputFormat === value }" :aria-pressed="modelValue.outputFormat === value" @click="update('outputFormat', value)">{{ value.toUpperCase() }}</button>
          </div>
        </fieldset>
      </section>
    </Teleport>
  </div>
</template>

<style scoped>
.image-parameters { position: relative; min-width: 220px; }
.image-parameters__trigger { display: flex; width: 100%; min-height: 38px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 10px; color: var(--app-text-secondary); background: var(--app-surface); box-shadow: 0 1px 2px rgb(32 36 49 / 3%); cursor: pointer; font: inherit; font-size: 11px; }
.image-parameters__trigger:hover { border-color: var(--app-border-strong); color: var(--app-text); background: var(--app-surface-hover); }
.image-parameters.is-open .image-parameters__trigger { border-color: var(--app-accent); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.image-parameters__trigger:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.image-parameters__trigger:disabled { cursor: not-allowed; opacity: .5; }
.image-parameters__trigger-ratio { display: block; flex: 0 0 auto; box-sizing: border-box; border: 2px solid currentColor; border-radius: 2px; }
.image-parameters__trigger > span { min-width: 0; flex: 1; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.image-parameters__trigger > svg:last-child { flex: 0 0 auto; transition: transform .16s ease; }
.image-parameters.is-open .image-parameters__trigger > svg:last-child { transform: rotate(180deg); }
.image-parameters.is-compact .image-parameters__trigger { min-height: 34px; border-radius: 9px; font-size: 10px; }
.image-parameters__panel { position: fixed; z-index: 1200; display: grid; gap: 18px; overflow: visible; padding: 20px; border: 1px solid var(--app-border); border-radius: 16px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 24px 64px rgb(24 28 42 / 22%); }
.image-parameters__panel fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
.image-parameters__panel legend { margin: 0 0 9px; padding: 0; color: var(--app-text-secondary); font-size: 11px; font-weight: 700; }
.image-parameters__segments { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.image-parameters__panel button { min-height: 44px; border: 1px solid var(--app-border); border-radius: 10px; color: var(--app-text-secondary); background: var(--app-surface-muted); cursor: pointer; font: inherit; font-size: 11px; transition: border-color .15s ease, color .15s ease, background-color .15s ease, box-shadow .15s ease; }
.image-parameters__panel button:hover { border-color: var(--app-border-strong); color: var(--app-text); background: var(--app-surface-hover); }
.image-parameters__panel button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.image-parameters__panel button.is-selected { border-color: color-mix(in srgb,var(--app-accent) 70%,var(--app-border)); color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 12%,transparent); }
.image-parameters__ratios { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.image-parameters__ratios button { display: grid; min-height: 68px; place-items: center; align-content: center; gap: 7px; }
.image-parameters__ratios i { display: block; width: auto; height: auto; max-width: 31px; max-height: 22px; min-width: 8px; min-height: 8px; border: 2px solid currentColor; border-radius: 2px; }
.image-parameters__ratios span { font-size: 10px; }
@media (max-width: 560px) {
  .image-parameters__panel { gap: 14px; padding: 15px; }
  .image-parameters__ratios { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .image-parameters__panel button { min-height: 40px; }
  .image-parameters__ratios button { min-height: 58px; }
}
</style>
