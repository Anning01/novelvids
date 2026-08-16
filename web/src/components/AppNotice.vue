<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-vue-next'
import { notice, type Notice } from '@/shared/notice'

const props = defineProps<{ item: Notice }>()

const icon = computed(() => ({
  info: Info,
  success: CheckCircle2,
  error: CircleAlert,
}[props.item.tone]))

function dismiss() {
  notice.dismiss(props.item.id)
}
</script>

<template>
  <div class="app-notice" :class="`is-${item.tone}`" role="status">
    <component :is="icon" class="app-notice__icon" :size="16" aria-hidden="true" />
    <p class="app-notice__message">{{ item.message }}</p>
    <button type="button" class="app-notice__close" aria-label="关闭通知" @click="dismiss"><X :size="14" /></button>
  </div>
</template>

<style scoped>
.app-notice {
  position: relative;
  display: flex;
  min-width: 260px;
  max-width: 380px;
  align-items: flex-start;
  gap: 10px;
  overflow: hidden;
  padding: 12px 12px 12px 16px;
  border-radius: 12px;
  color: var(--app-text, #303442);
  background: var(--app-surface-raised, #fff);
  box-shadow: 0 2px 6px rgb(20 22 28 / 6%), 0 16px 44px rgb(20 22 28 / 14%);
  font-size: 12px;
  line-height: 1.5;
}
.app-notice::before {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 3px;
  background: currentColor;
  content: '';
}
.app-notice__icon { flex: 0 0 auto; margin-top: 1px; }
.app-notice__message { flex: 1; min-width: 0; margin: 0; overflow-wrap: anywhere; }
.app-notice__close {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: 6px;
  color: var(--app-text-muted, #9398a8);
  background: transparent;
  cursor: pointer;
  transition: color .14s ease, background-color .14s ease;
}
.app-notice__close:hover { color: var(--app-text, #303442); background: var(--app-surface-hover, #f2f3f7); }

.app-notice.is-info { color: #5b5cf6; }
.app-notice.is-success { color: #22a06b; }
.app-notice.is-error { color: #e5484d; }
.app-notice .app-notice__message { color: var(--app-text, #303442); }
</style>
