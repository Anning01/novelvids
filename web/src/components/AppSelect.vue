<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'
import AppButton from './AppButton.vue'

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
  menuClass?: string
  menuZIndex?: number
  menuWidth?: number | 'auto' | string
  maxMenuHeight?: number
  align?: 'start' | 'end'
  density?: 'default' | 'compact'
  disabled?: boolean
}>(), {
  menuLabel: '',
  menuClass: '',
  menuZIndex: 1000,
  menuWidth: undefined,
  maxMenuHeight: 360,
  align: 'start',
  density: 'default',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const root = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const opensUp = ref(false)
const menuPosition = ref({ top: 0, left: 0, width: 0 })
const menuTheme = ref<Record<string, string>>({})

const normalizedOptions = computed<AppSelectOption[]>(() => props.options.map(option => (
  typeof option === 'string' ? { value: option, label: option } : option
)))
const selectedOption = computed(() => normalizedOptions.value.find(option => option.value === props.modelValue) ?? normalizedOptions.value[0])
const menuStyle = computed(() => {
  const style: Record<string, string | number | undefined> = {
    ...menuTheme.value,
    zIndex: props.menuZIndex,
    maxHeight: `${props.maxMenuHeight}px`,
    top: `${menuPosition.value.top}px`,
    left: `${menuPosition.value.left}px`,
  }
  if (props.menuWidth && props.menuWidth !== 'auto') {
    style.width = typeof props.menuWidth === 'number' ? `${props.menuWidth}px` : props.menuWidth
  } else {
    style.width = 'max-content'
    style.maxWidth = 'calc(100vw - 16px)'
  }
  return style
})

async function toggleMenu(fromEnd = false) {
  if (props.disabled || !normalizedOptions.value.length) return
  open.value = !open.value
  if (!open.value) return
  if (root.value) {
    const style = getComputedStyle(root.value)
    const properties = ['--app-surface', '--app-surface-raised', '--app-surface-muted', '--app-surface-hover',
      '--app-border', '--app-border-strong', '--app-text', '--app-text-secondary', '--app-text-muted', '--app-accent', '--app-accent-soft', '--app-shadow']
    menuTheme.value = Object.fromEntries(properties.map(name => [name, style.getPropertyValue(name).trim()]).filter(([, value]) => value))
  }
  updatePlacement()
  await nextTick()
  updatePlacement()
  const selected = normalizedOptions.value.findIndex(option => option.value === props.modelValue)
  focusOption(selected < 0 ? (fromEnd ? normalizedOptions.value.length - 1 : 0) : selected)
}

function focusOption(index: number) {
  const option = menu.value?.querySelectorAll<HTMLElement>('[role="option"]')[index]
  option?.focus({ preventScroll: true })
  option?.scrollIntoView({ block: 'nearest' })
}

function focusTrigger() {
  root.value?.querySelector('button')?.focus()
}

function navigateMenu(event: KeyboardEvent) {
  if (event.key === 'Tab') {
    focusTrigger()
    open.value = false
    return
  }
  const options = Array.from(menu.value?.querySelectorAll('[role="option"]') ?? [])
  const current = options.indexOf(document.activeElement as Element)
  let next: number
  switch (event.key) {
    case 'Home': next = 0; break
    case 'End': next = options.length - 1; break
    case 'ArrowDown': next = Math.min(current + 1, options.length - 1); break
    case 'ArrowUp': next = Math.max(current - 1, 0); break
    default: return
  }
  event.preventDefault()
  event.stopPropagation()
  focusOption(next)
}

function updatePlacement() {
  const rect = root.value?.getBoundingClientRect()
  if (!rect) return
  const estimatedMenuHeight = Math.min(props.maxMenuHeight, normalizedOptions.value.length * 38 + (props.menuLabel ? 34 : 14))
  const menuHeight = menu.value?.getBoundingClientRect().height || estimatedMenuHeight
  const roomBelow = window.innerHeight - rect.bottom
  opensUp.value = roomBelow < menuHeight + 12 && rect.top > roomBelow
  const measuredMenuWidth = menu.value?.getBoundingClientRect().width || 0
  const width = (props.menuWidth && props.menuWidth !== 'auto')
    ? (typeof props.menuWidth === 'number' ? props.menuWidth : Number.parseFloat(props.menuWidth) || rect.width)
    : (measuredMenuWidth || rect.width)
  const left = props.align === 'end' ? rect.right - width : rect.left
  menuPosition.value = {
    top: opensUp.value ? rect.top - menuHeight - 7 : rect.bottom + 7,
    left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
    width,
  }
}

function selectOption(option: AppSelectOption) {
  emit('update:modelValue', option.value)
  focusTrigger()
  open.value = false
}

watch(() => props.disabled || !normalizedOptions.value.length, unavailable => {
  if (unavailable) open.value = false
})

function closeFromOutside(event: PointerEvent) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !menu.value?.contains(target)) open.value = false
}

