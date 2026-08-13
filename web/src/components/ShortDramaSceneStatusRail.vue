<script setup lang="ts">
import { ref } from 'vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import type { SceneGenerationState, SceneStatusRailItem } from '@/shared/sceneGenerationStatus'

defineProps<{
  items: SceneStatusRailItem[]
  activeSceneId: number
}>()

const emit = defineEmits<{
  select: [sceneId: number]
}>()

const stateLabels: Record<SceneGenerationState, string> = {
  completed: '已完成',
  error: '生成异常',
  pending: '待生成',
}

const railElement = ref<HTMLElement | null>(null)
const tooltipItem = ref<SceneStatusRailItem | null>(null)
const tooltipTop = ref(0)

function showTooltip(event: Event, item: SceneStatusRailItem) {
  const button = event.currentTarget
  const rail = railElement.value
  if (!(button instanceof HTMLElement) || !rail) return
  const buttonRect = button.getBoundingClientRect()
  const railRect = rail.getBoundingClientRect()
  tooltipTop.value = Math.max(24, Math.min(buttonRect.top - railRect.top + buttonRect.height / 2, railRect.height - 24))
  tooltipItem.value = item
}

function hideTooltip() {
  tooltipItem.value = null
}

function selectScene(sceneId: number) {
  hideTooltip()
  emit('select', sceneId)
}
</script>

<template>
  <aside ref="railElement" class="scene-status-rail" aria-label="分镜生成状态">
    <AppScrollArea class="scene-status-rail__list" aria-label="本集分镜状态列表" @scroll="hideTooltip">
      <button
        v-for="item in items"
        :key="item.sceneId"
        type="button"
        class="scene-status-rail__item"
        :class="[`is-${item.state}`, { 'is-active': activeSceneId === item.sceneId }]"
        :aria-current="activeSceneId === item.sceneId ? 'location' : undefined"
        :aria-label="`分镜 ${item.sequence}，${stateLabels[item.state]}`"
        :aria-describedby="tooltipItem?.sceneId === item.sceneId ? `scene-status-tooltip-${item.sceneId}` : undefined"
        @mouseenter="showTooltip($event, item)"
        @mouseleave="hideTooltip"
        @focus="showTooltip($event, item)"
        @blur="hideTooltip"
        @click="selectScene(item.sceneId)"
      >
        <span class="scene-status-rail__bar" aria-hidden="true" />
      </button>
      <span v-if="!items.length" class="scene-status-rail__empty" aria-hidden="true" />
    </AppScrollArea>
    <Transition name="scene-status-tooltip">
      <span
        v-if="tooltipItem"
        :id="`scene-status-tooltip-${tooltipItem.sceneId}`"
        class="scene-status-rail__tooltip"
        role="tooltip"
        :style="{ top: `${tooltipTop}px` }"
      >
        分镜 {{ tooltipItem.sequence }} · {{ stateLabels[tooltipItem.state] }}
      </span>
    </Transition>
  </aside>
</template>

<style scoped>
.scene-status-rail {
  position: fixed;
  top: calc(var(--short-drama-episode-rail-top, var(--short-drama-topbar-height, 64px)) + var(--short-drama-scene-status-offset, 104px));
  bottom: 0;
  left: var(--short-drama-episode-rail-width, 48px);
  z-index: 23;
  width: var(--short-drama-scene-status-rail-width, 16px);
  color: var(--app-text-secondary);
  background: transparent;
}

.scene-status-rail__list {
  display: grid;
  width: 100%;
  max-height: 100%;
  justify-items: center;
  gap: 8px;
  padding: 10px 0 14px;
  scrollbar-color: transparent transparent;
  scrollbar-width: none;
  transform: translateX(4px);
}

.scene-status-rail__list::-webkit-scrollbar { display: none; width: 0; height: 0; }

.scene-status-rail__item {
  position: relative;
  display: grid;
  width: 16px;
  height: 34px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 999px;
  outline: none;
  background: transparent;
  cursor: pointer;
}

.scene-status-rail__bar {
  width: 8px;
  height: 100%;
  border-radius: 999px;
  background: var(--app-border-strong);
  transition: width .16s ease, filter .16s ease, transform .16s ease;
}

.scene-status-rail__item.is-completed .scene-status-rail__bar { background: #68d99c; }
.scene-status-rail__item.is-error .scene-status-rail__bar { background: #f08a9a; }
.scene-status-rail__item.is-pending .scene-status-rail__bar { background: color-mix(in srgb, var(--app-text-muted) 20%, var(--app-surface)); }

.scene-status-rail__item:hover .scene-status-rail__bar,
.scene-status-rail__item:focus-visible .scene-status-rail__bar { width: 10px; filter: saturate(1.08); transform: scaleY(1.04); }

.scene-status-rail__item:focus-visible { box-shadow: 0 0 0 2px var(--app-accent-soft), 0 0 0 3px var(--app-accent); }

.scene-status-rail__item.is-active::before {
  position: absolute;
  top: 50%;
  left: 0;
  width: 0;
  height: 0;
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  border-left: 5px solid var(--app-accent);
  content: '';
  transform: translateY(-50%);
}

.scene-status-rail__tooltip {
  position: absolute;
  left: calc(100% + 9px);
  z-index: 4;
  width: max-content;
  max-width: 180px;
  padding: 7px 9px;
  color: var(--app-text);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface-raised);
  box-shadow: var(--app-shadow);
  font-size: 11px;
  font-weight: 650;
  pointer-events: none;
  transform: translateY(-50%);
  white-space: nowrap;
}

.scene-status-tooltip-enter-active,.scene-status-tooltip-leave-active { transition: opacity .14s ease, transform .16s ease; }
.scene-status-tooltip-enter-from,.scene-status-tooltip-leave-to { opacity: 0; transform: translate(-5px,-50%) scale(.98); }

.scene-status-rail__empty { display: block; width: 8px; height: 34px; border-radius: 999px; background: color-mix(in srgb, var(--app-text-muted) 12%, var(--app-surface)); }

@media (prefers-reduced-motion: reduce) {
  .scene-status-rail__bar,.scene-status-tooltip-enter-active,.scene-status-tooltip-leave-active { transition-duration: .01ms; }
}
</style>
