<script setup lang="ts" generic="T extends string">
defineProps<{
  modelValue: T
  items: [{ value: T; label: string }, { value: T; label: string }]
  label: string
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: T] }>()
</script>

<template>
  <div class="app-segmented-switch" :class="{ 'is-second': modelValue === items[1].value }" role="group" :aria-label="label">
    <button v-for="item in items" :key="item.value" type="button" :aria-pressed="modelValue === item.value"
      :disabled="disabled" @click="emit('update:modelValue', item.value)">{{ item.label }}</button>
  </div>
</template>

<style scoped>
.app-segmented-switch { position: relative; isolation: isolate; display: inline-grid; flex: none; width: 108px; max-width: 100%; grid-template-columns: repeat(2,minmax(0,1fr)); padding: 2px; border: 1px solid var(--app-border); border-radius: 10px; background: var(--app-surface-muted); }
.app-segmented-switch::before { position: absolute; z-index: -1; top: 2px; bottom: 2px; left: 2px; width: calc((100% - 4px) / 2); border-radius: 7px; background: var(--home-accent,var(--app-accent)); content: ''; transform: translateX(0); transition: transform 280ms cubic-bezier(.22,1,.36,1); }
.app-segmented-switch.is-second::before { transform: translateX(100%); }
.app-segmented-switch button { display: inline-flex; min-width: 0; min-height: 24px; align-items: center; justify-content: center; padding: 0 4px; border: 0; border-radius: 7px; color: var(--app-text-secondary); background: transparent; font: inherit; font-size: 11px; font-weight: 600; white-space: nowrap; cursor: pointer; transition: color 160ms ease; }
.app-segmented-switch button:hover:not([aria-pressed='true']):not(:disabled) { color: var(--app-text); }
.app-segmented-switch button[aria-pressed='true'] { color: #fff; }
.app-segmented-switch button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; }
.app-segmented-switch button[aria-pressed='true']:focus-visible { outline-color: #fff; }
.app-segmented-switch button:disabled { cursor: not-allowed; opacity: .5; }
@media (prefers-reduced-motion: reduce) { .app-segmented-switch::before,.app-segmented-switch button { transition: none; } }
</style>
