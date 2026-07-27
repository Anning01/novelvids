<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { Check, Monitor, Moon, Sun } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import { appThemeControllerKey, type AppThemePreference, useAppThemeController } from '@/shared/appTheme'

withDefaults(defineProps<{
  placement?: 'floating' | 'sidebar'
}>(), {
  placement: 'floating',
})

const theme = inject(appThemeControllerKey) ?? useAppThemeController()
const open = ref(false)
const options: Array<{ value: AppThemePreference; label: string; description: string; icon: typeof Monitor }> = [
  { value: 'system', label: '跟随系统', description: '自动使用系统外观', icon: Monitor },
  { value: 'light', label: '浅色', description: '始终使用浅色外观', icon: Sun },
  { value: 'dark', label: '深色', description: '始终使用深色外观', icon: Moon },
]
const activeOption = computed(() => options.find(option => option.value === theme.preference.value) ?? options[0])
const activeLabel = computed(() => activeOption.value.label)
const activeIcon = computed(() => theme.resolvedTheme.value === 'dark' ? Moon : Sun)

function select(preference: AppThemePreference) {
  theme.setPreference(preference)
  open.value = false
}
</script>

<template>
  <div class="app-theme-toggle" :class="`is-${placement}`" @keydown.esc="open = false">
    <AppButton
      class="app-theme-toggle__trigger"
      variant="secondary"
      size="sm"
      :icon-only="placement === 'floating'"
      :aria-label="`外观主题：${activeLabel}`"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="open = !open"
    >
      <component :is="activeIcon" :size="17" />
      <span v-if="placement === 'sidebar'" class="app-theme-toggle__label">
        <span>外观</span>
        <small>{{ activeLabel }}</small>
      </span>
    </AppButton>
    <div v-if="open" class="app-theme-toggle__menu" role="menu" aria-label="选择外观主题">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        role="menuitemradio"
        :aria-checked="theme.preference.value === option.value"
        :data-theme-preference="option.value"
        @click="select(option.value)"
      >
        <component :is="option.icon" :size="16" />
        <span><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span>
        <Check v-if="theme.preference.value === option.value" :size="15" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.app-theme-toggle { position: fixed; right: 18px; bottom: 18px; z-index: 110; }
.app-theme-toggle__trigger { min-width: 42px; min-height: 42px; border-radius: 12px; color: var(--app-text-secondary); background: var(--app-surface-raised); box-shadow: inset 0 0 0 1px var(--app-border),0 10px 28px rgb(22 24 34 / 14%); backdrop-filter: blur(14px); }
.app-theme-toggle__trigger:hover { color: var(--app-accent); background: var(--app-surface-hover); }
.app-theme-toggle__menu { position: absolute; right: 0; bottom: 46px; display: grid; width: 228px; gap: 4px; padding: 6px; border: 1px solid var(--app-border); border-radius: 14px; color: var(--app-text); background: color-mix(in srgb,var(--app-surface-raised) 94%,transparent); box-shadow: 0 20px 56px rgb(18 20 29 / 22%); backdrop-filter: blur(18px); }
.app-theme-toggle__menu > button { display: grid; min-height: 52px; grid-template-columns: 28px minmax(0,1fr) 18px; align-items: center; gap: 8px; padding: 7px 9px; border-radius: 9px; color: var(--app-text-secondary); background: transparent; cursor: pointer; text-align: left; }
.app-theme-toggle__menu > button:hover { color: var(--app-text); background: var(--app-surface-hover); }
.app-theme-toggle__menu > button[aria-checked='true'] { color: var(--app-accent); background: var(--app-accent-soft); }
.app-theme-toggle__menu > button > span { display: grid; gap: 3px; }
.app-theme-toggle__menu strong { color: inherit; font-size: 11px; }
.app-theme-toggle__menu small { color: var(--app-text-muted); font-size: 9px; font-weight: 450; }
.app-theme-toggle__menu > button > svg:last-child { justify-self: end; }
.app-theme-toggle.is-sidebar { position: relative; right: auto; bottom: auto; z-index: 1; margin: auto 8px 12px; }
.app-theme-toggle.is-sidebar .app-theme-toggle__trigger { width: 100%; min-height: 44px; justify-content: flex-start; gap: 10px; padding: 0 12px; border-radius: 10px; box-shadow: inset 0 0 0 1px var(--app-border); backdrop-filter: none; }
.app-theme-toggle__label { display: flex; min-width: 0; flex: 1; align-items: center; justify-content: space-between; gap: 8px; font-size: 13px; }
.app-theme-toggle__label small { overflow: hidden; color: var(--app-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.app-theme-toggle.is-sidebar .app-theme-toggle__menu { right: auto; bottom: 52px; left: 0; }
@media (max-width: 720px) { .app-theme-toggle { right: 12px; bottom: 12px; }.app-theme-toggle__menu { width: min(228px,calc(100vw - 24px)); } }
@media (max-width: 720px) {
  .app-theme-toggle.is-sidebar { margin-right: 8px; margin-left: 8px; }
  .app-theme-toggle.is-sidebar .app-theme-toggle__trigger { justify-content: center; padding: 0; }
  .app-theme-toggle.is-sidebar .app-theme-toggle__label { display: none; }
  .app-theme-toggle.is-sidebar .app-theme-toggle__menu { position: fixed; right: 12px; bottom: 12px; left: 80px; width: auto; }
}
</style>
