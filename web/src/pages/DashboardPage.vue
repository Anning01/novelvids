<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, BookOpen, Clock3, FolderOpen, Image, Info, Plus, Search, X } from 'lucide-vue-next'
import { api } from '@/api'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppSelect from '@/components/AppSelect.vue'
import ProjectOverviewCard from '@/components/ProjectOverviewCard.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { projectKind, projectNumber, projectRuntime } from '@/shared/projectOverview'
import type { ProjectOverview, ProjectOverviewItem } from '@/types'

const auth = useAuthStore()
const overview = ref<ProjectOverview | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const search = ref('')
const typeFilter = ref('all')
const stateFilter = ref('all')
const sort = ref('updated')
const page = ref(1)
const pageSize = ref(12)
const deletingIds = ref<Set<number>>(new Set())
let requestRevision = 0
const editable = computed(() => auth.enabled === false || ['admin', 'creator', 'super'].includes(auth.role ?? ''))
const filtered = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  return (overview.value?.items ?? []).filter(project => (
    (!keyword || project.name.toLocaleLowerCase().includes(keyword))
    && (typeFilter.value === 'all' || projectKind(project) === typeFilter.value)
    && (stateFilter.value === 'all' || project.production.state === stateFilter.value)
  )).sort((left, right) => {
    if (sort.value === 'name') return left.name.localeCompare(right.name)
    const leftDate = sort.value === 'created' ? left.created_at : left.production.latest_activity_at
    const rightDate = sort.value === 'created' ? right.created_at : right.production.latest_activity_at
    return rightDate.localeCompare(leftDate) || right.id - left.id
  })
})
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const hasFilters = computed(() => Boolean(search.value.trim()) || typeFilter.value !== 'all' || stateFilter.value !== 'all')
const runtime = computed(() => projectRuntime(overview.value?.summary.video_seconds ?? 0, overview.value?.summary.unknown_duration_count ?? 0))
const stats = computed(() => [
  { key: 'projects', label: tr('项目总数'), value: projectNumber(overview.value?.summary.project_count ?? 0), unit: '', hint: tr('个创作项目'), icon: FolderOpen },
  { key: 'chapters', label: tr('累计章节'), value: projectNumber(overview.value?.summary.chapter_count ?? 0), unit: '', hint: tr('已有文字章节'), icon: BookOpen },
  { key: 'assets', label: tr('累计资产'), value: projectNumber(overview.value?.summary.asset_count ?? 0), unit: '', hint: tr('项目内文件去重'), icon: Image },
  { key: 'runtime', label: tr('累计成片时长'), value: runtime.value.value, unit: runtime.value.unit, hint: tr('已确认的视频时长'), icon: Clock3 },
])
const typeOptions = computed(() => [
  { value: 'all', label: tr('全部类型') }, { value: 'agent', label: tr('AI 创作') },
  { value: 'manual', label: tr('手动创作') }, { value: 'remake', label: tr('视频重制') },
  { value: 'script', label: tr('小说 / 剧本') },
])
const stateOptions = computed(() => [
  { value: 'all', label: tr('全部状态') }, { value: 'not_started', label: tr('未开始') },
  { value: 'in_progress', label: tr('制作中') }, { value: 'ready', label: tr('视频就绪') },
])
const sortOptions = computed(() => [
  { value: 'updated', label: tr('最近更新优先') }, { value: 'created', label: tr('最近创建优先') }, { value: 'name', label: tr('按项目名称') },
])

async function load() {
  const revision = ++requestRevision
  loading.value = true
  errorMessage.value = ''
  try {
    const result = (await api.projectOverview()).data
    if (revision === requestRevision) overview.value = result
  } catch (error) {
    if (revision === requestRevision) errorMessage.value = (error as Error).message
  } finally {
    if (revision === requestRevision) loading.value = false
  }
}

function resetFilters() {
  search.value = ''
  typeFilter.value = 'all'
  stateFilter.value = 'all'
}

