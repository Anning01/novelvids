<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronRight, Languages } from 'lucide-vue-next'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { applySavedLocale, locale, tr, type AppLocale } from '@/i18n'
import { notice } from '@/shared/notice'
import AppButton from './AppButton.vue'
import AppThemeToggle from './AppThemeToggle.vue'

withDefaults(defineProps<{ showTheme?: boolean }>(), { showTheme: true })
const auth = useAuthStore()
const languageRoot = ref<HTMLElement>()
const trigger = ref<HTMLButtonElement>()
const panel = ref<HTMLElement>()
const open = ref(false)
const loading = ref(false)
const saving = ref(false)
const loaded = ref(false)
const error = ref('')
const selected = ref<AppLocale>(locale.value)
const saved = ref<AppLocale>(locale.value)
let loadRevision = 0
const activeLabel = computed(() => locale.value === 'zh' ? tr('中文') : 'English')
const options: Array<{ value: AppLocale; label: string; description: string }> = [
  { value: 'zh', label: '简体中文', description: '中文' },
  { value: 'en', label: 'English', description: '英语' },
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

function close(restoreFocus = false) {
  open.value = false
  loading.value = false
  ++loadRevision
  if (restoreFocus) trigger.value?.focus()
}

async function toggle() {
  if (open.value) { close(); return }
  selected.value = saved.value = locale.value
  error.value = ''
  open.value = true
  await nextTick()
  panel.value?.focus()
  if (auth.canAccessSettings) await load()
}

async function save() {
  if (!auth.canAccessSettings || !loaded.value || saving.value || selected.value === saved.value) return
  saving.value = true
  error.value = ''
  try {
    const response = await api.updateGeneralConfig({ prompt_language: selected.value })
    saved.value = selected.value = response.data.prompt_language
    applySavedLocale(response.data.prompt_language)
    notice.success(tr('通用配置已保存，新提交的生成任务将使用该语言'))
    close(open.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tr('保存失败，请重试')
  } finally {
    saving.value = false
  }
}

function outside(event: PointerEvent) {
  if (event.target instanceof Node && !languageRoot.value?.contains(event.target)) close()
}
function focusOutside(event: FocusEvent) {
  if (event.target instanceof Node && !languageRoot.value?.contains(event.target)) close()
}
function escape(event: KeyboardEvent) {
  if (!open.value) return
  event.stopPropagation()
  event.preventDefault()
  close(true)
}
function moveSelection(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  if (!auth.canAccessSettings || loading.value || saving.value || !loaded.value) return
  event.preventDefault()
  selected.value = event.key === 'Home' ? 'zh' : event.key === 'End' ? 'en' : selected.value === 'zh' ? 'en' : 'zh'
  void nextTick(() => panel.value?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus())
}
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', focusOutside)
})
onBeforeUnmount(() => {
  ++loadRevision
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', focusOutside)
})
</script>

<template>
  <div class="app-sidebar-preferences">
    <div ref="languageRoot" class="sidebar-language" @keydown.esc="escape">
      <button ref="trigger" type="button" class="sidebar-language__trigger" :class="{ 'is-open': open }"
        :aria-label="`${tr('语言')}：${activeLabel}`" aria-haspopup="dialog" :aria-expanded="open" @click="toggle">
        <Languages :size="18" aria-hidden="true" />
        <span class="sidebar-language__label">{{ tr('语言') }}</span>
        <span class="sidebar-language__value">{{ activeLabel }}</span>
        <ChevronRight class="sidebar-language__chevron" :size="14" aria-hidden="true" />
      </button>
      <section v-if="open" ref="panel" class="sidebar-language__panel" role="dialog" :aria-label="tr('语言')" tabindex="-1" :aria-busy="loading || saving">
        <header><strong>{{ tr('语言') }}</strong><p>{{ tr('界面与后续生成内容') }}</p></header>
        <p v-if="loading" role="status">{{ tr('加载中…') }}</p>
        <div v-else class="sidebar-language__options" role="radiogroup" :aria-label="tr('语言')" @keydown="moveSelection">
          <button v-for="option in options" :key="option.value" type="button" role="radio"
            :aria-checked="selected === option.value" :tabindex="selected === option.value ? 0 : -1"
            :disabled="!auth.canAccessSettings || !loaded || saving" @click="selected = option.value">
            <span><strong>{{ option.value === 'zh' ? tr(option.label) : option.label }}</strong><small>{{ tr(option.description) }}</small></span>
            <Check v-if="selected === option.value" :size="16" aria-hidden="true" />
          </button>
        </div>
        <p class="sidebar-language__note">{{ tr('由管理员统一设置，影响全站界面和后续生成内容。') }}</p>
        <p v-if="error" class="sidebar-language__error" role="alert">{{ error }}</p>
        <AppButton v-if="auth.canAccessSettings && !loading && !loaded" block variant="secondary" @click="load">{{ tr('重试') }}</AppButton>
        <AppButton v-else-if="auth.canAccessSettings" block variant="primary" :loading="saving" :disabled="loading || !loaded || selected === saved" @click="save">
          {{ saving ? tr('保存中…') : tr('保存') }}
        </AppButton>
      </section>
    </div>
    <AppThemeToggle v-if="showTheme" placement="sidebar" />
  </div>
