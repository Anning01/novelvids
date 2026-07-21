<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

export interface AppSelectOption {
  value: string
  label: string
  image?: string
  separator?: boolean
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: Array<string | AppSelectOption>
  ariaLabel: string
  menuLabel?: string
  menuWidth?: number
  maxMenuHeight?: number
  align?: 'start' | 'end'
  disabled?: boolean
}>(), {
  menuLabel: '',
  menuWidth: undefined,
  maxMenuHeight: 360,
  align: 'start',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)
const opensUp = ref(false)

const normalizedOptions = computed<AppSelectOption[]>(() => props.options.map(option => (
  typeof option === 'string' ? { value: option, label: option } : option
)))
const selectedOption = computed(() => normalizedOptions.value.find(option => option.value === props.modelValue) ?? normalizedOptions.value[0])
const menuStyle = computed(() => ({
  maxHeight: `${props.maxMenuHeight}px`,
  width: props.menuWidth ? `${props.menuWidth}px` : undefined,
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
  const estimatedMenuHeight = Math.min(props.maxMenuHeight, normalizedOptions.value.length * 38 + (props.menuLabel ? 34 : 14))
  const roomBelow = window.innerHeight - rect.bottom
  opensUp.value = roomBelow < estimatedMenuHeight + 12 && rect.top > roomBelow
}

function selectOption(option: AppSelectOption) {
  emit('update:modelValue', option.value)
  open.value = false
}

function closeFromOutside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}

function closeFromEscape() {
  open.value = false
}

onMounted(() => {
  window.addEventListener('pointerdown', closeFromOutside)
  window.addEventListener('resize', updatePlacement)
})
onUnmounted(() => {
  window.removeEventListener('pointerdown', closeFromOutside)
  window.removeEventListener('resize', updatePlacement)
})
</script>

<template>
  <div ref="root" class="app-select" :class="{ 'is-open': open, 'is-disabled': disabled }" @keydown.esc="closeFromEscape">
    <AppButton
      type="button"
      class="app-select__trigger"
      :aria-label="ariaLabel"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :disabled="disabled"
      @click="toggleMenu"
    >
      <span class="app-select__leading">
        <slot name="leading" :option="selectedOption">
          <img v-if="selectedOption?.image" :src="selectedOption.image" alt="" />
        </slot>
      </span>
      <span class="app-select__value">{{ selectedOption?.label }}</span>
      <ChevronDown class="app-select__chevron" :size="14" />
    </AppButton>

    <div
      v-if="open"
      class="app-select__menu"
      :class="{ 'is-up': opensUp, 'is-end': align === 'end' }"
      :style="menuStyle"
      role="listbox"
      :aria-label="ariaLabel"
    >
      <p v-if="menuLabel" class="app-select__menu-label">{{ menuLabel }}</p>
      <AppButton
        v-for="option in normalizedOptions"
        :key="option.value"
        type="button"
        class="app-select__option"
        :class="{ 'is-selected': option.value === modelValue, 'has-separator': option.separator }"
        role="option"
        :aria-selected="option.value === modelValue"
        @click="selectOption(option)"
      >
        <span class="app-select__option-leading">
          <slot name="option-leading" :option="option">
            <img v-if="option.image" :src="option.image" alt="" />
          </slot>
        </span>
        <span>{{ option.label }}</span>
        <Check v-if="option.value === modelValue" class="app-select__check" :size="15" />
      </AppButton>
    </div>
  </div>
</template>

<style scoped>
.app-select {
  position: relative;
  min-width: 104px;
}

.app-select__trigger {
  display: flex;
  width: 100%;
  min-height: 36px;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid #e0e3eb;
  border-radius: 9px;
  color: #4f5464;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
  box-shadow: 0 1px 2px rgb(32 36 49 / 3%);
  transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease;
}

.app-select__trigger:hover {
  border-color: #cfd3df;
  background: #fcfcfe;
}

.app-select.is-open .app-select__trigger {
  border-color: #9495f8;
  box-shadow: 0 0 0 3px rgb(91 92 246 / 10%);
}

.app-select__trigger:focus-visible {
  outline: 2px solid #7778f3;
  outline-offset: 2px;
}

.app-select__trigger:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.app-select__leading,
.app-select__option-leading {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  color: #767c8d;
}

.app-select__leading:empty,
.app-select__option-leading:empty {
  display: none;
}

.app-select__leading img,
.app-select__option-leading img {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  object-fit: cover;
}

.app-select__value {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-select__chevron {
  flex: 0 0 auto;
  color: #8d92a1;
  transition: transform .15s ease;
}

.app-select.is-open .app-select__chevron {
  transform: rotate(180deg);
}

.app-select__menu {
  position: absolute;
  top: calc(100% + 7px);
  left: 0;
  z-index: 100;
  min-width: 100%;
  overflow: auto;
  padding: 6px;
  border: 1px solid #e1e4eb;
  border-radius: 11px;
  background: #fff;
  box-shadow: 0 18px 44px rgb(32 36 49 / 14%);
}

.app-select__menu.is-up {
  top: auto;
  bottom: calc(100% + 7px);
}

.app-select__menu.is-end {
  right: 0;
  left: auto;
}

.app-select__menu-label {
  margin: 4px 8px 6px;
  color: #969baa;
  font-size: 11px;
}

.app-select__option {
  display: flex;
  width: 100%;
  min-height: 36px;
  align-items: center;
  gap: 9px;
  padding: 5px 8px;
  border: 0;
  border-radius: 7px;
  color: #444958;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}

.app-select__option:hover {
  background: #f5f6fa;
}

.app-select__option.is-selected {
  color: #5557e8;
  background: #f0f0ff;
}

.app-select__option.has-separator {
  margin-top: 5px;
  padding-top: 9px;
  border-top: 1px solid #eceef3;
  border-radius: 0 0 7px 7px;
}

.app-select__check {
  margin-left: auto;
  flex: 0 0 auto;
  color: #5b5cf6;
}
</style>
