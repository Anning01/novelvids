<script setup lang="ts">
import { ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { episodeDisplayLabel, stripChapterOrdinal } from '@/shared/chapterTitle'
import type { Chapter } from '@/types'

defineProps<{
  chapters: Chapter[]
  activeChapterId: number
}>()

const emit = defineEmits<{
  select: [chapter: Chapter]
}>()

const railElement = ref<HTMLElement | null>(null)
const tooltipChapter = ref<Chapter | null>(null)
const tooltipTop = ref(0)

function showTooltip(event: Event, chapter: Chapter) {
  const button = event.currentTarget
  const rail = railElement.value
  if (!(button instanceof HTMLElement) || !rail) return
  const buttonRect = button.getBoundingClientRect()
  const railRect = rail.getBoundingClientRect()
  const relativeCenter = buttonRect.top - railRect.top + buttonRect.height / 2
  tooltipTop.value = Math.max(28, Math.min(relativeCenter, railRect.height - 28))
  tooltipChapter.value = chapter
}

function hideTooltip() {
  tooltipChapter.value = null
}

function selectChapter(chapter: Chapter) {
  hideTooltip()
  emit('select', chapter)
}
</script>

<template>
  <aside ref="railElement" class="episode-rail" aria-label="集数导航">
    <strong>集数</strong>
    <AppScrollArea class="episode-rail__list" aria-label="项目集数列表" @scroll="hideTooltip">
      <AppButton
        v-for="chapter in chapters"
        :key="chapter.id"
        variant="ghost"
        size="sm"
        icon-only
        :active="activeChapterId === chapter.id"
        :aria-current="activeChapterId === chapter.id ? 'page' : undefined"
        :aria-label="episodeDisplayLabel(chapter)"
        :aria-describedby="tooltipChapter?.id === chapter.id ? `episode-tooltip-${chapter.id}` : undefined"
        @mouseenter="showTooltip($event, chapter)"
        @mouseleave="hideTooltip"
        @focus="showTooltip($event, chapter)"
        @blur="hideTooltip"
        @click="selectChapter(chapter)"
      >
        {{ chapter.number }}
      </AppButton>
      <span v-if="!chapters.length" class="episode-rail__empty">—</span>
    </AppScrollArea>
    <Transition name="episode-tooltip">
      <div
        v-if="tooltipChapter"
        :id="`episode-tooltip-${tooltipChapter.id}`"
        class="episode-rail__tooltip"
        role="tooltip"
        :style="{ top: `${tooltipTop}px` }"
      >
        <strong>第 {{ tooltipChapter.number }} 集</strong>
        <span v-if="stripChapterOrdinal(tooltipChapter.name)">{{ stripChapterOrdinal(tooltipChapter.name) }}</span>
      </div>
    </Transition>
  </aside>
</template>

<style scoped>
.episode-rail {
  position: fixed;
  top: var(--short-drama-episode-rail-top, var(--short-drama-topbar-height, 64px));
  bottom: 0;
  left: 0;
  z-index: 24;
  display: grid;
  width: var(--short-drama-episode-rail-width, 48px);
  align-content: start;
  justify-items: center;
  gap: 10px;
  padding: 14px 5px;
  color: var(--app-text-secondary);
  background: var(--app-surface);
  box-shadow: 1px 0 0 var(--app-border);
}

.episode-rail > strong {
  color: var(--app-text-secondary);
  font-size: 11px;
}

.episode-rail__list {
  display: grid;
  width: 100%;
  max-height: calc(100vh - var(--short-drama-episode-rail-top, var(--short-drama-topbar-height, 64px)) - 48px);
  justify-items: center;
  gap: 8px;
  padding: 2px 2px 12px;
  scrollbar-color: transparent transparent;
  scrollbar-width: none;
}

.episode-rail__list:hover,
.episode-rail__list:focus,
.episode-rail__list:focus-within { scrollbar-color: transparent transparent; }
.episode-rail__list::-webkit-scrollbar { display: none; width: 0; height: 0; }

.episode-rail__list :deep(.app-button) {
  width: 34px;
  min-height: 34px;
  color: var(--app-text-secondary);
  border-radius: 8px;
  background: transparent;
  box-shadow: inset 0 0 0 1px var(--app-border);
}

.episode-rail__list :deep(.app-button:hover:not(:disabled)) {
  color: var(--app-accent);
  background: var(--app-surface-hover);
  box-shadow: inset 0 0 0 1px var(--app-border-strong);
}

.episode-rail__list :deep(.app-button.is-active) {
  color: var(--app-accent);
  background: var(--app-accent-soft);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--app-accent) 18%, transparent);
}

.episode-rail__empty {
  color: var(--app-text-muted);
  font-size: 12px;
}

.episode-rail__tooltip {
  position: absolute;
  left: calc(100% + 10px);
  z-index: 4;
  display: grid;
  min-width: 128px;
  max-width: 260px;
  gap: 3px;
  padding: 9px 11px;
  color: var(--app-text);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface-raised);
  box-shadow: var(--app-shadow);
  pointer-events: none;
  transform: translateY(-50%);
  backdrop-filter: blur(12px);
}

.episode-rail__tooltip::before {
  position: absolute;
  top: 50%;
  right: 100%;
  width: 8px;
  height: 8px;
  border-bottom: 1px solid var(--app-border);
  border-left: 1px solid var(--app-border);
  background: var(--app-surface-raised);
  content: '';
  transform: translate(5px,-50%) rotate(45deg);
}

.episode-rail__tooltip strong { color: var(--app-accent); font-size: 11px; }
.episode-rail__tooltip span { overflow: hidden; color: var(--app-text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.episode-tooltip-enter-active,.episode-tooltip-leave-active { transition: opacity .16s ease,transform .18s ease; }
.episode-tooltip-enter-from,.episode-tooltip-leave-to { opacity: 0; transform: translate(-6px,-50%) scale(.97); }

@media (prefers-reduced-motion: reduce) {
  .episode-tooltip-enter-active,.episode-tooltip-leave-active { transition-duration: .01ms; }
}

</style>
