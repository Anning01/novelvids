<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronRight, Languages, LoaderCircle } from 'lucide-vue-next'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { applySavedLocale, beginLocaleChange, locale, localeSaving as saving, tr, type AppLocale } from '@/i18n'
import { notice } from '@/shared/notice'
import AppButton from './AppButton.vue'
import AppThemeToggle from './AppThemeToggle.vue'
import PreferenceMenu from './PreferenceMenu.vue'

withDefaults(defineProps<{ showTheme?: boolean }>(), { showTheme: true })
const auth = useAuthStore()
const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const selected = ref<AppLocale>(locale.value)
const saved = ref<AppLocale>(locale.value)
let loadRevision = 0
const activeLabel = computed(() => locale.value === 'zh' ? tr('中文') : 'English')
const options: Array<{ value: AppLocale; label: string }> = [
  { value: 'zh', label: '简体中文' },
  { value: 'en', label: 'English' },
]

async function load() {
  const revision = ++loadRevision
  loading.value = true
  loaded.value = false
  error.value = ''
  try {
    const response = await api.generalConfig()
    if (revision !== loadRevision) return
    saved.value = selected.value = response.data.prompt_language
    applySavedLocale(response.data.prompt_language)
    loaded.value = true
  } catch (cause) {
    if (revision === loadRevision) error.value = cause instanceof Error ? cause.message : tr('加载失败，请重试')
  } finally {
    if (revision === loadRevision) loading.value = false
  }
}

function cancelLoad() {
  loading.value = false
  ++loadRevision
}
async function openLanguage() {
  selected.value = saved.value = locale.value
  error.value = ''
  if (auth.canAccessSettings) await load()
}

async function selectLanguage(nextValue: string) {
  const value = nextValue as AppLocale
  if (!auth.canAccessSettings || !loaded.value || saving.value) return
  if (value === saved.value) return
  const previous = saved.value
  selected.value = value
  error.value = ''
  beginLocaleChange(value)
  try {
    const response = await api.updateGeneralConfig({ prompt_language: value })
    saved.value = selected.value = response.data.prompt_language
    applySavedLocale(response.data.prompt_language)
  } catch (cause) {
    selected.value = saved.value = previous
    applySavedLocale(previous)
    notice.error(cause instanceof Error ? cause.message : tr('语言切换失败，请重试'))
  }
}

</script>

<template>
  <div class="app-sidebar-preferences">
    <PreferenceMenu class="sidebar-language" :model-value="selected" :options="options" :label="tr('语言')"
      :loading="loading" :disabled="!auth.canAccessSettings || !loaded" :busy="saving"
      @open="openLanguage" @close="cancelLoad" @update:model-value="selectLanguage">
      <template #trigger="{ toggle, open }">
        <button type="button" class="sidebar-language__trigger" :class="{ 'is-open': open }"
          :aria-label="`${tr('语言')}：${activeLabel}`" aria-haspopup="menu" :aria-expanded="open" :aria-busy="saving" :aria-disabled="saving" @click="toggle">
          <Languages :size="18" aria-hidden="true" />
          <span class="sidebar-language__label">{{ tr('语言') }}</span>
          <span class="sidebar-language__value">{{ activeLabel }}</span>
          <LoaderCircle v-if="saving" class="sidebar-language__spinner" :size="14" aria-hidden="true" />
          <ChevronRight v-else class="sidebar-language__chevron" :size="14" aria-hidden="true" />
        </button>
      </template>
      <p v-if="!auth.canAccessSettings" class="sidebar-language__note">{{ tr('由管理员设置') }}</p>
      <p v-if="error" class="sidebar-language__error" role="alert">{{ error }}</p>
      <AppButton v-if="auth.canAccessSettings && !loading && !loaded" block variant="secondary" @click="load">{{ tr('重试') }}</AppButton>
    </PreferenceMenu>
    <AppThemeToggle v-if="showTheme" placement="sidebar" />
  </div>
</template>

<style scoped>
.app-sidebar-preferences { flex: 0 0 auto; margin: 0 10px 12px; border: 1px solid var(--app-border); border-radius: 10px; background: var(--app-surface); }
.sidebar-language { position: relative; }
.sidebar-language__trigger { display: flex; width: 100%; min-height: 44px; align-items: center; gap: 9px; padding: 0 11px; border: 0; border-radius: 9px; color: var(--app-text-secondary); background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.sidebar-language__trigger:hover { background: var(--app-surface-hover); }
.sidebar-language__trigger.is-open { color: var(--app-accent); background: var(--app-accent-soft); }
.sidebar-language__trigger:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -3px; }
.sidebar-language__label { color: var(--app-text); }
.sidebar-language__value { margin-left: auto; font-size: 11px; }
.sidebar-language__trigger.is-open .sidebar-language__chevron { transform: rotate(-90deg); }
.sidebar-language__spinner { flex: 0 0 auto; animation: language-spin 1s linear infinite; }
@keyframes language-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .sidebar-language__spinner { animation: none; } }
.sidebar-language__error { color: var(--creation-danger); overflow-wrap: anywhere; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar) { margin: 0; padding-top: 1px; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar)::before { position: absolute; top: 0; right: 10px; left: 10px; height: 1px; background: var(--app-border); content: ''; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar .app-theme-toggle__trigger) { gap: 9px; padding: 0 11px; border-radius: 9px; background: transparent; box-shadow: none; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar .app-theme-toggle__trigger:hover) { background: var(--app-surface-hover); }
.app-sidebar-preferences :deep(.app-theme-toggle__label small) { font-size: 11px; }
@media (max-width: 720px) {
  .app-sidebar-preferences { margin-right: 8px; margin-left: 8px; }
  .sidebar-language__trigger { justify-content: center; padding: 0; }
  .sidebar-language__label, .sidebar-language__value, .sidebar-language__chevron { display: none; }
  .app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar .app-theme-toggle__trigger) { padding: 0; }
}
</style>
