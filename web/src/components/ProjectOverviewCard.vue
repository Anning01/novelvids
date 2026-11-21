<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { BookOpen, Clapperboard, Clock3, Coins, Download, Ellipsis, Film, Image, Sparkles, Trash2 } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { fallbackImage } from '@/shared/mediaFallback'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import ProjectCover from '@/components/ProjectCover.vue'
import { money } from '@/features/billing/recordDisplay'
import { projectDate, projectKindLabel, projectNumber, projectRuntime, projectSourceLabel } from '@/shared/projectOverview'
import { projectEntryRoute, projectSource, readShortDramaSettings } from '@/shared/shortDramaProject'
import type { ProjectOverviewItem } from '@/types'

const props = defineProps<{ project: ProjectOverviewItem; editable: boolean; exportOnly?: boolean; deleting?: boolean; exporting?: boolean; cost?: number; costState?: 'loading' | 'ready' | 'error' | 'pending'; costHint?: string }>()
const emit = defineEmits<{ download: [project: ProjectOverviewItem]; cancelDownload: [projectId: number]; remove: [project: ProjectOverviewItem] }>()
const menuOpen = ref(false)
const actions = ref<HTMLElement | null>(null)
const trigger = ref<InstanceType<typeof AppButton> | null>(null)
const exportButton = ref<HTMLButtonElement | null>(null)
const deleteButton = ref<HTMLButtonElement | null>(null)
const runtime = computed(() => projectRuntime(props.project.production.finished_seconds ?? 0, props.project.production.unknown_finished_duration_count ?? 0))
const settings = computed(() => readShortDramaSettings(props.project))
const source = computed(() => projectSource(props.project))
const clipPreview = computed(() => props.project.clip?.thumbnail || props.project.clip?.preview || props.project.cover_thumbnail || props.project.cover)
const clipFormat = computed(() => props.project.clip?.kind && ({ gif: tr('GIF 动图'), image: tr('图片'), video: tr('视频') })[props.project.clip.kind])
const metadata = computed(() => [source.value === 'series' ? projectKindLabel(props.project) : null, settings.value.aspectRatio, settings.value.resolution?.toUpperCase()].filter(Boolean).join(' · '))
const stateLabel = computed(() => ({ not_started: tr('未开始'), in_progress: tr('制作中'), ready: tr('已有作品') }[props.project.production.state]))
const tags = computed(() => props.project.tags?.filter(Boolean) ?? [])

async function openMenu() {
  menuOpen.value = !menuOpen.value
  if (menuOpen.value) {
    await nextTick()
    exportButton.value?.focus()
  }
}

function closeMenu(restoreFocus = false) {
  menuOpen.value = false
  if (restoreFocus) (trigger.value?.$el as HTMLButtonElement | undefined)?.focus()
}

function outside(event: PointerEvent) {
  if (event.target instanceof Node && !actions.value?.contains(event.target)) closeMenu()
}

function moveFocus() {
  const target = document.activeElement === exportButton.value ? deleteButton.value : exportButton.value
  if (!target?.disabled) target?.focus()
}

function download() {
  closeMenu(true)
  emit('download', props.project)
}

function exportAction() {
  if (!props.exporting) { download(); return }
  closeMenu(true)
  emit('cancelDownload', props.project.id)
}

function remove() {
  closeMenu(true)
  emit('remove', props.project)
}

onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <article class="project-overview-card" :class="{ 'is-deleting': deleting, 'is-clip': source === 'clip', 'is-remake': source === 'remake' }" :aria-labelledby="`project-title-${project.id}`">
    <component :is="exportOnly ? 'div' : 'RouterLink'" :to="exportOnly ? undefined : projectEntryRoute(project)" class="project-overview-card__link" :aria-label="exportOnly ? undefined : tr('打开项目：{p0}', { p0: project.name })" :aria-describedby="`project-progress-${project.id} project-stats-${project.id}`">
      <template v-if="source === 'clip'">
        <div class="clip-preview">
          <Sparkles :size="30" aria-hidden="true" />
          <img v-if="clipPreview" :key="clipPreview" :src="mediaUrl(clipPreview)" alt="" loading="lazy" decoding="async"
            @error="fallbackImage($event, mediaUrl(project.clip?.preview || project.cover))" />
          <span class="project-overview-card__source is-clip"><Sparkles :size="13" aria-hidden="true" />{{ projectSourceLabel(source) }}</span>
        </div>
        <div class="clip-caption">
          <p class="clip-specs">
            <strong v-if="clipFormat">{{ clipFormat }}</strong>
            <span>{{ [settings.aspectRatio, project.clip?.resolution || settings.resolution?.toUpperCase()].filter(Boolean).join(' · ') }}</span>
          </p>
          <h2 :id="`project-title-${project.id}`" :title="project.name">{{ project.name }}</h2>
          <div :id="`project-progress-${project.id}`" class="clip-activity"><span>{{ project.production.state === 'ready' ? tr('已有结果') : stateLabel }}</span>
            <time :datetime="project.production.latest_activity_at" :title="tr('最近更新')">{{ projectDate(project.production.latest_activity_at) }}</time>
          </div>
        </div>
      </template>
      <template v-else-if="source === 'remake'">
        <header class="remake-heading">
          <span class="project-overview-card__source is-remake"><Film :size="14" aria-hidden="true" />{{ projectSourceLabel(source) }}</span>
          <h2 :id="`project-title-${project.id}`" :title="project.name">{{ project.name }}</h2>
          <p class="project-overview-card__metadata">{{ [stateLabel, metadata].filter(Boolean).join(' · ') }}</p>
        </header>
        <dl :id="`project-progress-${project.id}`" class="remake-stages">
          <div><dt>{{ tr('原片拆解') }}</dt><dd>{{ project.remake ? `${project.remake.analyzed_count} / ${project.remake.source_count}` : '—' }}</dd>
            <progress v-if="project.remake?.source_count" :value="project.remake.analyzed_count" :max="project.remake.source_count" :aria-label="tr('原片拆解')" /></div>
          <div><dt>{{ tr('分镜视频') }}</dt><dd>{{ project.production.completed_shot_count }} / {{ project.production.shot_count }}</dd>
            <progress v-if="project.production.shot_count" :value="project.production.completed_shot_count" :max="project.production.shot_count" :aria-label="tr('分镜视频')" /></div>
        </dl>
        <div class="clip-activity"><span>{{ tr('最近更新') }}</span><time :datetime="project.production.latest_activity_at">{{ projectDate(project.production.latest_activity_at) }}</time></div>
      </template>
      <div v-else class="project-overview-card__identity">
        <ProjectCover :max-width="108" class="project-overview-card__cover" :source="project.cover_thumbnail || project.cover" :original="project.cover" :aspect-ratio="settings.aspectRatio" :title="project.name" :seed="project.id ?? project.name" :alt="project.name" />
        <div class="project-overview-card__copy">
          <span class="project-overview-card__source" :class="`is-${source}`">
            <Clapperboard :size="13" aria-hidden="true" />{{ projectSourceLabel(source) }}
          </span>
          <h2 :id="`project-title-${project.id}`" :title="project.name">{{ project.name }}</h2>
          <p v-if="metadata" class="project-overview-card__metadata" :title="metadata">{{ metadata }}</p>
          <div class="project-overview-card__tags" :title="tags.join(' · ')">
            <span class="project-overview-card__status" :class="`is-${project.production.state}`">{{ stateLabel }}</span>
            <span v-for="tag in tags.slice(0, 3)" :key="tag" :title="tag">{{ tag }}</span>
          </div>
        </div>
      </div>

      <div v-if="source === 'series'" :id="`project-progress-${project.id}`" class="project-overview-card__progress" :title="tr('每集合成成功后计为完成，同一集的多个合成版本只统计一次。')">
        <div class="project-overview-card__progress-heading">
          <span><Clapperboard :size="14" aria-hidden="true" />{{ tr('视频制作') }}</span>
          <strong>{{ tr('已完成 {p0} 集', { p0: projectNumber(project.production.completed_episode_count) }) }}</strong>
        </div>
        <div class="project-overview-card__progress-detail">
          <span v-if="project.production.latest_episode_number !== null">{{ tr('最近完成：第 {p0} 集', { p0: project.production.latest_episode_number }) }}</span>
          <span v-else-if="project.production.pending_composition_count">{{ tr('待合成 {p0} 集', {p0:project.production.pending_composition_count}) }}</span>
          <span v-else-if="project.production.shot_count">{{ tr('{p0} / {p1} 个分镜视频就绪', { p0: project.production.completed_shot_count, p1: project.production.shot_count }) }}</span>
          <span v-else>{{ tr('尚未开始视频制作') }}</span>
          <time :datetime="project.production.latest_activity_at" :title="tr('最近更新：{p0}', { p0: project.production.latest_activity_at })">{{ projectDate(project.production.latest_activity_at) }}</time>
        </div>
      </div>

      <dl :id="`project-stats-${project.id}`" class="project-overview-card__stats">
        <template v-if="source === 'series'">
          <div><dt><BookOpen :size="13" aria-hidden="true" />{{ tr('章节数') }}</dt><dd>{{ projectNumber(project.production.chapter_count) }}</dd></div>
          <div :title="tr('当前绑定的图片、声音和视频，项目内按文件去重；已移除的素材不计入。')"><dt><Image :size="13" aria-hidden="true" />{{ tr('资产数') }}</dt><dd>{{ projectNumber(project.production.asset_count) }}</dd></div>
          <div :title="runtime.incomplete ? tr('另有 {p0} 个视频的实际时长待确认，未使用剧本预计时长。', { p0: project.production.unknown_finished_duration_count ?? 0 }) : tr('每集按最新成功合成版本的实际时长统计。')"><dt><Clock3 :size="13" aria-hidden="true" />{{ tr('成片时长') }}</dt><dd :class="{ 'is-pending': runtime.incomplete && !runtime.unit }">{{ runtime.value }}<small v-if="runtime.unit">{{ runtime.unit }}</small></dd></div>
        </template>
        <div v-if="costState" class="project-overview-card__cost" :title="[costHint, tr('按成本页面的已入账费用汇总，包含历史生成及画质增强；未入账用量不计入。')].filter(Boolean).join(' ')" :aria-busy="costState === 'loading'"><dt><Coins :size="13" aria-hidden="true" />{{ tr('已花费') }}</dt><dd :class="{ 'is-pending': costState !== 'ready' }">{{ costState === 'ready' ? money(cost ?? 0) : costState === 'loading' ? tr('正在读取…') : costState === 'pending' ? tr('待结算') : tr('读取失败') }}</dd></div>
      </dl>
    </component>

    <footer v-if="!exportOnly && project.production.completed_episode_count" class="project-finished-link"><RouterLink :to="`/finished-library/${project.id}`">{{ tr('查看作品') }}<template v-if="source === 'series'"> · {{ project.production.completed_episode_count }} {{ tr('集') }}</template></RouterLink></footer>
    <div v-if="editable && exportOnly" class="project-overview-card__export">
      <span v-if="exporting" role="status">{{ tr('正在导出') }}</span>
      <AppButton variant="secondary" size="sm" @click="exportAction"><Download v-if="!exporting" :size="14" aria-hidden="true" />{{ exporting ? tr('取消导出') : tr('导出作品') }}</AppButton>
    </div>
    <div v-if="editable && !exportOnly" ref="actions" class="project-overview-card__actions" :class="{ 'is-open': menuOpen }" @keydown.esc.stop.prevent="closeMenu(true)" @focusout="event => { if (!actions?.contains(event.relatedTarget as Node)) closeMenu() }">
      <AppButton ref="trigger" variant="ghost" icon-only size="sm" :aria-label="tr('项目「{p0}」更多操作', { p0: project.name })" aria-haspopup="menu" :aria-expanded="menuOpen" :disabled="deleting" @click.stop="openMenu" @keydown.down.prevent="openMenu">
        <Ellipsis :size="18" aria-hidden="true" />
      </AppButton>
      <span v-if="exporting" class="project-overview-card__export-status" role="status">{{ tr('正在导出') }}</span>
      <div v-if="menuOpen" class="project-overview-card__menu" role="menu" :aria-label="tr('项目操作')" @keydown.up.prevent="moveFocus" @keydown.down.prevent="moveFocus">
        <button ref="exportButton" type="button" role="menuitem" @click.stop="exportAction"><Download :size="14" aria-hidden="true" />{{ exporting ? tr('取消导出') : tr('导出作品') }}</button>
        <button ref="deleteButton" class="remove-project" type="button" role="menuitem" :disabled="exporting" @click.stop="remove"><Trash2 :size="14" aria-hidden="true" />{{ tr('删除项目') }}</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.project-overview-card.is-remake { align-self: start; }
