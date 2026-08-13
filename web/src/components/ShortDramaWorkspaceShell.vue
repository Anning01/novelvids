<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, BookOpenText, Clapperboard, Film, Settings2, Video } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import ShortDramaEpisodeRail from '@/components/ShortDramaEpisodeRail.vue'
import type { Chapter } from '@/types'

export type ShortDramaPhase = 'script' | 'settings' | 'storyboard' | 'video'

const props = withDefaults(defineProps<{
  projectId: number
  projectName: string
  aspectRatio: string
  resolution: string
  styleName: string
  activePhase: ShortDramaPhase
  creationMode?: 'agent' | 'manual'
  chapters?: Chapter[]
  activeChapterId?: number
  showEpisodeRail?: boolean
  showProjectMeta?: boolean
  videoEnabled?: boolean
  immersive?: boolean
}>(), {
  creationMode: 'agent',
  chapters: () => [],
  activeChapterId: 0,
  showEpisodeRail: true,
  showProjectMeta: true,
  videoEnabled: false,
  immersive: false,
})

const emit = defineEmits<{
  selectChapter: [chapter: Chapter]
}>()

const route = useRoute()
const router = useRouter()
const phases = computed(() => [
  ...(props.creationMode === 'agent' ? [{ key: 'script' as const, label: '剧本', icon: BookOpenText }] : []),
  { key: 'settings' as const, label: '设定', icon: Settings2 },
  { key: 'storyboard' as const, label: '分镜', icon: Clapperboard },
  { key: 'video' as const, label: '视频', icon: Video, disabled: !props.videoEnabled },
])
const hasEpisodeRail = computed(() => props.showEpisodeRail && !props.immersive && props.activePhase !== 'script')

function phasePath(phase: ShortDramaPhase) {
  if (phase === 'script') return `/create/short-drama/agent/${props.projectId}`
  if (phase === 'settings') return `/create/short-drama/manual/${props.projectId}`
  if (phase === 'storyboard') return `/create/short-drama/storyboard/${props.projectId}`
  return `/create/short-drama/video/${props.projectId}`
}

function selectPhase(phase: ShortDramaPhase, disabled = false) {
  if (disabled || phase === props.activePhase) return
  const chapter = props.activeChapterId || Number(route.query.chapter)
  void router.push({
    path: phasePath(phase),
    query: chapter > 0 ? { chapter: String(chapter) } : undefined,
  })
}
</script>

<template>
  <div
    class="short-drama-workspace-shell"
    :class="{ 'has-episode-rail': hasEpisodeRail, 'is-immersive': immersive }"
  >
    <header class="short-drama-workspace-header">
      <div class="short-drama-project-identity">
        <AppButton
          class="short-drama-back"
          variant="ghost"
          size="sm"
          icon-only
          aria-label="返回项目"
          title="返回项目"
          @click="router.push('/projects')"
        >
          <ArrowLeft :size="18" />
        </AppButton>
        <div class="short-drama-project-copy">
          <div class="short-drama-project-name"><slot name="project-name"><strong>{{ projectName }}</strong></slot></div>
          <slot v-if="showProjectMeta" name="project-meta">
            <span class="short-drama-project-meta"><Film :size="13" />{{ aspectRatio }}<i />{{ resolution }}<i />{{ styleName }}</span>
          </slot>
        </div>
      </div>

      <nav v-if="!immersive" class="short-drama-phase-nav" aria-label="短剧制作流程">
        <template v-for="(phase, index) in phases" :key="phase.key">
          <span v-if="index" class="short-drama-phase-line" />
          <AppButton
            variant="ghost"
            size="sm"
            :active="activePhase === phase.key"
            :disabled="phase.disabled"
            :aria-current="activePhase === phase.key ? 'step' : undefined"
            @click="selectPhase(phase.key, phase.disabled)"
          >
            <component :is="phase.icon" :size="16" />{{ phase.label }}
          </AppButton>
        </template>
      </nav>

      <div class="short-drama-header-end"><slot name="header-end" /></div>
    </header>

    <ShortDramaEpisodeRail
      v-if="hasEpisodeRail"
      :chapters="chapters"
      :active-chapter-id="activeChapterId"
      @select="emit('selectChapter', $event)"
    />

    <div class="short-drama-workspace-body"><slot /></div>
  </div>
