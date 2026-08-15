<script setup lang="ts">
import { Check, ChevronDown } from 'lucide-vue-next'
import type { Component } from 'vue'
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { claimExclusivePopover } from '@/shared/exclusivePopover'

const props = defineProps<{
  modelValue: string
  options: Array<{ label: string; value: string; disabled?: boolean; icon?: Component }>
  label: string
  placeholder?: string
  iconOnly?: boolean
  fallbackIcon?: Component
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const container = ref<HTMLElement | null>(null)
const open = ref(false)
const openAbove = ref(false)
const exclusiveSource = Symbol('workbench-select')
let releaseExclusive: (() => void) | null = null
const selectedOption = computed(() => props.options.find(option => option.value === props.modelValue))

function updatePlacement() {
  const trigger = container.value?.querySelector<HTMLElement>('.workbench-select__trigger')
  const boundary = container.value?.closest<HTMLElement>('.workbench-prompt-panel, .workbench-node-frame')
  if (!trigger) return
  const triggerRect = trigger.getBoundingClientRect()
  const boundaryRect = boundary?.getBoundingClientRect()
  const menuHeight = Math.min(props.options.length * 34 + 12, 220)
  const lowerBoundary = Math.min(window.innerHeight, boundaryRect?.bottom ?? window.innerHeight)
  const upperBoundary = Math.max(0, boundaryRect?.top ?? 0)
  const spaceBelow = lowerBoundary - triggerRect.bottom
  const spaceAbove = triggerRect.top - upperBoundary
  openAbove.value = spaceBelow < menuHeight && spaceAbove > spaceBelow
}

function beginExclusiveSession() {
  releaseExclusive?.()
  releaseExclusive = claimExclusivePopover(exclusiveSource, close)
}

function toggle() {
  if (open.value) {
    close()
    return
  }
  updatePlacement()
  beginExclusiveSession()
  open.value = true
}

function select(value: string) {
  emit('update:modelValue', value)
  close()
}

function close() {
  open.value = false
  releaseExclusive?.()
  releaseExclusive = null
}

function handleFocusOut(event: FocusEvent) {
  const next = event.relatedTarget as Node | null
  if (!next || !container.value?.contains(next)) close()
}

async function openAndFocus(last = false) {
  updatePlacement()
  beginExclusiveSession()
  open.value = true
  await nextTick()
  const options = [...(container.value?.querySelectorAll<HTMLButtonElement>('[role="option"]:not(:disabled)') ?? [])]
  const selected = options.find(option => option.ariaSelected === 'true')
  ;(selected ?? options[last ? options.length - 1 : 0])?.focus()
}

function moveOptionFocus(event: KeyboardEvent, direction: 1 | -1) {
  const options = [...(container.value?.querySelectorAll<HTMLButtonElement>('[role="option"]:not(:disabled)') ?? [])]
  const index = options.indexOf(document.activeElement as HTMLButtonElement)
  options[(index + direction + options.length) % options.length]?.focus()
  event.preventDefault()
}

function closeAndFocus() {
  close()
  container.value?.querySelector<HTMLButtonElement>('.workbench-select__trigger')?.focus()
}

onBeforeUnmount(close)
</script>

<template>
  <div
    ref="container"
    class="workbench-select nodrag nowheel"
    :class="{ 'is-open': open, 'is-above': openAbove }"
    @focusout="handleFocusOut"
    @pointerdown.stop
    @click.stop
    @wheel.stop
  >
    <button
      type="button"
      class="workbench-select__trigger nodrag nowheel"
      :aria-label="label"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :data-state="open ? 'open' : 'closed'"
      @click="toggle"
      @keydown.down.prevent="openAndFocus()"
      @keydown.up.prevent="openAndFocus(true)"
      @keydown.esc.stop.prevent="close"
    >
      <component
        :is="selectedOption?.icon || fallbackIcon"
        v-if="iconOnly && (selectedOption?.icon || fallbackIcon)"
        :size="18"
        aria-hidden="true"
      />
      <span v-else :class="{ 'is-placeholder': !selectedOption }">{{ selectedOption?.label || placeholder || '请选择' }}</span>
      <ChevronDown v-if="!iconOnly" :size="15" aria-hidden="true" />
    </button>
    <div
      v-if="open"
      class="workbench-select__content workbench-scroll-region nowheel"
      :class="{ 'is-above': openAbove }"
      role="listbox"
      :aria-label="`${label}选项`"
      @keydown.down="moveOptionFocus($event, 1)"
      @keydown.up="moveOptionFocus($event, -1)"
      @keydown.home.prevent="openAndFocus()"
      @keydown.end.prevent="openAndFocus(true)"
      @keydown.esc.stop.prevent="closeAndFocus"
    >
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        class="workbench-select__item"
        role="option"
        :disabled="option.disabled"
        :aria-selected="option.value === modelValue"
        :data-state="option.value === modelValue ? 'checked' : 'unchecked'"
        @pointerdown.prevent
        @click="select(option.value)"
      >
        <span class="workbench-select__option">
          <component :is="option.icon" v-if="option.icon" :size="16" aria-hidden="true" />
          <span class="workbench-select__option-label">{{ option.label }}</span>
        </span>
        <Check v-if="option.value === modelValue" :size="13" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
