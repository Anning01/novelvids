<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'

export interface AppMultiSelectOption {
  value: string
  label: string
}

const props = withDefaults(defineProps<{
  modelValue: string[]
  options: AppMultiSelectOption[]
  ariaLabel: string
  placeholder?: string
  maxMenuHeight?: number
  disabled?: boolean
}>(), {
  placeholder: '请选择',
  maxMenuHeight: 320,
  disabled: false,
})

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const root = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const menuPosition = ref({ top: 0, left: 0, width: 0 })
const opensUp = ref(false)

const selectedOptions = computed(() => props.options.filter(option => props.modelValue.includes(option.value)))
const displayValue = computed(() => selectedOptions.value.length
  ? selectedOptions.value.map(option => option.label).join('、')
  : props.placeholder)
const menuStyle = computed(() => ({
  width: `${menuPosition.value.width}px`,
  top: `${menuPosition.value.top}px`,
  left: `${menuPosition.value.left}px`,
  maxHeight: `${props.maxMenuHeight}px`,
}))

async function toggleMenu() {
  if (props.disabled) return
  open.value = !open.value
  if (!open.value) return
  await nextTick()
  updatePlacement()
}

function updatePlacement() {
  const rect = root.value?.getBoundingClientRect()
  if (!rect) return
  const estimatedHeight = Math.min(props.maxMenuHeight, props.options.length * 42 + 12)
  const roomBelow = window.innerHeight - rect.bottom
  opensUp.value = roomBelow < estimatedHeight + 12 && rect.top > roomBelow
  menuPosition.value = {
    top: opensUp.value ? rect.top - estimatedHeight - 7 : rect.bottom + 7,
    left: Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8)),
    width: rect.width,
  }
}

function toggleOption(value: string) {
  emit('update:modelValue', props.modelValue.includes(value)
    ? props.modelValue.filter(item => item !== value)
    : [...props.modelValue, value])
}

function closeFromOutside(event: PointerEvent) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !menu.value?.contains(target)) open.value = false
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
  <div ref="root" class="app-multi-select" :class="{ 'is-open': open, 'is-empty': !selectedOptions.length }" @keydown.esc="open = false">
    <AppButton
      type="button"
      variant="secondary"
      class="app-multi-select__trigger"
      :aria-label="ariaLabel"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :disabled="disabled"
      @click="toggleMenu"
    >
      <span>{{ displayValue }}</span>
      <span v-if="selectedOptions.length > 1" class="app-multi-select__count">{{ selectedOptions.length }}</span>
      <ChevronDown :size="14" />
    </AppButton>

    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        class="app-multi-select__menu"
        :style="menuStyle"
        role="listbox"
        aria-multiselectable="true"
        :aria-label="ariaLabel"
      >
        <AppButton
          v-for="option in options"
          :key="option.value"
          type="button"
          variant="ghost"
          class="app-multi-select__option"
          :class="{ 'is-selected': modelValue.includes(option.value) }"
          role="option"
          :aria-selected="modelValue.includes(option.value)"
          @click="toggleOption(option.value)"
        >
          <span class="app-multi-select__checkbox"><Check v-if="modelValue.includes(option.value)" :size="13" /></span>
          <span>{{ option.label }}</span>
        </AppButton>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.app-multi-select { position: relative; min-width: 104px; }
.app-multi-select__trigger { display: flex; width: 100%; min-height: 39px; align-items: center; gap: 8px; padding: 0 11px; border: 1px solid var(--app-border); border-radius: 9px; color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: none; font-size: 11px; }
.app-multi-select__trigger > span:first-child { min-width: 0; flex: 1; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.app-multi-select__trigger > svg { flex: 0 0 auto; color: var(--app-text-muted); transition: transform .15s ease; }
.app-multi-select.is-open .app-multi-select__trigger { border-color: var(--app-accent); color: var(--app-text); background: var(--app-surface-hover); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.app-multi-select.is-open .app-multi-select__trigger > svg { transform: rotate(180deg); }
.app-multi-select.is-empty .app-multi-select__trigger { color: var(--app-text-muted); }
.app-multi-select__count { display: grid; width: 19px; height: 19px; flex: 0 0 auto; place-items: center; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 9px; font-weight: 700; }
.app-multi-select__menu { position: fixed; z-index: 2000; display: grid; gap: 3px; overflow-y: auto; padding: 6px; border: 1px solid var(--app-border); border-radius: 11px; color: var(--app-text); background: var(--app-surface); box-shadow: var(--app-shadow); }
.app-multi-select__option { display: flex; width: 100%; min-height: 38px; align-items: center; justify-content: flex-start; gap: 9px; padding: 5px 8px; border-radius: 7px; color: var(--app-text-secondary); font-size: 11px; text-align: left; }
.app-multi-select__menu .app-multi-select__option:hover { color: var(--app-text); background: var(--app-surface-hover); }
.app-multi-select__menu .app-multi-select__option.is-selected { color: var(--app-accent); background: var(--app-accent-soft); }
.app-multi-select__checkbox { display: grid; width: 17px; height: 17px; flex: 0 0 auto; place-items: center; border-radius: 5px; color: var(--app-surface); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border-strong); }
.app-multi-select__option.is-selected .app-multi-select__checkbox { color: #211c2a; background: var(--app-accent); box-shadow: none; }
</style>
