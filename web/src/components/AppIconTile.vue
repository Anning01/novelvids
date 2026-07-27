<script setup lang="ts">
export type AppIconTileTone = 'accent' | 'image' | 'video' | 'neutral'
export type AppIconTileSize = 'sm' | 'md' | 'lg' | 'xl'

withDefaults(defineProps<{
  tone?: AppIconTileTone
  size?: AppIconTileSize
}>(), {
  tone: 'accent',
  size: 'md',
})
</script>

<template>
  <span
    class="app-icon-tile"
    :class="[`app-icon-tile--${tone}`, `app-icon-tile--${size}`]"
    aria-hidden="true"
  >
    <slot />
  </span>
</template>

<style scoped>
.app-icon-tile {
  --app-icon-tile-color: var(--app-accent);
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid color-mix(in srgb,var(--app-icon-tile-color) 18%,var(--app-border));
  color: var(--app-icon-tile-color);
  background: color-mix(in srgb,var(--app-icon-tile-color) 12%,var(--app-surface));
  box-shadow: 0 8px 22px color-mix(in srgb,var(--app-icon-tile-color) 9%,transparent);
}

.app-icon-tile--sm { width: 40px; height: 40px; border-radius: 11px; }
.app-icon-tile--md { width: 44px; height: 44px; border-radius: 12px; }
.app-icon-tile--lg { width: 46px; height: 46px; border-radius: 12px; }
.app-icon-tile--xl { width: 52px; height: 52px; border-radius: 15px; }
.app-icon-tile--image { --app-icon-tile-color: #c06b9d; }
.app-icon-tile--video { --app-icon-tile-color: #58a8ad; }
.app-icon-tile--neutral { --app-icon-tile-color: var(--app-text-muted); }
</style>
