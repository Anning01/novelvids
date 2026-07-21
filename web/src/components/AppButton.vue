<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next'

export type AppButtonVariant = 'primary' | 'secondary' | 'soft' | 'ghost' | 'danger' | 'dark'
export type AppButtonSize = 'xs' | 'sm' | 'md' | 'lg'

withDefaults(defineProps<{
  type?: 'button' | 'submit' | 'reset'
  variant?: AppButtonVariant
  size?: AppButtonSize
  disabled?: boolean
  loading?: boolean
  iconOnly?: boolean
  block?: boolean
  active?: boolean
}>(), {
  type: 'button',
  variant: 'ghost',
  size: 'md',
  disabled: false,
  loading: false,
  iconOnly: false,
  block: false,
  active: false,
})
</script>

<template>
  <button
    :type="type"
    class="app-button"
    :class="[
      `app-button--${variant}`,
      `app-button--${size}`,
      { 'is-icon-only': iconOnly, 'is-block': block, 'is-active': active, 'is-loading': loading },
    ]"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <LoaderCircle v-if="loading" class="app-button__spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.app-button {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin: 0;
  border: 0;
  border-radius: 11px;
  outline: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  font-weight: 620;
  line-height: 1;
  white-space: nowrap;
  appearance: none;
  cursor: pointer;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
  transition: color .16s ease, background-color .16s ease, box-shadow .16s ease, transform .16s ease, opacity .16s ease;
}
.app-button--xs { min-height: 28px; padding: 0 9px; border-radius: 8px; font-size: 10px; }
.app-button--sm { min-height: 34px; padding: 0 12px; border-radius: 9px; font-size: 11px; }
.app-button--md { min-height: 38px; padding: 0 14px; font-size: 12px; }
.app-button--lg { min-height: 44px; padding: 0 18px; border-radius: 12px; font-size: 13px; }
.app-button--primary { color: #fff; background: linear-gradient(135deg, #6869f7, #5556ed); box-shadow: 0 9px 22px rgb(83 84 230 / 20%); }
.app-button--primary:hover:not(:disabled) { background: linear-gradient(135deg, #5d5ff2, #494be5); box-shadow: 0 12px 28px rgb(83 84 230 / 26%); transform: translateY(-1px); }
.app-button--secondary { color: #4c5262; background: #fff; box-shadow: 0 1px 2px rgb(35 39 55 / 7%), 0 7px 20px rgb(35 39 55 / 5%); }
.app-button--secondary:hover:not(:disabled) { color: #323746; background: #fafaff; box-shadow: 0 2px 4px rgb(35 39 55 / 8%), 0 10px 24px rgb(35 39 55 / 7%); transform: translateY(-1px); }
.app-button--soft { color: #5b5cf0; background: #efefff; box-shadow: inset 0 0 0 1px rgb(91 92 240 / 5%); }
.app-button--soft:hover:not(:disabled), .app-button--soft.is-active { color: #4d4ee5; background: #e8e8ff; }
.app-button--ghost { color: inherit; background: transparent; }
.app-button--ghost:hover:not(:disabled), .app-button--ghost.is-active { color: #5658ec; background: #f0f0ff; }
.app-button--danger { color: #c45461; background: #fff1f2; }
.app-button--danger:hover:not(:disabled) { color: #a83f4c; background: #ffe7e9; }
.app-button--dark { color: #fff; background: #292c36; box-shadow: 0 9px 24px rgb(31 34 44 / 20%); }
.app-button--dark:hover:not(:disabled) { background: #1f222b; transform: translateY(-1px); }
.app-button.is-icon-only { width: 38px; padding: 0; flex: 0 0 auto; }
.app-button--xs.is-icon-only { width: 28px; }
.app-button--sm.is-icon-only { width: 34px; }
.app-button--lg.is-icon-only { width: 44px; }
.app-button.is-block { width: 100%; }
.app-button:focus-visible { outline: 3px solid rgb(91 92 246 / 20%); outline-offset: 2px; }
.app-button:active:not(:disabled) { transform: translateY(0) scale(.985); }
.app-button:disabled { opacity: .45; cursor: not-allowed; transform: none; box-shadow: none; }
.app-button__spinner { width: 1em; height: 1em; animation: app-button-spin .8s linear infinite; }
@keyframes app-button-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .app-button { transition: none; } .app-button__spinner { animation-duration: 1.6s; } }
</style>
