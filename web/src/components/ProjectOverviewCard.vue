<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { BookOpen, Clapperboard, Clock3, Ellipsis, Image, Trash2 } from 'lucide-vue-next'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import { mediaUrl } from '@/api'
import { fallbackImage } from '@/shared/mediaFallback'
import { projectDate, projectKindLabel, projectNumber, projectRuntime } from '@/shared/projectOverview'
import { projectEntryRoute, readShortDramaSettings } from '@/shared/shortDramaProject'
import type { ProjectOverviewItem } from '@/types'

const props = defineProps<{ project: ProjectOverviewItem; editable: boolean; deleting?: boolean }>()
const emit = defineEmits<{ remove: [project: ProjectOverviewItem] }>()
const menuOpen = ref(false)
const actions = ref<HTMLElement | null>(null)
const trigger = ref<InstanceType<typeof AppButton> | null>(null)
const deleteButton = ref<HTMLButtonElement | null>(null)
const runtime = computed(() => projectRuntime(props.project.production.video_seconds, props.project.production.unknown_duration_count))
const settings = computed(() => readShortDramaSettings(props.project))
const metadata = computed(() => [projectKindLabel(props.project), settings.value.aspectRatio, settings.value.resolution?.toUpperCase()].filter(Boolean).join(' · '))
const stateLabel = computed(() => ({ not_started: tr('未开始'), in_progress: tr('制作中'), ready: tr('视频就绪') }[props.project.production.state]))
const tags = computed(() => props.project.tags?.filter(Boolean) ?? [])

async function openMenu() {
  menuOpen.value = !menuOpen.value
  if (menuOpen.value) {
    await nextTick()
    deleteButton.value?.focus()
  }
}

function closeMenu(restoreFocus = false) {
  menuOpen.value = false
  if (restoreFocus) (trigger.value?.$el as HTMLButtonElement | undefined)?.focus()
}

function outside(event: PointerEvent) {
  if (event.target instanceof Node && !actions.value?.contains(event.target)) closeMenu()
}

function remove() {
  closeMenu(true)
  emit('remove', props.project)
}

onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <article class="project-overview-card" :class="{ 'is-deleting': deleting }" :aria-labelledby="`project-title-${project.id}`">
    <RouterLink :to="projectEntryRoute(project)" class="project-overview-card__link" :aria-label="tr('打开项目：{p0}', { p0: project.name })" :aria-describedby="`project-progress-${project.id} project-stats-${project.id}`">
      <div class="project-overview-card__identity">
        <div class="project-overview-card__cover">
          <img v-if="project.cover" :src="mediaUrl(project.cover_thumbnail || project.cover)" alt="" width="84" height="120" loading="lazy" decoding="async" @error="fallbackImage($event, mediaUrl(project.cover))">
          <BookOpen v-else :size="29" :stroke-width="1.5" aria-hidden="true" />
        </div>
        <div class="project-overview-card__copy">
          <span class="project-overview-card__status" :class="`is-${project.production.state}`">{{ stateLabel }}</span>
          <h2 :id="`project-title-${project.id}`" :title="project.name">{{ project.name }}</h2>
          <p class="project-overview-card__metadata" :title="metadata">{{ metadata }}</p>
          <div class="project-overview-card__tags" :title="tags.join(' · ')">
            <span v-for="tag in tags.slice(0, 3)" :key="tag" :title="tag">{{ tag }}</span>
            <span v-if="!tags.length" class="project-overview-card__no-tags">{{ tr('未分类') }}</span>
          </div>
        </div>
      </div>

      <div :id="`project-progress-${project.id}`" class="project-overview-card__progress" :title="tr('整集内全部有效分镜的当前视频均生成成功，才计为完成一集；章节总数不是制作目标。')">
        <div class="project-overview-card__progress-heading">
          <span><Clapperboard :size="14" aria-hidden="true" />{{ tr('视频制作') }}</span>
          <strong>{{ tr('已完成 {p0} 集', { p0: projectNumber(project.production.completed_episode_count) }) }}</strong>
        </div>
        <div class="project-overview-card__progress-detail">
          <span v-if="project.production.latest_episode_number !== null">{{ tr('最近完成：第 {p0} 集', { p0: project.production.latest_episode_number }) }}</span>
          <span v-else-if="project.production.shot_count">{{ tr('{p0} / {p1} 个分镜视频就绪', { p0: project.production.completed_shot_count, p1: project.production.shot_count }) }}</span>
          <span v-else>{{ tr('尚未开始视频制作') }}</span>
          <time :datetime="project.production.latest_activity_at" :title="tr('最近更新：{p0}', { p0: project.production.latest_activity_at })">{{ projectDate(project.production.latest_activity_at) }}</time>
        </div>
      </div>

      <dl :id="`project-stats-${project.id}`" class="project-overview-card__stats">
        <div><dt><BookOpen :size="13" aria-hidden="true" />{{ tr('章节数') }}</dt><dd>{{ projectNumber(project.production.chapter_count) }}</dd></div>
        <div :title="tr('当前绑定的图片、声音和视频，项目内按文件去重；已移除的素材不计入。')"><dt><Image :size="13" aria-hidden="true" />{{ tr('资产数') }}</dt><dd>{{ projectNumber(project.production.asset_count) }}</dd></div>
        <div :title="runtime.incomplete ? tr('另有 {p0} 个视频的实际时长待确认，未使用剧本预计时长。', { p0: project.production.unknown_duration_count }) : tr('当前成功视频已确认的实际时长，不重复累计历史版本。')"><dt><Clock3 :size="13" aria-hidden="true" />{{ tr('成片时长') }}</dt><dd :class="{ 'is-pending': runtime.incomplete && !runtime.unit }">{{ runtime.value }}<small v-if="runtime.unit">{{ runtime.unit }}</small></dd></div>
      </dl>
    </RouterLink>

    <div v-if="editable" ref="actions" class="project-overview-card__actions" :class="{ 'is-open': menuOpen }" @keydown.esc.stop.prevent="closeMenu(true)" @focusout="event => { if (!actions?.contains(event.relatedTarget as Node)) closeMenu() }">
      <AppButton ref="trigger" variant="ghost" icon-only size="sm" :aria-label="tr('项目「{p0}」更多操作', { p0: project.name })" aria-haspopup="menu" :aria-expanded="menuOpen" :disabled="deleting" @click.stop="openMenu" @keydown.down.prevent="openMenu">
        <Ellipsis :size="18" aria-hidden="true" />
      </AppButton>
      <div v-if="menuOpen" class="project-overview-card__menu" role="menu" :aria-label="tr('项目操作')" @keydown.up.prevent="deleteButton?.focus()" @keydown.down.prevent="deleteButton?.focus()">
        <button ref="deleteButton" type="button" role="menuitem" @click.stop="remove"><Trash2 :size="14" aria-hidden="true" />{{ tr('删除项目') }}</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.project-overview-card { position: relative; min-width: 0; border: 1px solid var(--app-border); border-radius: 18px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 3px 14px rgb(35 39 55 / 3%); transition: border-color 160ms ease, box-shadow 160ms ease; }