async function remove(project: ProjectOverviewItem) {
  if (deletingIds.value.has(project.id) || !editable.value) return
  if (!await appConfirm({
    title: tr('删除项目「{p0}」？', { p0: project.name }),
    get message() { return tr('项目、章节及相关创作数据将被删除，且无法恢复。') },
    get confirmLabel() { return tr('删除项目') },
    tone: 'danger',
  })) return
  deletingIds.value = new Set([...deletingIds.value, project.id])
  try {
    await api.deleteNovel(project.id)
    overview.value = null
    await load()
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    deletingIds.value = new Set([...deletingIds.value].filter(id => id !== project.id))
  }
}

watch([search, typeFilter, stateFilter, sort, pageSize], () => { page.value = 1 })
watch(() => filtered.value.length, total => { page.value = Math.max(1, Math.min(page.value, Math.ceil(total / pageSize.value))) })
watch(() => auth.activeTeamId, () => { overview.value = null; void load() })
function refreshOnFocus() { if (!loading.value) void load() }
onMounted(() => { void load(); window.addEventListener('focus', refreshOnFocus) })
onBeforeUnmount(() => { ++requestRevision; window.removeEventListener('focus', refreshOnFocus) })
</script>

<template>
  <main class="projects-page">
    <header class="projects-page__header">
      <h1>{{ tr('我的项目') }}</h1>
      <RouterLink v-if="editable" to="/create/short-drama" class="projects-page__create"><Plus :size="18" aria-hidden="true" />{{ tr('新建项目') }}</RouterLink>
    </header>

    <div v-if="loading && !overview" class="projects-page__loading" role="status">
      <div class="projects-page__summary-skeleton"><span v-for="n in 4" :key="n" /></div>
      <p>{{ tr('正在加载项目…') }}</p>
    </div>
    <template v-else-if="overview">
      <section class="projects-summary" :aria-label="tr('全部项目统计')" :aria-busy="loading">
        <article v-for="stat in stats" :key="stat.key" class="projects-summary__item" :class="`is-${stat.key}`">
          <span class="projects-summary__icon"><component :is="stat.icon" :size="23" :stroke-width="1.7" aria-hidden="true" /></span>
          <div><h2>{{ stat.label }}</h2><p :class="{ 'is-pending': stat.key === 'runtime' && runtime.incomplete && !runtime.unit }">{{ stat.value }}<small v-if="stat.unit">{{ stat.unit }}</small></p><span>{{ stat.hint }}</span></div>
        </article>
      </section>
      <p v-if="overview.summary.unknown_duration_count" class="projects-page__duration-note"><Info :size="13" aria-hidden="true" />{{ tr('另有 {p0} 个视频的实际时长待确认，未使用剧本预计时长。', { p0: overview.summary.unknown_duration_count }) }}</p>

      <section class="projects-library" :aria-label="tr('项目列表')">
        <div class="projects-library__toolbar">
          <div class="projects-library__heading"><h2>{{ tr('全部项目') }}</h2><span role="status" aria-live="polite">{{ tr('共 {p0} 个项目', { p0: projectNumber(filtered.length) }) }}</span></div>
          <div class="projects-library__filters">
            <label class="projects-search"><Search :size="17" aria-hidden="true" /><span class="projects-sr-only">{{ tr('搜索项目名称') }}</span><input v-model="search" type="search" :placeholder="tr('搜索项目名称')"><button v-if="search" type="button" :aria-label="tr('清空搜索')" @click="search = ''"><X :size="14" aria-hidden="true" /></button></label>
            <AppSelect v-model="typeFilter" :options="typeOptions" :ariaLabel="tr('项目类型')" />
            <AppSelect v-model="sort" :options="sortOptions" :ariaLabel="tr('项目排序')" />
            <AppSelect v-model="stateFilter" :options="stateOptions" :ariaLabel="tr('创作状态')" />
          </div>
        </div>

        <div v-if="visible.length" class="projects-library__grid" :aria-busy="loading">
          <ProjectOverviewCard v-for="project in visible" :key="project.id" :project="project" :editable="editable" :deleting="deletingIds.has(project.id)" @remove="remove" />
        </div>
        <div v-else class="projects-page__empty">
          <span class="projects-page__empty-icon"><Search v-if="hasFilters" :size="28" aria-hidden="true" /><BookOpen v-else :size="28" aria-hidden="true" /></span>
          <h3>{{ hasFilters ? tr('没有找到匹配的项目') : tr('暂无项目') }}</h3>
          <p>{{ hasFilters ? tr('试试其他关键词，或调整筛选条件。') : tr('从一个故事开始，逐步完成你的第一部作品。') }}</p>
          <AppButton v-if="hasFilters" variant="soft" @click="resetFilters">{{ tr('清除筛选') }}</AppButton>
          <RouterLink v-else-if="editable" to="/create/short-drama" class="projects-page__empty-link">{{ tr('前往创作') }}<ArrowRight :size="15" aria-hidden="true" /></RouterLink>
        </div>
        <AppPagination v-if="filtered.length > 12" :page="page" :page-size="pageSize" :total="filtered.length" :page-size-options="[12, 24, 48]" @page-change="page = $event" @size-change="pageSize = $event" />
      </section>
    </template>
    <div v-if="errorMessage" class="projects-page__error" role="alert"><h2>{{ tr('项目加载失败') }}</h2><p>{{ errorMessage }}</p><AppButton variant="secondary" :loading="loading" @click="load">{{ tr('重新加载') }}</AppButton></div>
  </main>