.remake-heading { padding-right: 22px; }
.project-overview-card .remake-heading h2 { min-height: 0; }
.project-overview-card__source.is-remake { color: var(--creation-warning); background: color-mix(in srgb,var(--creation-warning) 12%,var(--app-surface)); }
.remake-stages { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; padding: 14px; margin: 16px 0 12px; border-radius: 9px; background: var(--app-surface-muted); }
.remake-stages dt { color: var(--app-text-secondary); font-size: 12px; }
.remake-stages dd { margin: 4px 0; font-weight: 650; font-variant-numeric: tabular-nums; }
.remake-stages progress { display: block; width: 100%; height: 6px; accent-color: var(--creation-warning); }
.is-remake .project-overview-card__stats { margin-top: 0; border: 0; padding-top: 0; }
.is-clip.project-overview-card { align-self: start; overflow: visible; }
.is-clip .project-overview-card__link { padding: 0; }
.clip-preview { position: relative; display: grid; width: 100%; aspect-ratio: 16 / 9; overflow: hidden; place-items: center; border-radius: 17px 17px 0 0; color: var(--creation-success); background: color-mix(in srgb,var(--creation-success) 10%,var(--app-surface-muted)); }
.clip-preview img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.clip-preview .project-overview-card__source { position: absolute; left: 12px; bottom: 10px; color: var(--creation-success); background: var(--app-surface); }
.clip-caption { padding: 15px 16px 12px; }
.clip-specs,.clip-activity { display: flex; align-items: center; gap: 8px; margin: 0; color: var(--app-text-secondary); font-size: 12px; }
.clip-specs strong { color: var(--creation-success); }
.clip-activity { justify-content: space-between; }
.project-overview-card.is-clip h2 { min-height: 0; margin: 6px 0 12px; }
.is-clip .project-overview-card__stats { margin: 0 16px; padding: 0; border: 0; }
.is-clip .project-overview-card__cost { margin: 0; padding: 10px 0 14px; }
.is-clip .project-overview-card__actions > .app-button { background: var(--app-surface); }
.project-finished-link{padding:10px 20px 15px;font-size:12px;color:var(--app-accent)}
.project-overview-card__export { display:flex; align-items:center; justify-content:flex-end; gap:10px; padding:0 20px 15px; color:var(--app-text-secondary); font-size:12px; }
.project-overview-card { display:flex;flex-direction:column;position: relative; min-width: 0; border: 1px solid var(--app-border); border-radius: 18px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 3px 14px rgb(35 39 55 / 3%); transition: border-color 160ms ease, box-shadow 160ms ease; }
.project-overview-card:hover, .project-overview-card:focus-within { border-color: var(--app-border-strong); box-shadow: 0 8px 24px rgb(35 39 55 / 7%); }
.project-overview-card__link { display: flex; flex:1; min-width: 0; flex-direction: column; padding: 20px; border-radius: inherit; color: inherit; }
.project-overview-card__link:focus-visible { outline: 3px solid var(--app-accent); outline-offset: 3px; }
.project-overview-card__identity { display: grid; min-height: 126px; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 12px; }
.project-overview-card__copy { min-width: 0; }
.project-overview-card__source { display: inline-flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 5px; font-size: 12px; font-weight: 650; line-height: 1.4; }
.project-overview-card__source svg { flex: none; }
.project-overview-card__source.is-series { color: var(--app-accent); background: var(--app-accent-soft); }
.project-overview-card__source.is-clip { color: var(--creation-success); background: color-mix(in srgb, var(--creation-success) 12%, var(--app-surface)); }
.project-overview-card__status { display: inline-flex; max-width: 100%; min-height: 23px; white-space: nowrap; align-items: center; padding: 2px 7px; border-radius: 6px; color: var(--app-text-secondary); background: var(--app-surface-muted); font-size: 12px; font-weight: 600; line-height: 1.35; }
.project-overview-card__status.is-in_progress { color: var(--app-accent); background: var(--app-accent-soft); }
.project-overview-card__status.is-ready { color: var(--creation-success); background: color-mix(in srgb, var(--creation-success) 10%, var(--app-surface)); }
.project-overview-card h2 { display: -webkit-box; min-height: 44px; overflow: hidden; margin: 9px 0 5px; font-size: 16px; font-weight: 650; line-height: 22px; overflow-wrap: anywhere; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.project-overview-card__metadata { overflow: hidden; margin: 0; color: var(--app-text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.project-overview-card__tags { display: flex; min-height: 22px; align-items: center; gap: 5px; margin-top: 9px; overflow: hidden; }
.project-overview-card__tags > span:not(.project-overview-card__status) { overflow: hidden; max-width: 8em; padding: 2px 6px; border-radius: 5px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.project-overview-card__tags > .project-overview-card__status { flex: none; }
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
.project-overview-card__cost { display: flex; grid-column: 1 / -1; align-items: baseline; justify-content: space-between; gap: 12px; margin-top: 3px; padding-top: 12px; border-top: 1px solid var(--app-border); }
.project-overview-card__cost dd { margin: 0; color: var(--app-accent); }
.project-overview-card__actions { position: absolute; top: 13px; right: 12px; z-index: 2; }
.project-overview-card__actions > .app-button { width: 32px; min-height: 32px; color: var(--app-text-secondary); opacity: 0; transition: opacity 140ms ease, background-color 140ms ease; }
.project-overview-card:hover .project-overview-card__actions > .app-button, .project-overview-card:focus-within .project-overview-card__actions > .app-button, .project-overview-card__actions.is-open > .app-button { opacity: 1; }
.project-overview-card__menu { position: absolute; top: 36px; right: 0; width: 140px; padding: 5px; border: 1px solid var(--app-border); border-radius: 10px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.project-overview-card__menu button { display: flex; width: 100%; min-height: 38px; align-items: center; gap: 9px; padding: 0 10px; border: 0; border-radius: 6px; color: var(--app-text); background: transparent; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.project-overview-card__export-status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.project-overview-card__menu button:disabled { opacity: .45; cursor: not-allowed; }
.project-overview-card__menu .remove-project { color: var(--creation-danger); }
.project-overview-card__menu button:hover, .project-overview-card__menu button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; background: var(--app-surface-muted); }
.is-deleting { opacity: .6; pointer-events: none; }
@media (hover: none) { .project-overview-card__actions > .app-button { opacity: 1; min-height: 40px; width: 40px; } }
@media (prefers-reduced-motion: reduce) { .project-overview-card, .project-overview-card__actions > .app-button { transition: none; } }
</style>
