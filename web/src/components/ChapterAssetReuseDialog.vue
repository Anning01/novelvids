<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { BookOpenText, Check, ChevronDown, Search, X } from 'lucide-vue-next'
import { api } from '@/api'
import { tr } from '@/i18n'
import { assetTypeIconFor } from '@/features/workbench/components/assetTypePresentation'
import { stripChapterOrdinal } from '@/shared/chapterTitle'
import { fallbackImage } from '@/shared/mediaFallback'
import type { Asset, AssetTypeEnum, Chapter } from '@/types'
import AppButton from './AppButton.vue'

const props = defineProps<{ chapter: Chapter; chapters: Chapter[]; assetType: AssetTypeEnum; typeLabel: string }>()
const emit = defineEmits<{ close: []; added: [asset: Asset, chapter: Chapter] }>()
const id = useId()
const chapterLabel = computed(() => {
  const name = stripChapterOrdinal(props.chapter.name)
  return name
    ? tr('第 {p0} 章 · {p1}', { p0: props.chapter.number, p1: name })
    : tr('第 {p0} 章', { p0: props.chapter.number })
})
const panel = ref<HTMLDialogElement>()
const search = ref('')
const query = ref('')
const sourceChapters = ref<number[]>([])
const chapterSearch = ref('')
const filtersOpen = ref(false)
const chapterOptions = computed(() => {
  const keyword = chapterSearch.value.trim().toLowerCase()
  return props.chapters.map(chapter => ({
    number: chapter.number,
    ordinal: tr('第 {p0} 章', { p0: chapter.number }),
    title: stripChapterOrdinal(chapter.name),
  })).filter(chapter => !keyword || `${chapter.ordinal} ${chapter.title}`.toLowerCase().includes(keyword))
})
const items = ref<Asset[]>([])
const selectedId = ref<number>()
const selected = computed(() => items.value.find(asset => asset.id === selectedId.value))
const page = ref(0)
const pages = ref(0)
const total = ref(0)
const failedPage = ref(0)
const loading = ref(true)
const saving = ref(false)
const saveError = ref(false)
const icon = assetTypeIconFor(props.assetType)
let revision = 0

function isInChapter(asset: Asset) {
  return asset.source_chapters?.includes(props.chapter.number) ?? false
}

function chaptersLabel(asset: Asset) {
  const numbers = asset.source_chapters ?? []
  if (!numbers.length) return tr('尚未加入章节')
  return tr('出现于第 {p0} 章', { p0: numbers.join(tr('、')) })
}

async function loadPage(nextPage: number) {
  const request = ++revision
  loading.value = true
  failedPage.value = 0
  try {
    const { data } = await api.projectAssetLibrary(props.chapter.novel_id, nextPage, query.value, 24, props.assetType, sourceChapters.value)
    if (request !== revision) return
    items.value = nextPage === 1 ? data.items : [...items.value, ...data.items.filter(item => !items.value.some(current => current.id === item.id))]
    page.value = data.pagination.page
    pages.value = data.pagination.pages
    total.value = data.pagination.total
  } catch {
    if (request === revision) failedPage.value = nextPage
  } finally {
    if (request === revision) loading.value = false
  }
}

function submitSearch() {
  if (saving.value) return
  query.value = search.value.trim()
  resetResults()
}

function resetResults() {
  items.value = []
  page.value = 0
  pages.value = 0
  total.value = 0
  selectedId.value = undefined
  saveError.value = false
  void loadPage(1)
}

function clearChapterFilters() {
  sourceChapters.value = []
}

watch(sourceChapters, resetResults)

async function addToChapter() {
  const asset = selected.value
  const chapter = props.chapter
  if (!asset || isInChapter(asset) || saving.value) return
  saving.value = true
  saveError.value = false
  try {
    const { data } = await api.reuseAsset(asset.id, chapter.id)
    if (!panel.value?.open) return
    panel.value.close()
    emit('added', data, chapter)
  } catch {
    saveError.value = true
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  panel.value?.showModal()
  void loadPage(1)
})
onBeforeUnmount(() => {
  revision++
  panel.value?.close()
})
</script>