function closeFromEscape(event: KeyboardEvent) {
  // 菜单展开时消费 Esc，避免同时关闭外层弹窗；已关闭时放行给外层弹窗。
  if (!open.value) return
  event.preventDefault()
  event.stopPropagation()
  focusTrigger()
  open.value = false
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
  <div
    ref="root"
    class="app-select"
    :class="{ 'is-open': open, 'is-disabled': disabled, 'is-compact': density === 'compact' }"
    @keydown.esc="closeFromEscape"
  >
    <AppButton
      type="button"
      variant="secondary"
      class="app-select__trigger"
      :aria-label="ariaLabel"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :disabled="disabled || !normalizedOptions.length"
      @click="toggleMenu()"
      @keydown.down.prevent.stop="!open && toggleMenu()"
      @keydown.up.prevent.stop="!open && toggleMenu(true)"
    >
      <span class="app-select__leading">
        <slot name="leading" :option="selectedOption">
          <img v-if="selectedOption?.image" :src="selectedOption.image" alt="" />
        </slot>
      </span>
      <span class="app-select__value" :title="selectedOption?.label">{{ selectedOption?.label }}</span>
      <ChevronDown class="app-select__chevron" :size="14" />
    </AppButton>

    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        class="app-select__menu"
        :class="[menuClass, { 'is-up': opensUp, 'is-end': align === 'end', 'is-compact': density === 'compact' }]"
        :style="menuStyle"
        role="listbox"
        :aria-label="ariaLabel"
        @keydown.esc="closeFromEscape"
        @keydown="navigateMenu"
      >
        <p v-if="menuLabel" class="app-select__menu-label">{{ menuLabel }}</p>
        <AppButton
          v-for="option in normalizedOptions"
          :key="option.value"
          type="button"
          class="app-select__option"
          :class="{ 'is-selected': option.value === modelValue, 'has-separator': option.separator }"
          role="option"
          tabindex="-1"
          :aria-selected="option.value === modelValue"
          @click="selectOption(option)"
        >
          <span class="app-select__option-leading">
            <slot name="option-leading" :option="option">
              <img v-if="option.image" :src="option.image" alt="" />
            </slot>
          </span>
          <span :title="option.label">{{ option.label }}</span>
          <Check
            class="app-select__check"
            :class="{ 'is-invisible': option.value !== modelValue }"
            :size="15"
            aria-hidden="true"
          />
        </AppButton>
      </div>
    </Teleport>
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
  border: 1px solid var(--app-border);
  border-radius: 9px;
  color: var(--app-text-secondary);
  background: var(--app-surface);
  cursor: pointer;
  font-size: 12px;
  box-shadow: 0 1px 2px rgb(32 36 49 / 3%);
  transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease;
}

.app-select__trigger:hover {
  border-color: var(--app-border-strong);
  color: var(--app-text);
  background: var(--app-surface-hover);
}

.app-select.is-open .app-select__trigger {
  border-color: var(--app-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent);
}

.app-select__trigger:focus-visible {
  outline: 2px solid var(--app-accent);
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
  color: var(--app-text-muted);
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
  color: var(--app-text-muted);
  transition: transform .15s ease;
}

.app-select.is-open .app-select__chevron {
  transform: rotate(180deg);
}

.app-select__menu {
  position: fixed;
  z-index: 1000;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: none;
  padding: 6px;
  border: 1px solid var(--app-border);
  border-radius: 11px;
  color: var(--app-text);
  background: var(--app-surface);
  box-shadow: var(--app-shadow);
}

.app-select__menu::-webkit-scrollbar { display: none; }

.app-select__menu-label {
  margin: 4px 8px 6px;
  color: var(--app-text-muted);
  font-size: 11px;
}

.app-select__option {
  display: flex;
  width: 100%;
  min-width: 0;
  min-height: 36px;
  align-items: center;
  justify-content: flex-start;
  gap: 9px;
  padding: 5px 8px;
  border: 0;
  border-radius: 7px;
  color: var(--app-text-secondary);
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}

.app-select__option > span:nth-child(2) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.app-select__option:hover {
  color: var(--app-text);
  background: var(--app-surface-hover);
}

.app-select__option:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
}

.app-select__option.is-selected {
  color: var(--app-accent);
  background: var(--app-accent-soft);
}

.app-select__option.has-separator {
  margin-top: 5px;
  padding-top: 9px;
  border-top: 1px solid var(--app-border);
  border-radius: 0 0 7px 7px;
}

.app-select__check {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--app-accent);
}

.app-select__check.is-invisible {
  visibility: hidden;
  pointer-events: none;
}

.app-select.is-compact .app-select__trigger {
  min-height: 34px;
  gap: 7px;
  padding-inline: 10px 8px;
  border-radius: 9px;
  font-size: 11px;
}

.app-select__menu.is-compact {
  padding: 5px;
  border-radius: 10px;
}

.app-select__menu.is-compact .app-select__option {
  min-height: 32px;
  gap: 7px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
}
</style>
