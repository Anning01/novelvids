<script setup lang="ts">
import { nextTick, type Component } from 'vue'

export interface AppTabItem {
  value: string
  label: string
  icon?: Component
  disabled?: boolean
}

const props = defineProps<{
  modelValue: string
  items: AppTabItem[]
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

function select(item: AppTabItem) {
  if (!item.disabled && item.value !== props.modelValue) emit('update:modelValue', item.value)
}

function moveFocus(event: KeyboardEvent, currentIndex: number, direction: 1 | -1) {
  const root = (event.currentTarget as HTMLElement).parentElement
  let nextIndex = currentIndex
  for (let attempts = 0; attempts < props.items.length; attempts += 1) {
    nextIndex = (nextIndex + direction + props.items.length) % props.items.length
    if (!props.items[nextIndex]?.disabled) break
  }
  const item = props.items[nextIndex]
  if (!item || item.disabled) return
  select(item)
  void nextTick(() => root?.querySelector<HTMLElement>(`[data-tab-index="${nextIndex}"]`)?.focus())
}
</script>

<template>
  <div class="app-tabs" role="tablist" :aria-label="label">
    <button
      v-for="(item, index) in items"
      :key="item.value"
      type="button"
      role="tab"
      class="app-tabs__tab"
      :class="{ 'is-active': modelValue === item.value }"
      :aria-selected="modelValue === item.value"
      :tabindex="modelValue === item.value ? 0 : -1"
      :disabled="item.disabled"
      :data-tab-index="index"
      @click="select(item)"
      @keydown.left.prevent="moveFocus($event, index, -1)"
      @keydown.right.prevent="moveFocus($event, index, 1)"
    >
      <component :is="item.icon" v-if="item.icon" class="app-tabs__icon" :size="16" aria-hidden="true" />
      <span>{{ item.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.app-tabs {
  display: flex;
  width: 100%;
  max-width: 100%;
  align-items: center;
  gap: 22px;
  border-bottom: 1px solid var(--app-border);
}
.app-tabs__tab {
  position: relative;
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  gap: 7px;
  padding: 0 2px;
  border: 0;
  outline: 0;
  color: var(--app-text-muted);
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 650;
  line-height: 1;
  white-space: nowrap;
  transition: color .16s ease;
}
.app-tabs__tab::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  border-radius: 99px 99px 0 0;
  background: transparent;
  content: '';
  transition: background-color .16s ease;
}
.app-tabs__tab:hover:not(:disabled) {
  color: var(--app-text-secondary);
}
.app-tabs__tab.is-active {
  color: var(--app-text);
}
.app-tabs__tab.is-active::after {
  background: var(--app-accent);
}
.app-tabs__tab:focus-visible {
  border-radius: 4px;
  outline: 3px solid color-mix(in srgb,var(--app-accent) 22%,transparent);
  outline-offset: 3px;
}
.app-tabs__tab:disabled { cursor: not-allowed; opacity: .45; }
.app-tabs__icon { flex: 0 0 auto; color: currentColor; }
.app-tabs__tab.is-active .app-tabs__icon { color: var(--app-accent); }
@media (max-width: 520px) {
  .app-tabs { gap: 18px; }
}
@media (prefers-reduced-motion: reduce) {
  .app-tabs__tab,.app-tabs__tab::after { transition: none; }
}
</style>