<template>
  <dialog
    ref="panel"
    class="chapter-reuse"
    :aria-labelledby="`${id}-title`"
    :aria-describedby="`${id}-chapter`"
    @cancel="saving && $event.preventDefault()"
    @close="emit('close')"
  >
    <header class="chapter-reuse__header">
      <div>
        <h2 :id="`${id}-title`" tabindex="-1" autofocus>{{ tr('加入已有{p0}', { p0: typeLabel }) }}</h2>
        <p :id="`${id}-chapter`"><BookOpenText :size="15" aria-hidden="true" />{{ tr('加入到 {p0}', { p0: chapterLabel }) }}</p>
      </div>
      <form method="dialog">
        <AppButton type="submit" size="md" icon-only :aria-label="tr('关闭')" :disabled="saving"><X :size="18" aria-hidden="true" /></AppButton>
      </form>
    </header>

    <div class="chapter-reuse__body">
      <aside class="chapter-reuse__filters">
        <AppButton class="chapter-reuse__filter-toggle" size="md" :aria-expanded="filtersOpen"
          :aria-controls="`${id}-filters`" @click="filtersOpen = !filtersOpen">
          {{ tr('来源章节') }}
          <small>{{ sourceChapters.length ? tr('已选 {p0} 章', { p0: sourceChapters.length }) : tr('全部章节') }}</small>
          <ChevronDown :size="16" aria-hidden="true" />
        </AppButton>
        <fieldset :id="`${id}-filters`" class="chapter-reuse__filter-panel" :class="{ 'is-open': filtersOpen }" :disabled="saving">
          <legend class="visually-hidden">{{ tr('来源章节') }}</legend>
          <div class="chapter-reuse__filter-heading">
            <strong>{{ tr('来源章节') }}</strong>
            <AppButton size="xs" :disabled="!sourceChapters.length" @click="clearChapterFilters">{{ tr('清除筛选') }}</AppButton>
          </div>
          <input v-if="chapters.length > 8" v-model="chapterSearch" class="chapter-reuse__chapter-search" type="search"
            :aria-label="tr('搜索章节')" :placeholder="tr('搜索章节')" />
          <div class="chapter-reuse__chapter-options">
            <label v-for="option in chapterOptions" :key="option.number" class="chapter-reuse__chapter-option">
              <input v-model="sourceChapters" type="checkbox" name="source-chapter" :value="option.number" />
              <span class="chapter-reuse__chapter-name">
                <strong>{{ option.ordinal }}</strong>
                <small v-if="option.title" :title="option.title">{{ option.title }}</small>
              </span>
            </label>
            <p v-if="!chapterOptions.length" class="chapter-reuse__no-chapters">{{ tr('未找到匹配的章节') }}</p>
          </div>
        </fieldset>
      </aside>

      <div class="chapter-reuse__results">
        <div class="chapter-reuse__toolbar">
          <form class="chapter-reuse__search" role="search" @submit.prevent="submitSearch">
            <Search :size="17" aria-hidden="true" />
            <input v-model="search" name="search" type="search"
              :aria-label="tr('搜索项目{p0}', { p0: typeLabel })" :placeholder="tr('搜索项目{p0}', { p0: typeLabel })" :disabled="saving" />
            <AppButton type="submit" size="sm" :disabled="saving">{{ tr('搜索') }}</AppButton>
          </form>
          <span v-if="total" class="chapter-reuse__total" role="status">{{ tr('共 {p0} 项', { p0: total }) }}</span>
        </div>
        <form :id="`${id}-assets`" class="chapter-reuse__form" @submit.prevent="addToChapter">
          <fieldset class="chapter-reuse__list" :disabled="saving">
            <legend class="visually-hidden">{{ tr('选择要加入本章的{p0}', { p0: typeLabel }) }}</legend>
            <div class="chapter-reuse__grid">
              <component :is="isInChapter(asset) ? 'article' : 'label'" v-for="asset in items" :key="asset.id" class="chapter-reuse__card"
                :class="{ 'is-selected': selectedId === asset.id, 'is-in-chapter': isInChapter(asset) }">
                <span class="chapter-reuse__preview" aria-hidden="true">
                  <component :is="icon" :size="30" />
                  <img v-if="asset.main_image_thumbnail || asset.main_image" :src="asset.main_image_thumbnail || asset.main_image"
                    alt="" loading="lazy" decoding="async" @error="fallbackImage($event, asset.main_image)" />
                </span>
                <span v-if="isInChapter(asset)" class="chapter-reuse__added"><Check :size="14" aria-hidden="true" />{{ tr('已在本章') }}</span>
                <span class="chapter-reuse__identity">
                  <strong :title="asset.canonical_name">{{ asset.canonical_name }}</strong>
                  <small :title="chaptersLabel(asset)">{{ chaptersLabel(asset) }}</small>
                </span>
                <input v-if="!isInChapter(asset)" v-model="selectedId" type="radio" name="asset" :value="asset.id" @change="saveError = false" />
              </component>
            </div>
            <p v-if="loading" class="chapter-reuse__state" role="status">{{ tr('正在加载项目资产…') }}</p>
            <div v-else-if="failedPage" class="chapter-reuse__state">
              <span class="chapter-reuse__error" role="alert">{{ tr('项目资产加载失败') }}</span>
              <AppButton size="sm" @click="loadPage(failedPage)">{{ tr('重试') }}</AppButton>
            </div>
            <div v-else-if="!items.length" class="chapter-reuse__state">
              <span role="status">{{ query || sourceChapters.length ? tr('未找到匹配的{p0}', { p0: typeLabel }) : tr('项目中暂无{p0}', { p0: typeLabel }) }}</span>
              <AppButton v-if="sourceChapters.length" size="sm" @click="clearChapterFilters">{{ tr('清除筛选') }}</AppButton>
            </div>
            <AppButton v-else-if="page < pages" class="chapter-reuse__more" size="sm" @click="loadPage(page + 1)">{{ tr('加载更多') }}</AppButton>
          </fieldset>
        </form>
      </div>
    </div>
    <footer class="chapter-reuse__footer">
      <span v-if="saveError" class="chapter-reuse__error" role="alert">{{ tr('加入本章失败，请重试。') }}</span>
      <span v-else-if="selected" class="chapter-reuse__selection" :title="selected.canonical_name">{{ tr('已选「{p0}」', { p0: selected.canonical_name }) }}</span>
      <AppButton type="button" size="md" :disabled="saving" @click="panel?.close()">{{ tr('取消') }}</AppButton>
      <AppButton type="submit" :form="`${id}-assets`" variant="primary" size="md" :disabled="!selected" :loading="saving">{{ saving ? tr('正在加入本章…') : tr('加入本章') }}</AppButton>
    </footer>
  </dialog>
