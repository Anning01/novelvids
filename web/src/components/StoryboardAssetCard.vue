<script setup lang="ts">
import type { Component } from 'vue'
import { Volume2 } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { fallbackImage } from '@/shared/mediaFallback'
import AppButton from './AppButton.vue'
import SceneAssetActionMenu from './SceneAssetActionMenu.vue'

defineProps<{
  assetId: number
  label: string
  icon: Component
  thumbnail: string
  original: string
  highlighted: boolean
  anchorId: string
  replacing: boolean
  menuOpen: boolean
  voiceLabel?: string
  voiceOpen?: boolean
  savingVoice?: boolean
  voiceDisabled?: boolean
}>()
const emit = defineEmits<{
  preview: []
  replace: []
  voice: []
  menu: []
  edit: []
  remove: []
}>()
</script>

<template>
  <article class="selected-asset-row">
    <button type="button" class="asset-thumb" :class="{ 'is-reference-highlighted': highlighted }"
      :data-reference-asset-id="assetId" :disabled="!original && !thumbnail"
      :aria-label="tr('放大查看 {p0}', { p0: label })" aria-haspopup="dialog" @click="emit('preview')">
      <component :is="icon" :size="16" aria-hidden="true" />
      <img v-if="thumbnail || original" :src="thumbnail || original" alt="" loading="lazy" decoding="async" @error="fallbackImage($event, original)" />
    </button>
    <AppButton :id="anchorId" class="asset-name-button" variant="soft" size="sm" :active="replacing"
      aria-haspopup="dialog" :aria-expanded="replacing" :aria-label="tr('替换{p0}', { p0: label })"
      :title="tr('替换{p0}', { p0: label })" @click="emit('replace')"><span>{{ label }}</span></AppButton>
    <SceneAssetActionMenu :open="menuOpen" :label="label" @toggle="emit('menu')" @edit="emit('edit')" @remove="emit('remove')" />
    <AppButton v-if="voiceLabel !== undefined" variant="soft" size="sm" class="asset-voice-button" :active="voiceOpen"
      :loading="savingVoice" :disabled="voiceDisabled" :aria-label="tr('为{p0}更换音色', { p0: label })"
      :title="tr('更换{p0}的音色', { p0: label })" @click="emit('voice')"><Volume2 :size="13" /><span>{{ voiceLabel }}</span></AppButton>
  </article>
</template>

<style scoped>
.selected-asset-row { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 24px; align-content: start; align-items: start; gap: 2px 0; min-width: 0; }
.asset-thumb { position: relative; display: grid; grid-column: 1 / -1; width: 100%; aspect-ratio: 8 / 5; padding: 0; overflow: hidden; place-items: center; border: 0; border-radius: 7px; color: var(--app-text-muted); background: var(--app-surface-muted); cursor: zoom-in; }
.asset-thumb:disabled { cursor: default; }
.asset-thumb:focus-visible,.asset-thumb.is-reference-highlighted { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.asset-thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.selected-asset-row :is(.asset-name-button,.asset-voice-button) { justify-content: center; min-width: 0; min-height: 24px; height: auto; padding: 2px 3px; background: transparent; box-shadow: none; }
.asset-name-button { color: var(--app-text); font-size: 12px; }
.asset-name-button span { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; white-space: normal; overflow-wrap: anywhere; line-height: 1.4; }
.asset-voice-button { grid-column: 1 / -1; gap: 3px; color: var(--app-text-secondary); font-size: 10px; }
.asset-voice-button svg { flex: none; }
.asset-voice-button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-asset-row :is(.asset-name-button,.asset-voice-button):is(:hover:not(:disabled),.is-active) { color: var(--app-accent); background: var(--app-accent-soft); }
.scene-asset-actions { width: 24px; height: 24px; }
.selected-asset-row :deep(.scene-asset-actions__trigger) { width: 24px !important; min-width: 24px !important; min-height: 24px !important; height: 24px; }
.selected-asset-row:has(.scene-asset-actions__menu) { z-index: 1; }
</style>