</template>

<style scoped>
.app-sidebar-preferences { flex: 0 0 auto; margin: 0 10px 12px; border: 1px solid var(--app-border); border-radius: 10px; background: var(--app-surface); }
.sidebar-language { position: relative; }
.sidebar-language__trigger { display: flex; width: 100%; min-height: 44px; align-items: center; gap: 9px; padding: 0 11px; border: 0; border-radius: 9px; color: var(--app-text-secondary); background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.sidebar-language__trigger:hover { background: var(--app-surface-hover); }
.sidebar-language__trigger.is-open { color: var(--app-accent); background: var(--app-accent-soft); }
.sidebar-language__trigger:focus-visible, .sidebar-language__options button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -3px; }
.sidebar-language__label { color: var(--app-text); }
.sidebar-language__value { margin-left: auto; font-size: 11px; }
.sidebar-language__trigger.is-open .sidebar-language__chevron { transform: rotate(-90deg); }
.sidebar-language__panel { position: absolute; z-index: 5; bottom: calc(100% + 8px); left: -1px; width: 256px; max-width: calc(100vw - 92px); max-height: calc(100dvh - 120px); overflow-y: auto; box-sizing: border-box; padding: 12px; border: 1px solid var(--app-border); border-radius: 12px; outline: none; color: var(--app-text); background: var(--app-surface); box-shadow: var(--app-shadow); }
.sidebar-language__panel header strong { font-size: 14px; }
.sidebar-language__panel p { margin: 6px 0 12px; font-size: 12px; line-height: 1.6; color: var(--app-text-secondary); }
.sidebar-language__options { display: grid; gap: 4px; }
.sidebar-language__options button { display: flex; width: 100%; min-height: 52px; align-items: center; justify-content: space-between; padding: 8px 10px; border: 0; border-radius: 8px; color: var(--app-text); background: transparent; text-align: left; cursor: pointer; }
.sidebar-language__options button:hover:not(:disabled) { background: var(--app-surface-hover); }
.sidebar-language__options button[aria-checked='true'] { color: var(--app-accent); background: var(--app-accent-soft); }
.sidebar-language__options button:disabled { cursor: default; }
.sidebar-language__options button:disabled:not([aria-checked='true']) { opacity: .55; }
.sidebar-language__options button span { display: grid; gap: 4px; }
.sidebar-language__options strong { font-size: 13px; font-weight: 600; }
.sidebar-language__options small { color: var(--app-text-secondary); font-size: 12px; }
.sidebar-language__panel .sidebar-language__note { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--app-border); }
.sidebar-language__panel .sidebar-language__error { color: var(--creation-danger); overflow-wrap: anywhere; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar) { margin: 0; padding-top: 1px; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar)::before { position: absolute; top: 0; right: 10px; left: 10px; height: 1px; background: var(--app-border); content: ''; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar .app-theme-toggle__trigger) { gap: 9px; padding: 0 11px; border-radius: 9px; background: transparent; box-shadow: none; }
.app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar .app-theme-toggle__trigger:hover) { background: var(--app-surface-hover); }
.app-sidebar-preferences :deep(.app-theme-toggle__label small) { font-size: 11px; }
@media (max-width: 720px) {
  .app-sidebar-preferences { margin-right: 8px; margin-left: 8px; }
  .sidebar-language__trigger { justify-content: center; padding: 0; }
  .sidebar-language__label, .sidebar-language__value, .sidebar-language__chevron { display: none; }
  .sidebar-language__panel { position: fixed; left: 76px; bottom: 12px; }
  .app-sidebar-preferences :deep(.app-theme-toggle.is-sidebar .app-theme-toggle__trigger) { padding: 0; }
}
</style>
