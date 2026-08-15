<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ChevronDown, Search, Sparkles, X } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  modelValue: number[]
  episodeNumbers?: number[]
  currentEpisode?: number
}>(), {
  episodeNumbers: () => [],
})

const emit = defineEmits<{ 'update:modelValue': [value: number[]] }>()

const PAGE_SIZE = 50
const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const open = ref(false)
const rangeStart = ref<number | null>(null)
const rangeEnd = ref<number | null>(null)
const jumpEpisode = ref<number | null>(null)
const activePage = ref(0)
const rangeAnchor = ref<number | null>(null)
const panelPosition = ref({ left: 0, top: 0 })

const availableEpisodes = computed(() => {
  const source = props.episodeNumbers.length
    ? props.episodeNumbers
    : [...props.modelValue, ...(props.currentEpisode ? [props.currentEpisode] : [])]
  return [...new Set(source.filter(item => Number.isInteger(item) && item > 0))].sort((a, b) => a - b)
})
const selectedEpisodes = computed(() => [...new Set(props.modelValue.filter(item => Number.isInteger(item) && item > 0))].sort((a, b) => a - b))
const selectedSet = computed(() => new Set(selectedEpisodes.value))
const pages = computed(() => {
  const result: number[][] = []
  for (let index = 0; index < availableEpisodes.value.length; index += PAGE_SIZE) {
    result.push(availableEpisodes.value.slice(index, index + PAGE_SIZE))
  }
  return result
})
const visibleEpisodes = computed(() => pages.value[activePage.value] || [])
const activePageSelectedCount = computed(() => visibleEpisodes.value.filter(item => selectedSet.value.has(item)).length)
const summary = computed(() => formatEpisodeRanges(selectedEpisodes.value))

function formatEpisodeRanges(episodes: number[]) {
  if (!episodes.length) return '请选择适用集数'
  const ranges: string[] = []
  let start = episodes[0]!
  let previous = start
  for (const episode of episodes.slice(1)) {
    if (episode === previous + 1) {
      previous = episode
      continue
    }
    ranges.push(start === previous ? `第 ${start} 集` : `第 ${start}–${previous} 集`)
    start = episode
    previous = episode
  }
  ranges.push(start === previous ? `第 ${start} 集` : `第 ${start}–${previous} 集`)
  return ranges.join('、')
}

function updateSelection(values: Iterable<number>) {
  const available = new Set(availableEpisodes.value)
  const normalized = [...new Set([...values].filter(item => item > 0 && (!available.size || available.has(item))))].sort((a, b) => a - b)
  emit('update:modelValue', normalized)
}

function toggleEpisode(episode: number, event?: MouseEvent) {
  const next = new Set(selectedEpisodes.value)
  if (event?.shiftKey && rangeAnchor.value !== null) {
    const startIndex = availableEpisodes.value.indexOf(rangeAnchor.value)
    const endIndex = availableEpisodes.value.indexOf(episode)
    if (startIndex >= 0 && endIndex >= 0) {
      const [start, end] = startIndex <= endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
      for (const item of availableEpisodes.value.slice(start, end + 1)) next.add(item)
    }
  } else if (next.has(episode)) {
    next.delete(episode)
  } else {
    next.add(episode)
  }
  rangeAnchor.value = episode
  updateSelection(next)
}

function addRange() {
  if (!rangeStart.value) return
  const end = rangeEnd.value || rangeStart.value
  const [startValue, endValue] = rangeStart.value <= end ? [rangeStart.value, end] : [end, rangeStart.value]
  const next = new Set(selectedEpisodes.value)
  if (availableEpisodes.value.length) {
    for (const episode of availableEpisodes.value) {
      if (episode >= startValue && episode <= endValue) next.add(episode)
    }
  } else {
    for (let episode = startValue; episode <= Math.min(endValue, startValue + 999); episode += 1) next.add(episode)
  }
  updateSelection(next)
}

function useCurrentEpisode() {
  if (!props.currentEpisode) return
  const next = new Set(selectedEpisodes.value)
  next.add(props.currentEpisode)
  updateSelection(next)
  jumpToEpisode(props.currentEpisode)
}

