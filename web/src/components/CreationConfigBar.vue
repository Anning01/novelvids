<script setup lang="ts">
withDefaults(defineProps<{
  modesLabel?: string
}>(), {
  modesLabel: '创作模式',
})
</script>

<template>
  <div class="creation-config-bar">
    <div class="creation-config-modes" :aria-label="modesLabel">
      <slot name="modes" />
    </div>
    <div class="creation-config-controls">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.creation-config-bar {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-top: 10px;
  padding: 8px;
  border: 1px solid #e8e9ef;
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 8px 22px rgb(35 39 52 / 5%);
}

.creation-config-modes,
.creation-config-controls {
  display: flex;
  align-items: center;
}

.creation-config-modes { gap: 3px; }
.creation-config-controls { gap: 7px; }

.creation-config-modes :deep(.app-button--soft) {
  min-height: 34px;
  padding: 0 11px;
  border-radius: 8px;
  color: var(--app-text-muted, #73798a);
  background: transparent;
  box-shadow: none;
  font-size: 12px;
}

.creation-config-modes :deep(.app-button--soft:hover) {
  background: var(--app-surface-hover, #f5f6fa);
}

.creation-config-modes :deep(.app-button--soft.is-active) {
  color: var(--app-accent, #5b5cf6);
  background: var(--app-accent-soft, #eeefff);
}

@media (max-width: 880px) {
  .creation-config-bar { align-items: stretch; flex-direction: column; }
  .creation-config-modes,
  .creation-config-controls { justify-content: center; }
}

@media (max-width: 620px) {
  .creation-config-modes,
  .creation-config-controls { width: 100%; flex-wrap: wrap; }
}
</style>