.project-overview-card:hover, .project-overview-card:focus-within { border-color: var(--app-border-strong); box-shadow: 0 8px 24px rgb(35 39 55 / 7%); }
.project-overview-card__link { display: flex; height: 100%; min-width: 0; flex-direction: column; padding: 20px; border-radius: inherit; color: inherit; }
.project-overview-card__link:focus-visible { outline: 3px solid var(--app-accent); outline-offset: 3px; }
.project-overview-card__identity { display: grid; min-height: 126px; grid-template-columns: 84px minmax(0, 1fr); align-items: start; gap: 16px; }
.project-overview-card__cover { display: grid; width: 84px; height: 120px; overflow: hidden; place-items: center; border-radius: 10px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.project-overview-card__cover img { width: 100%; height: 100%; object-fit: cover; }
.project-overview-card__copy { min-width: 0; }
.project-overview-card__status { display: inline-flex; max-width: calc(100% - 23px); min-height: 23px; align-items: center; padding: 2px 7px; border-radius: 6px; color: var(--app-text-secondary); background: var(--app-surface-muted); font-size: 12px; font-weight: 600; line-height: 1.35; }
.project-overview-card__status.is-in_progress { color: var(--app-accent); background: var(--app-accent-soft); }
.project-overview-card__status.is-ready { color: var(--creation-success); background: color-mix(in srgb, var(--creation-success) 10%, var(--app-surface)); }
.project-overview-card h2 { display: -webkit-box; min-height: 44px; overflow: hidden; margin: 9px 0 5px; font-size: 16px; font-weight: 650; line-height: 22px; overflow-wrap: anywhere; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.project-overview-card__metadata { overflow: hidden; margin: 0; color: var(--app-text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.project-overview-card__tags { display: flex; min-height: 22px; align-items: center; gap: 5px; margin-top: 9px; overflow: hidden; }
.project-overview-card__tags > span { overflow: hidden; max-width: 8em; padding: 2px 6px; border-radius: 5px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.project-overview-card__tags > .project-overview-card__no-tags { color: var(--app-text-secondary); background: var(--app-surface-muted); }
.project-overview-card__progress { margin-top: 19px; }
.project-overview-card__progress-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px; font-size: 12px; }
.project-overview-card__progress-heading > span { display: inline-flex; align-items: center; gap: 6px; color: var(--app-text-secondary); }
.project-overview-card__progress-heading strong { color: var(--app-accent); font-size: 13px; font-weight: 650; }
.project-overview-card__progress-detail { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-top: 8px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.5; }
.project-overview-card__progress-detail time { flex: 0 0 auto; font-size: 11px; }
.project-overview-card__stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; margin: 17px 0 0; padding-top: 15px; border-top: 1px solid var(--app-border); }
.project-overview-card__stats dt { display: flex; align-items: center; gap: 5px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.4; }
.project-overview-card__stats dt svg { flex: 0 0 auto; color: var(--app-text-muted); }
.project-overview-card__stats dd { margin: 6px 0 0; font-size: 17px; font-weight: 650; line-height: 1.3; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.project-overview-card__stats small { margin-left: 3px; font-size: 11px; font-weight: 500; }
.project-overview-card__stats dd.is-pending { font-size: 13px; font-weight: 500; line-height: 22px; }
.project-overview-card__actions { position: absolute; top: 13px; right: 12px; z-index: 2; }
.project-overview-card__actions > .app-button { width: 32px; min-height: 32px; color: var(--app-text-secondary); opacity: 0; transition: opacity 140ms ease, background-color 140ms ease; }
.project-overview-card:hover .project-overview-card__actions > .app-button, .project-overview-card:focus-within .project-overview-card__actions > .app-button, .project-overview-card__actions.is-open > .app-button { opacity: 1; }
.project-overview-card__menu { position: absolute; top: 36px; right: 0; width: 140px; padding: 5px; border: 1px solid var(--app-border); border-radius: 10px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.project-overview-card__menu button { display: flex; width: 100%; min-height: 38px; align-items: center; gap: 9px; padding: 0 10px; border: 0; border-radius: 6px; color: var(--creation-danger); background: transparent; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.project-overview-card__menu button:hover, .project-overview-card__menu button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; background: var(--app-surface-muted); }
.is-deleting { opacity: .6; pointer-events: none; }
@media (hover: none) { .project-overview-card__actions > .app-button { opacity: 1; min-height: 40px; width: 40px; } }
@media (prefers-reduced-motion: reduce) { .project-overview-card, .project-overview-card__actions > .app-button { transition: none; } }
</style>