function toggleVisiblePage() {
  const next = new Set(selectedEpisodes.value)
  const everySelected = visibleEpisodes.value.length > 0 && activePageSelectedCount.value === visibleEpisodes.value.length
  for (const episode of visibleEpisodes.value) {
    if (everySelected) next.delete(episode)
    else next.add(episode)
  }
  updateSelection(next)
}

function jumpToEpisode(value = jumpEpisode.value) {
  if (!value) return
  const index = availableEpisodes.value.indexOf(value)
  if (index >= 0) activePage.value = Math.floor(index / PAGE_SIZE)
}

function handleDocumentPointerDown(event: PointerEvent) {
  if (!open.value || !(event.target instanceof Node)) return
  if (!root.value?.contains(event.target) && !panel.value?.contains(event.target)) open.value = false
}

function handleDocumentKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') open.value = false
}

function toggleOpen() {
  open.value = !open.value
  if (open.value) {
    const bounds = root.value?.getBoundingClientRect()
    if (bounds) {
      const panelWidth = Math.min(530, window.innerWidth - 32)
      const halfWidth = panelWidth / 2
      const left = Math.min(window.innerWidth - halfWidth - 16, Math.max(halfWidth + 16, bounds.left + bounds.width / 2))
      const belowTop = bounds.bottom + 7
      const top = belowTop + 340 <= window.innerHeight - 16 ? belowTop : Math.max(16, bounds.top - 347)
      panelPosition.value = { left, top }
    }
    document.addEventListener('pointerdown', handleDocumentPointerDown)
    document.addEventListener('keydown', handleDocumentKeyDown)
  }
}

watch(open, value => {
  if (!value) {
    document.removeEventListener('pointerdown', handleDocumentPointerDown)
    document.removeEventListener('keydown', handleDocumentKeyDown)
  }
})

watch(() => props.currentEpisode, value => {
  if (value && !selectedEpisodes.value.length) rangeStart.value = value
}, { immediate: true })

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeyDown)
})
</script>

<template>
  <div ref="root" class="episode-picker" :class="{ 'is-open': open }">
    <button
      type="button"
      class="episode-picker__trigger"
      :aria-expanded="open"
      aria-haspopup="dialog"
      @click="toggleOpen"
    >
      <span :class="{ 'is-placeholder': !selectedEpisodes.length }">{{ summary }}</span>
      <small v-if="selectedEpisodes.length">{{ selectedEpisodes.length }} 集</small>
      <ChevronDown :size="14" />
    </button>

    <Teleport to="body">
      <section v-if="open" ref="panel" class="episode-picker__panel" :style="{ left: `${panelPosition.left}px`, top: `${panelPosition.top}px` }" role="dialog" aria-label="选择适用集数">
      <header>
        <div>
          <strong>选择适用集数</strong>
          <small><Sparkles :size="10" />AI 已预选，可批量调整</small>
        </div>
        <button type="button" aria-label="关闭集数选择" @click="open = false"><X :size="15" /></button>
      </header>

      <div class="episode-picker__toolbar">
        <button v-if="currentEpisode" type="button" @click="useCurrentEpisode">当前集</button>
        <button v-if="availableEpisodes.length" type="button" @click="updateSelection(availableEpisodes)">全部</button>
        <button type="button" :disabled="!selectedEpisodes.length" @click="updateSelection([])">清空</button>
        <label>
          <Search :size="13" />
          <input v-model.number="jumpEpisode" type="number" min="1" placeholder="跳到集数" @keyup.enter="jumpToEpisode()" />
        </label>
      </div>

      <div class="episode-picker__range">
        <span>连续区间</span>
        <label>从<input v-model.number="rangeStart" type="number" min="1" aria-label="区间开始集数" /></label>
        <i>—</i>
        <label>到<input v-model.number="rangeEnd" type="number" min="1" aria-label="区间结束集数" /></label>
        <button type="button" :disabled="!rangeStart" @click="addRange">加入选择</button>
      </div>

      <nav v-if="pages.length > 1" class="episode-picker__pages" aria-label="集数分段">
        <button
          v-for="(page, index) in pages"
          :key="page[0]"
          type="button"
          :class="{ 'is-active': activePage === index }"
          @click="activePage = index"
        >{{ page[0] }}–{{ page[page.length - 1] }}</button>
      </nav>

      <div v-if="visibleEpisodes.length" class="episode-picker__grid-heading">
        <span>逐集微调 <small>Shift 点击可连续选择</small></span>
        <button type="button" @click="toggleVisiblePage">
          <Check v-if="activePageSelectedCount === visibleEpisodes.length" :size="12" />
          {{ activePageSelectedCount === visibleEpisodes.length ? '取消本段' : '选择本段' }}
        </button>
      </div>
      <div v-if="visibleEpisodes.length" class="episode-picker__grid">
        <button
          v-for="episode in visibleEpisodes"
          :key="episode"
          type="button"
          :class="{ 'is-selected': selectedSet.has(episode), 'is-current': currentEpisode === episode }"
          :aria-pressed="selectedSet.has(episode)"
          @click="toggleEpisode(episode, $event)"
        >{{ episode }}</button>
      </div>
      <p v-else>暂未读取到项目集数，可使用上方连续区间添加。</p>

      <footer>
        <span v-if="selectedEpisodes.length"><strong>{{ selectedEpisodes.length }}</strong> 集已选</span>
        <span v-else>尚未选择</span>
        <button type="button" @click="open = false">完成</button>
      </footer>
      </section>
    </Teleport>
  </div>