</template>

<style scoped>
.chapter-reuse {
  box-sizing: border-box;
  width: min(1060px, calc(100% - 32px));
  height: min(720px, calc(100dvh - 32px));
  max-height: calc(100dvh - 32px);
  padding: 0;
  border: 1px solid var(--app-border-strong);
  border-radius: 16px;
  color: var(--app-text);
  background: var(--app-surface);
}
.chapter-reuse[open] { display: flex; flex-direction: column; }
.chapter-reuse:modal { overscroll-behavior: contain; }
.chapter-reuse::backdrop { overflow: hidden; overscroll-behavior: contain; background: rgb(15 17 27 / 55%); }
.chapter-reuse :is(button, input, h2):focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.chapter-reuse__header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 20px 22px 16px; border-bottom: 1px solid var(--app-border); }
.chapter-reuse__header h2 { margin: 0 0 6px; font-size: 20px; line-height: 1.3; }
.chapter-reuse__header h2:focus { outline: none; }
.chapter-reuse__header p { display: flex; align-items: flex-start; gap: 6px; margin: 0; color: var(--app-text-secondary); font-size: 13px; overflow-wrap: anywhere; }
.chapter-reuse__header p svg { flex: none; margin-top: 2px; }
.chapter-reuse__body { display: grid; grid-template-columns: 212px minmax(0, 1fr); flex: 1; min-height: 0; }
.chapter-reuse__filters {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-inline-end: 1px solid var(--app-border);
  background: var(--app-surface-muted);
}
.chapter-reuse__filters .chapter-reuse__filter-toggle { display: none; }
.chapter-reuse__filter-panel, .chapter-reuse__list { min-inline-size: 0; min-height: 0; margin: 0; border: 0; }
.chapter-reuse__filter-panel { display: flex; flex-direction: column; flex: 1; padding: 14px 10px 0; }
.chapter-reuse__filter-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 4px 10px; font-size: 13px; }
.chapter-reuse__filter-heading button { color: var(--app-text-secondary); }
.chapter-reuse__chapter-search {
  min-width: 0;
  min-height: 38px;
  margin: 0 4px 8px;
  padding: 0 8px;
  border: 1px solid var(--app-border-strong);
  border-radius: 8px;
  color: var(--app-text);
  background: var(--app-surface);
  font: inherit;
  font-size: 1rem;
}
.chapter-reuse__chapter-options { display: grid; align-content: start; gap: 2px; padding: 2px 4px 14px; overflow: auto; overscroll-behavior: contain; }
.chapter-reuse__chapter-option { display: grid; grid-template-columns: 16px minmax(0, 1fr); align-items: center; gap: 9px; min-height: 44px; padding: 5px 8px; border-radius: 8px; cursor: pointer; }
.chapter-reuse__chapter-option:hover { background: var(--app-surface-hover); }
.chapter-reuse__chapter-option:has(input:checked) { background: var(--app-accent-soft); }
.chapter-reuse__chapter-option input, .chapter-reuse__card input { width: 16px; height: 16px; margin: 0; accent-color: var(--app-accent); }
.chapter-reuse__chapter-name { display: grid; }
.chapter-reuse__chapter-name strong { font-size: 12px; }
.chapter-reuse__chapter-name small, .chapter-reuse__no-chapters { color: var(--app-text-secondary); font-size: 12px; }
.chapter-reuse__chapter-name small, .chapter-reuse__identity > *, .chapter-reuse__selection { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chapter-reuse__no-chapters { margin: 8px; text-align: center; }
.chapter-reuse__results, .chapter-reuse__form { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.chapter-reuse__form { flex: 1; }
.chapter-reuse__toolbar { display: flex; align-items: center; gap: 12px; padding: 14px 18px 10px; }
.chapter-reuse__search {
  display: flex;
  align-items: center;
  flex: 1;
  gap: 8px;
  min-width: 0;
  padding: 2px 5px 2px 10px;
  border: 1px solid var(--app-border-strong);
  border-radius: 9px;
  color: var(--app-text-secondary);
  background: var(--app-surface-muted);
}
.chapter-reuse__search:focus-within { border-color: var(--app-accent); }
.chapter-reuse__search > svg, .chapter-reuse__added svg { flex: none; }
.chapter-reuse__search input { flex: 1; min-width: 0; min-height: 38px; padding: 0 3px; border: 0; color: var(--app-text); background: transparent; font: inherit; font-size: 1rem; }
.chapter-reuse__search input:focus-visible { outline: none; }
.chapter-reuse__search input::placeholder, .chapter-reuse__chapter-search::placeholder { color: var(--app-text-secondary); }
.chapter-reuse__total { flex: none; color: var(--app-text-secondary); font-size: 12px; }
.chapter-reuse__list { display: block; flex: 1; padding: 4px 18px 16px; overflow: auto; overscroll-behavior: contain; }
.chapter-reuse__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 156px), 1fr)); gap: 12px; }
.chapter-reuse__card {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
}
label.chapter-reuse__card, .chapter-reuse__card input { cursor: pointer; }
label.chapter-reuse__card:hover { border-color: var(--app-border-strong); background: var(--app-surface-hover); }
.chapter-reuse__list:disabled label, .chapter-reuse__filter-panel:disabled label { cursor: not-allowed; }
.chapter-reuse__card.is-selected { border-color: var(--app-accent); background: var(--app-accent-soft); }
.chapter-reuse__card:has(input:focus-visible) { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.chapter-reuse__preview {
  position: relative;
  display: grid;
  grid-column: 1 / -1;
  aspect-ratio: 4 / 3;
  place-items: center;
  overflow: clip;
  border-radius: 11px 11px 0 0;
  border-bottom: 1px solid var(--app-border);
  color: var(--app-text-muted);
  background: var(--app-surface-muted);
}
.chapter-reuse__preview img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: var(--app-surface-muted); }
.chapter-reuse__identity { display: grid; gap: 3px; min-width: 0; padding: 10px; }
.chapter-reuse__identity strong { font-size: 13px; }
.chapter-reuse__identity small { color: var(--app-text-secondary); font-size: 11px; }
.chapter-reuse__card input { margin-inline-end: 10px; }
.chapter-reuse__added {
  position: absolute;
  inset: 7px 7px auto auto;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 7px;
  border-radius: 7px;
  color: var(--app-text);
  background: var(--app-surface-raised);
  font-size: 11px;
}
.chapter-reuse__added svg { color: var(--creation-success); }
.chapter-reuse__state { display: grid; justify-items: center; place-content: center; gap: 8px; min-height: 116px; margin: 0; color: var(--app-text-secondary); font-size: 13px; text-align: center; }
.chapter-reuse__more { display: flex; margin: 12px auto 0; }
.chapter-reuse__footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; padding: 12px 22px; border-top: 1px solid var(--app-border); }
.chapter-reuse__error { color: var(--creation-danger); font-size: 13px; }
.chapter-reuse__footer :is(.chapter-reuse__error, .chapter-reuse__selection) { flex: 1 1 120px; min-width: 0; margin-inline-end: auto; }
.chapter-reuse__selection { color: var(--app-text-secondary); font-size: 13px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (max-width: 680px) {
  .chapter-reuse { width: calc(100% - 20px); height: calc(100dvh - 20px); max-height: calc(100dvh - 20px); }
  .chapter-reuse__body { grid-template: auto minmax(0, 1fr) / minmax(0, 1fr); }
  .chapter-reuse__header, .chapter-reuse__list, .chapter-reuse__footer { padding-inline: 14px; }
  .chapter-reuse__filters { border-inline-end: 0; border-bottom: 1px solid var(--app-border); }
  .chapter-reuse__filters .chapter-reuse__filter-toggle { display: flex; justify-content: flex-start; min-height: 44px; border-radius: 0; padding-inline: 14px; }
  .chapter-reuse__filter-toggle small { margin-inline-start: auto; color: var(--app-text-secondary); font-size: 12px; }
  .chapter-reuse__filter-toggle:focus-visible { outline-offset: -3px; }
  .chapter-reuse__filter-panel:not(.is-open), .chapter-reuse__filter-heading > strong { display: none; }
  .chapter-reuse__filter-panel { padding: 0 10px; }
  .chapter-reuse__filter-heading { justify-content: flex-end; padding-bottom: 2px; }
  .chapter-reuse__chapter-options { grid-template-columns: repeat(auto-fill, minmax(min(100%, 140px), 1fr)); max-height: min(24dvh, 180px); }
  .chapter-reuse__toolbar { padding-inline: 14px; }
  .chapter-reuse__grid { gap: 10px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 128px), 1fr)); }
  .chapter-reuse__footer .app-button { min-height: 44px; }
}
</style>
