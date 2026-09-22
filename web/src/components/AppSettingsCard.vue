<script setup lang="ts">
import AppIconTile from './AppIconTile.vue'

defineProps<{ title: string; description: string }>()
</script>

<template>
  <article class="app-settings-card">
    <header class="app-settings-card__heading">
      <AppIconTile size="sm"><slot name="icon" /></AppIconTile>
      <div class="app-settings-card__copy"><h3>{{ title }}</h3><p>{{ description }}</p></div>
      <div v-if="$slots.status" class="app-settings-card__status"><slot name="status" /></div>
    </header>
    <div class="app-settings-card__body"><slot /></div>
    <footer v-if="$slots.footer" class="app-settings-card__footer"><slot name="footer" /></footer>
  </article>
</template>

<style scoped>
.app-settings-card { min-width: 0; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); color: var(--app-text); overflow: hidden; }
.app-settings-card__heading { display: flex; align-items: center; gap: 12px; padding: 22px 24px 18px; }
.app-settings-card__copy { flex: 1; min-width: 0; }
h3 { margin: 0; font-size: 15px; line-height: 1.5; font-weight: 650; }
p { margin: 4px 0 0; font-size: 12px; line-height: 1.6; color: var(--app-text-secondary); }
.app-settings-card__status { flex-shrink: 0; font-size: 11px; color: var(--app-text-secondary); }
.app-settings-card__body { padding: 0 24px 20px; }
.app-settings-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 24px; border-top: 1px solid var(--app-border); background: color-mix(in srgb, var(--app-surface-muted) 45%, var(--app-surface)); font-size: 11px; color: var(--app-text-secondary); }
@media (max-width: 560px) {
  .app-settings-card__heading { padding: 18px 16px 16px; flex-wrap: wrap; }
  .app-settings-card__status { margin-left: 52px; }
  .app-settings-card__body { padding: 0 16px 16px; }
  .app-settings-card__footer { padding: 12px 16px; flex-wrap: wrap; }
}
</style>
