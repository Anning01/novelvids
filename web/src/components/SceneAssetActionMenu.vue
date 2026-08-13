<script setup lang="ts">
import { Ellipsis, Pencil, Trash2 } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'

defineProps<{
  open: boolean
  label: string
}>()

const emit = defineEmits<{
  toggle: []
  edit: []
  remove: []
}>()
</script>

<template>
  <div class="scene-asset-actions">
    <AppButton
      class="scene-asset-actions__trigger"
      type="button"
      variant="ghost"
      size="sm"
      icon-only
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="`${label}更多操作`"
      @click.stop="emit('toggle')"
    >
      <Ellipsis :size="16" />
    </AppButton>

    <Transition name="scene-asset-actions-menu">
      <div v-if="open" class="scene-asset-actions__menu" role="menu" :aria-label="`${label}操作`" @click.stop>
        <button type="button" role="menuitem" @click="emit('edit')"><Pencil :size="14" /><span>编辑</span></button>
        <button type="button" class="is-danger" role="menuitem" @click="emit('remove')"><Trash2 :size="14" /><span>删除</span></button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.scene-asset-actions { position: relative; display: grid; width: 30px; height: 30px; place-items: center; }
.scene-asset-actions__trigger { display: grid !important; width: 30px !important; min-width: 30px !important; min-height: 30px !important; place-items: center; justify-content: center !important; padding: 0 !important; }
.scene-asset-actions__trigger :deep(svg) { display: block; margin: 0; }
.scene-asset-actions__menu { position: absolute; top: calc(100% + 5px); right: 0; z-index: 45; display: grid; width: 112px; overflow: hidden; padding: 5px; border-radius: 10px; color: var(--app-text-secondary); background: var(--app-surface-raised); box-shadow: 0 14px 34px rgb(34 38 56 / 16%), inset 0 0 0 1px var(--app-border); }
.scene-asset-actions__menu button { display: flex; min-height: 34px; align-items: center; gap: 8px; padding: 0 10px; border: 0; border-radius: 7px; color: inherit; background: transparent; font: inherit; font-size: 11px; text-align: left; cursor: pointer; transition: color 140ms ease,background 140ms ease; }
.scene-asset-actions__menu button:hover,.scene-asset-actions__menu button:focus-visible { color: var(--app-text); background: var(--app-surface-hover); outline: 0; }
.scene-asset-actions__menu button.is-danger { color: #cf4d60; }
.scene-asset-actions__menu button.is-danger:hover,.scene-asset-actions__menu button.is-danger:focus-visible { color: #b73549; background: #fff1f3; }
.scene-asset-actions-menu-enter-active,.scene-asset-actions-menu-leave-active { transition: opacity 130ms ease,transform 160ms cubic-bezier(.2,.75,.2,1); transform-origin: top right; }
.scene-asset-actions-menu-enter-from,.scene-asset-actions-menu-leave-to { opacity: 0; transform: translateY(-3px) scale(.97); }
@media (prefers-reduced-motion: reduce) { .scene-asset-actions-menu-enter-active,.scene-asset-actions-menu-leave-active { transition-duration: 1ms; } }
</style>
