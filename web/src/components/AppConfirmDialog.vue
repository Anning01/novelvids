<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { CircleHelp, TriangleAlert, Trash2 } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { appConfirmState, resolveAppConfirm } from '@/shared/confirmDialog'

const props = withDefaults(defineProps<{ dark?: boolean }>(), { dark: false })
const dialog = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null

const dialogIcon = computed(() => ({
  danger: Trash2,
  warning: TriangleAlert,
  neutral: CircleHelp,
}[appConfirmState.tone]))

function close(confirmed: boolean) {
  resolveAppConfirm(confirmed)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close(false)
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled),[href],[tabindex]:not([tabindex="-1"])')]
  if (!controls.length) return
  const first = controls[0]
  const last = controls.at(-1)!
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => appConfirmState.open, async open => {
  if (open) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    dialog.value?.querySelector<HTMLButtonElement>('button')?.focus()
  } else {
    previousFocus?.focus()
    previousFocus = null
  }
})

onBeforeUnmount(() => resolveAppConfirm(false))
</script>

<template>
  <Teleport to="body">
    <Transition name="app-confirm">
      <div
        v-if="appConfirmState.open"
        class="app-confirm-backdrop"
        :class="{ 'is-dark': props.dark }"
        @click.self="close(false)"
        @keydown="onKeydown"
      >
        <section
          ref="dialog"
          class="app-confirm-dialog"
          :class="`is-${appConfirmState.tone}`"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="app-confirm-title"
          :aria-describedby="appConfirmState.message ? 'app-confirm-message' : undefined"
        >
          <span class="app-confirm-icon"><component :is="dialogIcon" :size="21" /></span>
          <div class="app-confirm-copy">
            <h2 id="app-confirm-title">{{ appConfirmState.title }}</h2>
            <p v-if="appConfirmState.message" id="app-confirm-message">{{ appConfirmState.message }}</p>
          </div>
          <footer class="app-confirm-actions">
            <AppButton variant="secondary" @click="close(false)">{{ appConfirmState.cancelLabel }}</AppButton>
            <AppButton :variant="appConfirmState.tone === 'danger' ? 'danger' : 'primary'" @click="close(true)">{{ appConfirmState.confirmLabel }}</AppButton>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.app-confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(26 29 40 / 48%);
  backdrop-filter: blur(8px);
}
.app-confirm-dialog {
  display: grid;
  width: min(420px,100%);
  grid-template-columns: 48px minmax(0,1fr);
  gap: 14px;
  padding: 22px;
  border: 1px solid #e6e8ef;
  border-radius: 20px;
  color: #303442;
  background: #fff;
  box-shadow: 0 30px 90px rgb(25 28 45 / 28%);
}
.app-confirm-icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: 15px;
  color: #6264ef;
  background: #efefff;
}
.app-confirm-dialog.is-danger .app-confirm-icon { color: #c45461; background: #fff0f2; }
.app-confirm-dialog.is-warning .app-confirm-icon { color: #b7733d; background: #fff3e9; }
.app-confirm-copy { min-width: 0; align-self: center; }
.app-confirm-copy h2 { margin: 0; color: #292d3a; font-size: 17px; line-height: 1.3; }
.app-confirm-copy p { margin: 7px 0 0; color: #777e8f; font-size: 12px; line-height: 1.65; }
.app-confirm-actions { display: flex; grid-column: 1/-1; justify-content: flex-end; gap: 9px; margin-top: 7px; }
.app-confirm-actions :deep(.app-button--danger) {
  color: #fff;
  background: linear-gradient(135deg,#d26570,#bb4c59);
  box-shadow: 0 9px 22px rgb(187 76 89 / 20%);
}
.app-confirm-actions :deep(.app-button--danger:hover:not(:disabled)) {
  color: #fff;
  background: linear-gradient(135deg,#c65a66,#ab414e);
  box-shadow: 0 12px 28px rgb(187 76 89 / 26%);
}
.app-confirm-backdrop.is-dark { background: rgb(8 9 12 / 72%); }
.is-dark .app-confirm-dialog { border-color: #3d3732; color: #eee9e2; background: #211e1b; box-shadow: 0 34px 100px rgb(0 0 0 / 42%); }
.is-dark .app-confirm-copy h2 { color: #eee9e2; }
.is-dark .app-confirm-copy p { color: #9f958c; }
.is-dark .app-confirm-icon { color: #b8a7ff; background: rgb(169 149 255 / 13%); box-shadow: inset 0 0 0 1px rgb(184 167 255 / 14%); }
.is-dark .app-confirm-dialog.is-danger .app-confirm-icon { color: #e08a92; background: rgb(190 73 85 / 12%); box-shadow: inset 0 0 0 1px rgb(224 138 146 / 18%); }
.is-dark .app-confirm-dialog.is-warning .app-confirm-icon { color: #d2a272; background: rgb(185 119 63 / 12%); box-shadow: inset 0 0 0 1px rgb(210 162 114 / 18%); }
.is-dark .app-confirm-actions :deep(.app-button--secondary) { color: #c7bdb4; background: #292521; box-shadow: inset 0 0 0 1px #3d3732; }
.is-dark .app-confirm-actions :deep(.app-button--secondary:hover:not(:disabled)) { color: #eee9e2; background: #302b27; }
.app-confirm-enter-active,.app-confirm-leave-active { transition: opacity .16s ease; }
.app-confirm-enter-active .app-confirm-dialog,.app-confirm-leave-active .app-confirm-dialog { transition: opacity .16s ease,transform .16s ease; }
.app-confirm-enter-from,.app-confirm-leave-to { opacity: 0; }
.app-confirm-enter-from .app-confirm-dialog,.app-confirm-leave-to .app-confirm-dialog { opacity: 0; transform: translateY(8px) scale(.98); }
@media (max-width: 520px) {
  .app-confirm-backdrop { padding: 16px; }
  .app-confirm-dialog { padding: 19px; }
  .app-confirm-actions :deep(.app-button) { flex: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .app-confirm-enter-active,.app-confirm-leave-active,.app-confirm-enter-active .app-confirm-dialog,.app-confirm-leave-active .app-confirm-dialog { transition: none; }
}
</style>
