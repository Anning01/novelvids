<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { api, mediaUrl } from '@/api'
import { tr } from '@/i18n'
import type { Scene } from '@/types'
import type { SheetHistory, SheetHistoryItem } from '@/shared/storyboardSheetHistory'
import type { PreviewImage } from '@/shared/imageGallery'
import ImageLightbox from './ImageLightbox.vue'
import AppButton from './AppButton.vue'

const props = defineProps<{open: boolean; scene: Scene}>()
const emit = defineEmits<{close: []; updated: [scene: Scene]}>()
const dialog = ref<HTMLDialogElement | null>(null)
const data = ref<SheetHistory | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const preview = ref('')
const comparison = ref<PreviewImage[]>([])
let revision = 0
async function load() {
  const request = ++revision
  loading.value = true
  error.value = ''
  try {
    const response = await api.storyboardSheetHistory(props.scene.id)
    if (request === revision) data.value = response.data
  } catch (caught) { if (request === revision) error.value = (caught as Error).message }
  finally { if (request === revision) loading.value = false }
}
function compare(item: SheetHistoryItem) {
  comparison.value = [
    ...(data.value?.current_image_url ? [{src: mediaUrl(data.value.current_image_url), alt: tr('当前线稿')}] : []),
    ...(!item.is_current ? [{src: mediaUrl(item.image_url), alt: tr('所选历史线稿')}] : []),
  ]
  preview.value = mediaUrl(item.image_url)
}
async function restore(item: SheetHistoryItem) {
  if (!data.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    const updated = (await api.restoreStoryboardSheet(props.scene.id, {
      task_id: item.task_id, source: item.source, expected_revision: data.value.revision,
    })).data
    emit('updated', updated)
    await load()
  } catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}
watch(() => props.open, async open => {
  await nextTick()
  if (!dialog.value) return
  if (open) { dialog.value.showModal(); void load() }
  else { ++revision; dialog.value.close(); preview.value = '' }
}, {immediate:true})
onBeforeUnmount(() => { ++revision; dialog.value?.close() })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="sheet-history" :aria-label="tr('线稿历史与对比')" @keydown.stop @close="emit('close')">
      <header><h2>{{ tr('分镜 {p0} · 线稿历史', {p0: scene.sequence}) }}</h2><AppButton autofocus size="sm" variant="ghost" :aria-label="tr('关闭线稿历史')" @click="dialog?.close()">{{ tr('关闭') }}</AppButton></header>
      <p v-if="loading" role="status">{{ tr('正在读取线稿历史…') }}</p>
      <p v-if="error" role="alert">{{ error }} <AppButton size="sm" :disabled="loading || saving" @click="load">{{ tr('重新加载') }}</AppButton></p>
      <p v-if="!loading && !error && !data?.items.length">{{ tr('暂无线稿历史') }}</p>
      <ol v-if="data?.items.length" role="list">
        <li v-for="item in data.items" :key="`${item.task_id}:${item.source}`">
          <button type="button" class="sheet-history__preview" :aria-label="item.is_current ? tr('查看当前线稿') : tr('与当前线稿对比')" @click="compare(item)"><img :src="mediaUrl(item.image_url)" :alt="item.is_current ? tr('当前线稿') : tr('历史线稿')" loading="lazy" /></button>
          <div><strong>{{ item.is_current ? tr('当前线稿') : item.source ? tr('修改前线稿') : tr('历史线稿') }}</strong><time :datetime="item.created_at">{{ new Date(item.created_at).toLocaleString() }}</time><p>{{ item.instruction }}</p><small v-if="!item.saved && !item.is_current">{{ tr('已生成，尚未设为当前线稿') }}</small></div>
          <AppButton size="sm" variant="secondary" :disabled="item.is_current || saving || loading" @click="restore(item)">{{ item.is_current ? tr('当前使用') : tr('恢复这版') }}</AppButton>
        </li>
      </ol>
      <ImageLightbox :open="Boolean(preview)" :src="preview" :alt="tr('线稿对比')" :images="comparison" @close="preview = ''" />
    </dialog>
  </Teleport>
</template>

<style scoped>
.sheet-history { width: min(820px,calc(100vw - 32px)); max-height: calc(100dvh - 40px); padding: 20px; border: 1px solid var(--app-border); border-radius: 14px; color: var(--app-text); background: var(--app-surface); }
.sheet-history:modal { overscroll-behavior: contain; }
.sheet-history::backdrop { background: rgb(0 0 0 / 55%); overflow: hidden; overscroll-behavior: contain; }
.sheet-history header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.sheet-history h2 { margin: 0; font-size: 18px; }.sheet-history ol { display: grid; gap: 12px; padding: 0; list-style: none; }
.sheet-history li { display: grid; grid-template-columns: 150px minmax(0,1fr) auto; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--app-border); }
.sheet-history time { display: block; margin-top: 4px; color: var(--app-text-muted); font-size: 12px; }.sheet-history p { overflow-wrap: anywhere; }.sheet-history small { color: var(--app-text-muted); }
.sheet-history__preview { padding: 0; border: 0; background: var(--app-surface-muted); cursor: zoom-in; }.sheet-history__preview img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; }
.sheet-history__preview:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }.sheet-history [role=alert] { color: var(--creation-danger); }
@media (max-width:600px) { .sheet-history li { grid-template-columns: 100px minmax(0,1fr); }.sheet-history li > :last-child { grid-column:2; justify-self:start; } }
</style>