</template>

<style scoped>
.projects-page { container: projects / inline-size; min-height: 100%; padding: 32px 30px 60px; color: var(--app-text); background: var(--app-canvas); }
.projects-page__header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 28px; }
.projects-page h1 { margin: 0; font-size: clamp(26px, 2.6vw, 34px); font-weight: 700; line-height: 1.25; letter-spacing: -.035em; }
.projects-page__create { display: inline-flex; min-height: 42px; flex: 0 0 auto; align-items: center; gap: 7px; padding: 0 17px; border-radius: 11px; color: #fff; background: #5b5cf6; box-shadow: 0 5px 14px rgb(91 92 246 / 16%); font-size: 13px; font-weight: 600; transition: background-color 150ms ease; }
.projects-page__create:hover { background: #4d4ee5; }
.projects-page__create:focus-visible, .projects-page__empty-link:focus-visible { outline: 3px solid var(--app-accent); outline-offset: 3px; }
.projects-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.projects-summary__item { display: flex; min-width: 0; min-height: 119px; align-items: center; gap: 16px; padding: 21px; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); box-shadow: 0 2px 10px rgb(35 39 55 / 2%); }
.projects-summary__icon { display: grid; width: 48px; height: 48px; flex: 0 0 auto; place-items: center; border-radius: 13px; color: var(--app-accent); background: var(--app-accent-soft); }
.projects-summary__item.is-chapters .projects-summary__icon { color: #2878c2; background: color-mix(in srgb, #4095e5 11%, var(--app-surface)); }
.projects-summary__item.is-assets .projects-summary__icon { color: var(--creation-success); background: color-mix(in srgb, var(--creation-success) 10%, var(--app-surface)); }
.projects-summary__item.is-runtime .projects-summary__icon { color: var(--creation-warning); background: color-mix(in srgb, var(--creation-warning) 10%, var(--app-surface)); }
.projects-summary__item > div { min-width: 0; }
.projects-summary h2 { margin: 0; color: var(--app-text-secondary); font-size: 12px; font-weight: 500; line-height: 1.4; }
.projects-summary p { margin: 7px 0 4px; font-size: clamp(23px, 2.4vw, 30px); font-weight: 700; line-height: 1.1; letter-spacing: -.03em; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.projects-summary small { margin-left: 4px; font-size: 13px; font-weight: 600; letter-spacing: 0; }
.projects-summary p.is-pending { font-size: clamp(16px, 1.6vw, 20px); line-height: 1.4; letter-spacing: 0; }
.projects-summary__item > div > span { color: var(--app-text-secondary); font-size: 11px; }
.projects-page__duration-note { display: flex; align-items: start; gap: 6px; margin: 12px 0 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.5; }
.projects-page__duration-note svg { flex: 0 0 auto; margin-top: 2px; }
.projects-library { margin-top: 32px; }
.projects-library__toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 20px; }
.projects-library__heading { display: flex; flex: 0 0 auto; align-items: baseline; gap: 12px; }
.projects-library__heading h2 { margin: 0; font-size: 19px; font-weight: 650; line-height: 1.4; }
.projects-library__heading > span { color: var(--app-text-secondary); font-size: 12px; }
.projects-library__filters { display: flex; flex: 0 1 720px; align-items: center; gap: 10px; }
.projects-search { display: flex; min-width: 150px; height: 40px; flex: 1 1 240px; align-items: center; gap: 9px; padding: 0 12px; border: 1px solid var(--app-border); border-radius: 10px; color: var(--app-text-secondary); background: var(--app-surface); }
.projects-search:focus-within { border-color: var(--app-accent); box-shadow: 0 0 0 2px var(--app-accent-soft); }
.projects-search svg { flex: 0 0 auto; }
.projects-search input { width: 100%; min-width: 0; padding: 0; border: 0; outline: none; color: var(--app-text); background: transparent; font: inherit; font-size: 12px; }
.projects-search input::-webkit-search-cancel-button { display: none; }
.projects-search button { display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center; padding: 0; border: 0; border-radius: 5px; color: var(--app-text-secondary); background: var(--app-surface-muted); cursor: pointer; }
.projects-search button:focus-visible { outline: 2px solid var(--app-accent); }
.projects-library__filters :deep(.app-select) { min-width: 0; flex: 0 0 124px; }
.projects-library__filters :deep(.app-select__trigger) { height: 40px; }
.projects-library__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.projects-page__empty, .projects-page__error { display: grid; min-height: 285px; place-items: center; align-content: center; gap: 12px; text-align: center; }
.projects-page__empty-icon { display: grid; width: 64px; height: 64px; margin-bottom: 4px; place-items: center; border-radius: 18px; color: var(--app-text-secondary); background: var(--app-surface-muted); }
.projects-page__empty h3, .projects-page__error h2 { margin: 0; font-size: 17px; font-weight: 600; }
.projects-page__empty p, .projects-page__error p { max-width: 500px; margin: 0 0 6px; color: var(--app-text-secondary); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.projects-page__empty-link { display: inline-flex; min-height: 38px; align-items: center; gap: 7px; color: var(--app-accent); font-size: 13px; font-weight: 600; }
.projects-page__summary-skeleton { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.projects-page__summary-skeleton span { min-height: 119px; border-radius: 16px; background: var(--app-surface-muted); }
.projects-page__loading p { padding: 35px; color: var(--app-text-secondary); font-size: 13px; text-align: center; }
.projects-sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@container projects (min-width: 1800px) { .projects-library__grid { grid-template-columns: repeat(5, minmax(0, 1fr)); } }
@container projects (max-width: 1160px) { .projects-library__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .projects-summary__item { padding: 17px; gap: 11px; } }
@container projects (max-width: 870px) { .projects-library__grid, .projects-summary, .projects-page__summary-skeleton { grid-template-columns: repeat(2, minmax(0, 1fr)); } .projects-library__filters { flex-basis: 100%; } }
@container projects (max-width: 560px) { .projects-library__grid { grid-template-columns: minmax(0, 1fr); } .projects-library__filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } .projects-search, .projects-library__filters :deep(.app-select:last-child) { grid-column: 1 / -1; } .projects-summary__item { min-height: 112px; gap: 9px; padding: 14px; } .projects-summary__icon { width: 34px; height: 34px; border-radius: 9px; } .projects-summary__icon svg { width: 19px; } .projects-summary p { font-size: 23px; } .projects-summary__item > div > span { font-size: 11px; } }
@container projects (max-width: 380px) { .projects-summary__icon { display: none; } .projects-summary__item > div > span { font-size: 11px; } }
@media (max-width: 720px) { .projects-page { padding: 24px 16px 45px; } .projects-page__header { gap: 10px; margin-bottom: 23px; } .projects-page__create { padding: 0 12px; font-size: 12px; } }
@media (prefers-reduced-motion: reduce) { .projects-page__create { transition: none; } }
</style>