</template>

<style scoped>
.episode-picker { position: relative; min-width: 0; font-weight: 450; }
.episode-picker__trigger { display: grid; width: 100%; height: 34px; grid-template-columns: minmax(0,1fr) auto auto; align-items: center; gap: 7px; padding: 0 9px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text); background: var(--app-surface); font: inherit; text-align: left; cursor: pointer; }
.episode-picker__trigger > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.episode-picker__trigger > span.is-placeholder { color: var(--app-text-muted); }
.episode-picker__trigger > small { padding: 2px 5px; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 7px; white-space: nowrap; }
.episode-picker__trigger > svg { color: var(--app-text-muted); transition: transform .16s ease; }
.episode-picker.is-open .episode-picker__trigger { border-color: var(--app-accent); box-shadow: 0 0 0 3px var(--app-accent-soft); }
.episode-picker.is-open .episode-picker__trigger > svg { transform: rotate(180deg); }
.episode-picker__panel { position: fixed; z-index: 1200; display: grid; width: min(530px,calc(100vw - 32px)); gap: 10px; padding: 13px; border: 1px solid var(--app-border); border-radius: 14px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 18px 46px rgb(24 29 48 / 24%); transform: translateX(-50%); }
.episode-picker__panel > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.episode-picker__panel > header > div { display: grid; gap: 2px; }
.episode-picker__panel > header strong { font-size: 11px; }
.episode-picker__panel > header small { display: flex; align-items: center; gap: 3px; color: var(--app-accent); font-size: 8px; }
.episode-picker__panel > header > button { display: grid; width: 26px; height: 26px; place-items: center; border: 0; border-radius: 7px; color: var(--app-text-secondary); background: transparent; cursor: pointer; }
.episode-picker__panel > header > button:hover { background: var(--app-surface-muted); }
.episode-picker__toolbar { display: flex; align-items: center; gap: 5px; }
.episode-picker__toolbar > button,.episode-picker__range > button,.episode-picker__pages button,.episode-picker__grid-heading button,.episode-picker__panel > footer button { min-height: 28px; padding: 0 9px; border: 1px solid var(--app-border); border-radius: 7px; color: var(--app-text-secondary); background: var(--app-surface); font: inherit; font-size: 8px; font-weight: 650; cursor: pointer; }
.episode-picker__toolbar > button:hover,.episode-picker__range > button:hover,.episode-picker__pages button:hover,.episode-picker__grid-heading button:hover { border-color: var(--app-accent); color: var(--app-accent); }
.episode-picker__toolbar > button:disabled,.episode-picker__range > button:disabled { cursor: not-allowed; opacity: .45; }
.episode-picker__toolbar > label { display: flex; min-width: 0; height: 28px; flex: 1; align-items: center; gap: 5px; margin-left: auto; padding: 0 8px; border: 1px solid var(--app-border); border-radius: 7px; color: var(--app-text-muted); }
.episode-picker__toolbar input,.episode-picker__range input { min-width: 0; border: 0 !important; outline: 0; color: var(--app-text); background: transparent; box-shadow: none !important; font: inherit; }
.episode-picker__toolbar input { width: 100%; height: 26px !important; padding: 0 !important; }
.episode-picker__range { display: grid; grid-template-columns: auto minmax(72px,1fr) auto minmax(72px,1fr) auto; align-items: center; gap: 6px; padding: 9px; border-radius: 9px; background: var(--app-surface-muted); }
.episode-picker__range > span { color: var(--app-text-secondary); font-size: 8px; font-weight: 650; }
.episode-picker__range > label { display: grid; height: 28px; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 4px; padding: 0 7px; border: 1px solid var(--app-border); border-radius: 7px; color: var(--app-text-muted); background: var(--app-surface); font-size: 8px; }
.episode-picker__range input { height: 26px !important; padding: 0 !important; }
.episode-picker__range > i { color: var(--app-text-muted); font-style: normal; }
.episode-picker__pages { display: grid; max-height: 58px; grid-template-columns: repeat(6,minmax(0,1fr)); gap: 5px; overflow-y: auto; padding-bottom: 2px; scrollbar-width: none; }
.episode-picker__pages::-webkit-scrollbar { display: none; }
.episode-picker__pages button { min-width: 0; min-height: 25px; overflow: hidden; padding: 0 5px; text-overflow: ellipsis; white-space: nowrap; }
.episode-picker__pages button.is-active { border-color: var(--app-accent); color: var(--app-accent); background: var(--app-accent-soft); }
.episode-picker__grid-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.episode-picker__grid-heading > span { color: var(--app-text-secondary); font-size: 8px; font-weight: 650; }
.episode-picker__grid-heading small { color: var(--app-text-muted); font-size: 7px; font-weight: 450; }
.episode-picker__grid-heading button { display: inline-flex; min-height: 24px; align-items: center; gap: 3px; }
.episode-picker__grid { display: grid; grid-template-columns: repeat(10,minmax(0,1fr)); gap: 5px; }
.episode-picker__grid > button { position: relative; height: 29px; border: 1px solid transparent; border-radius: 7px; color: var(--app-text-secondary); background: var(--app-surface-muted); font: inherit; font-size: 8px; cursor: pointer; }
.episode-picker__grid > button:hover { border-color: var(--app-accent); color: var(--app-accent); }
.episode-picker__grid > button.is-selected { border-color: var(--app-accent); color: var(--app-accent); background: var(--app-accent-soft); font-weight: 700; }
.episode-picker__grid > button.is-current::after { position: absolute; right: 3px; bottom: 3px; width: 3px; height: 3px; border-radius: 50%; background: var(--app-accent); content: ''; }
.episode-picker__panel > p { margin: 0; padding: 16px; color: var(--app-text-muted); background: var(--app-surface-muted); font-size: 8px; text-align: center; }
.episode-picker__panel > footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-top: 9px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); font-size: 8px; }
.episode-picker__panel > footer strong { color: var(--app-accent); }
.episode-picker__panel > footer button { border-color: var(--app-accent); color: #fff; background: var(--app-accent); }
@media (max-width: 620px) {
  .episode-picker__panel { top: auto !important; right: 12px; bottom: 12px; left: 12px !important; width: auto; max-height: calc(100vh - 24px); overflow-y: auto; transform: none; }
  .episode-picker__grid { grid-template-columns: repeat(5,minmax(0,1fr)); }
  .episode-picker__pages { grid-template-columns: repeat(3,minmax(0,1fr)); }
  .episode-picker__range { grid-template-columns: auto 1fr auto 1fr; }
  .episode-picker__range > button { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) { .episode-picker__trigger > svg { transition: none; } }
</style>