</template>

<style scoped>
.short-drama-workspace-shell {
  --short-drama-header-height: 72px;
  min-width: 0;
  min-height: 100vh;
}

.short-drama-workspace-header {
  position: fixed;
  top: 0;
  right: 0;
  left: 0;
  z-index: 30;
  display: grid;
  min-height: var(--short-drama-header-height);
  grid-template-columns: minmax(270px,1fr) auto minmax(270px,1fr);
  align-items: center;
  padding: 8px 28px;
  color: var(--app-text);
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface-raised);
  box-shadow: 0 8px 28px rgb(36 40 60 / 4%);
  backdrop-filter: blur(16px);
}

.short-drama-project-identity { display: flex; min-width: 0; align-items: center; gap: 13px; }
.short-drama-back { color: var(--app-text-secondary); }
.short-drama-project-copy { display: grid; min-width: 0; gap: 3px; }
.short-drama-project-name { display: flex; min-width: 0; min-height: 24px; align-items: center; }
.short-drama-project-name :slotted(strong) { overflow: hidden; max-width: 360px; color: var(--app-text); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.short-drama-project-meta { display: flex; align-items: center; gap: 7px; color: var(--app-text-muted); font-size: 11px; }
.short-drama-project-meta i { width: 1px; height: 10px; background: var(--app-border-strong); }

.short-drama-phase-nav { grid-column: 2; display: flex; align-items: center; }
.short-drama-phase-line { width: 28px; height: 1px; background: var(--app-border); }
.short-drama-phase-nav :deep(.app-button) { width: 72px; min-height: 54px; flex-direction: column; gap: 4px; color: var(--app-text-muted); border: 1px solid transparent; border-radius: 17px; background: transparent; font-size: 11px; }
.short-drama-phase-nav :deep(.app-button:hover:not(:disabled)) { color: var(--app-text-secondary); background: var(--app-surface-hover); }
.short-drama-phase-nav :deep(.app-button.is-active) { color: var(--app-accent); background: var(--app-accent-soft); box-shadow: 0 8px 22px color-mix(in srgb, var(--app-accent) 12%, transparent); }
.short-drama-header-end { grid-column: 3; display: flex; justify-self: end; align-items: center; }

.short-drama-workspace-shell :deep(.episode-rail) { --short-drama-episode-rail-top: var(--short-drama-header-height); }
.short-drama-workspace-body { min-width: 0; min-height: 100vh; padding-top: var(--short-drama-header-height); }
.has-episode-rail > .short-drama-workspace-body { margin-left: 48px; }

.is-immersive { height: 100vh; overflow: hidden; }
.is-immersive .short-drama-workspace-header { right: 0; min-height: 0; padding: 14px 18px; border: 0; pointer-events: none; background: transparent; box-shadow: none; backdrop-filter: none; }
.is-immersive .short-drama-project-identity,.is-immersive .short-drama-header-end { pointer-events: auto; }
.is-immersive .short-drama-workspace-body { height: 100vh; min-height: 0; padding-top: 0; }
.is-immersive .short-drama-back { color: #eee9e2; background: rgb(33 30 27 / 92%); box-shadow: inset 0 0 0 1px #3b3631,0 8px 24px rgb(0 0 0 / 24%); backdrop-filter: blur(12px); }

@media (max-width: 900px) {
  .short-drama-workspace-shell { --short-drama-header-height: 124px; }
  .short-drama-workspace-header { grid-template-columns: 1fr auto; grid-template-rows: auto auto; gap: 8px; padding: 10px 14px; }
  .short-drama-phase-nav { grid-column: 1 / -1; grid-row: 2; justify-content: center; }
  .short-drama-header-end { grid-column: 2; grid-row: 1; }
  .short-drama-phase-nav :deep(.app-button) { width: 60px; min-height: 46px; }
  .short-drama-phase-line { width: 14px; }
  .is-immersive { --short-drama-header-height: 0px; }
  .is-immersive .short-drama-workspace-header { display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto; padding: 12px 14px; }
}

@media (max-width: 520px) {
  .short-drama-phase-nav :deep(.app-button) { width: 52px; }
  .short-drama-phase-line { width: 7px; }
}
</style>
