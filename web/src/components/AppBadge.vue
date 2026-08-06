<script setup lang="ts">
export type AppBadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'
export type AppBadgeSize = 'sm' | 'md'

withDefaults(defineProps<{
  tone?: AppBadgeTone
  size?: AppBadgeSize
}>(), {
  tone: 'neutral',
  size: 'md',
})
</script>

<template>
  <span class="app-badge" :class="[`app-badge--${tone}`, `app-badge--${size}`]">
    <slot />
  </span>
</template>

<style scoped>
.app-badge {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-weight: 620;
  line-height: 1;
  white-space: nowrap;
}
.app-badge--sm { min-height: 20px; padding: 0 7px; font-size: 9px; }
.app-badge--md { min-height: 24px; padding: 0 9px; font-size: 10px; }
.app-badge--neutral { border-color: #e2e4ea; color: #717789; background: #f3f4f7; }
.app-badge--accent { border-color: #dedfff; color: #5c5ee8; background: #f0f0ff; }
.app-badge--success { border-color: #d8eee4; color: #278363; background: #eaf7f1; }
.app-badge--warning { border-color: #f2e2d1; color: #b7733d; background: #fff3e9; }
.app-badge--danger { border-color: #f1d9dd; color: #bb5b68; background: #fff0f2; }
</style>
