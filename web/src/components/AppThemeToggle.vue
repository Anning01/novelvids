<script setup lang="ts">
import { tr } from '@/i18n'

import { computed, inject } from 'vue'
import { ChevronRight, Monitor, Moon, Sun } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import PreferenceMenu from './PreferenceMenu.vue'
import { appThemeControllerKey, type AppThemePreference, useAppThemeController } from '@/shared/appTheme'

withDefaults(defineProps<{
  placement?: 'floating' | 'sidebar' | 'inline'
}>(), {
  placement: 'floating',
})

const theme = inject(appThemeControllerKey) ?? useAppThemeController()
const options: Array<{ value: AppThemePreference; label: string; icon: typeof Monitor }> = [
  { value: 'system', get label() { return tr('跟随系统') }, icon: Monitor },
  { value: 'light', get label() { return tr('浅色') }, icon: Sun },
  { value: 'dark', get label() { return tr('深色') }, icon: Moon },
]
const activeOption = computed(() => options.find(option => option.value === theme.preference.value) ?? options[0])
const activeLabel = computed(() => activeOption.value.label)
const activeIcon = computed(() => theme.resolvedTheme.value === 'dark' ? Moon : Sun)

function select(value: string) {
  theme.setPreference(value as AppThemePreference)
}
</script>

<template>
  <PreferenceMenu class="app-theme-toggle" :class="`is-${placement}`" :placement="placement"
    :model-value="theme.preference.value" :options="options" :label="tr('选择外观主题')" @update:model-value="select">
    <template #trigger="{ toggle, open }">
      <AppButton class="app-theme-toggle__trigger" variant="secondary" size="sm" :icon-only="placement !== 'sidebar'"
        :aria-label="tr('外观主题：{p0}', { p0: activeLabel })" aria-haspopup="menu" :aria-expanded="open" @click="toggle">
        <component :is="activeIcon" :size="17" />
        <span v-if="placement === 'sidebar'" class="app-theme-toggle__label"><span>{{ tr('外观') }}</span><small>{{ activeLabel }}</small></span>
        <ChevronRight v-if="placement === 'sidebar'" class="app-theme-toggle__chevron" :size="14" aria-hidden="true" />
      </AppButton>
    </template>
  </PreferenceMenu>
</template>

<style scoped>
.app-theme-toggle.is-floating { position: fixed; right: 18px; bottom: 18px; z-index: 110; }
.app-theme-toggle__trigger { min-width: 42px; min-height: 42px; border-radius: 12px; color: var(--app-text-secondary); background: var(--app-surface-raised); box-shadow: inset 0 0 0 1px var(--app-border),0 10px 28px rgb(22 24 34 / 14%); backdrop-filter: blur(14px); }
.app-theme-toggle__trigger:hover { color: var(--app-accent); background: var(--app-surface-hover); }
.app-theme-toggle.is-sidebar { position: relative; right: auto; bottom: auto; z-index: 1; margin: auto 8px 12px; }
.app-theme-toggle.is-sidebar .app-theme-toggle__trigger { width: 100%; min-height: 44px; justify-content: flex-start; gap: 10px; padding: 0 12px; border-radius: 10px; box-shadow: inset 0 0 0 1px var(--app-border); backdrop-filter: none; }
.app-theme-toggle__chevron { flex: 0 0 auto; }
.app-theme-toggle__label { display: flex; min-width: 0; flex: 1; align-items: center; justify-content: space-between; gap: 8px; font-size: 13px; }
.app-theme-toggle__label small { overflow: hidden; color: var(--app-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.app-theme-toggle.is-inline { position: relative; inset: auto; z-index: 1; }
.app-theme-toggle.is-inline .app-theme-toggle__trigger { min-width: 34px; min-height: 34px; box-shadow: none; border-radius: 9px; }
@media (max-width: 720px) {
  .app-theme-toggle.is-floating { right: 12px; bottom: 12px; }
  .app-theme-toggle.is-sidebar { margin-right: 8px; margin-left: 8px; }
  .app-theme-toggle.is-sidebar .app-theme-toggle__trigger { justify-content: center; padding: 0; }
  .app-theme-toggle.is-sidebar .app-theme-toggle__label, .app-theme-toggle.is-sidebar .app-theme-toggle__chevron { display: none; }
}
</style>
