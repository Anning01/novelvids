<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CheckCircle2, ChevronRight, Clapperboard, Home, LayoutGrid, List, Play, Search, Shield, Star } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { useAuthStore } from '@/features/auth/authStore'
import WorkCard from '@/features/portfolio/WorkCard.vue'
import { workApi, workDate, type WorkFilter } from '@/features/portfolio/api'
import { tr } from '@/i18n'
import '@/features/portfolio/portfolio.css'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const status = ref<WorkFilter>('all')
const search = ref('')
const category = ref('')
const producer = ref('')
const sort = ref('recent')
const page = ref(1)
const layout = ref<'cards' | 'list'>('cards')
const loading = ref(false)
const error = ref('')
const result = ref<Awaited<ReturnType<typeof workApi.list>>['data']>()
const pageSize = 18
let request: AbortController | undefined
let searchTimer: ReturnType<typeof setTimeout> | undefined

const canManage = computed(() => auth.enabled !== true || ['admin', 'super'].includes(auth.role ?? ''))
const project = computed(() => String(route.query.project ?? ''))
const pages = computed(() => Math.max(1, Math.ceil((result.value?.total ?? 0) / pageSize)))
const metrics = [
  { key: 'all', label: '作品总数', icon: Clapperboard },
  { key: 'pending', label: '待审核', icon: Shield },
  { key: 'public', label: '已公开', icon: CheckCircle2 },
  { key: 'featured', label: '首页推荐', icon: Star },
] as const
const tabs = [
  { key: 'all', label: '全部作品' }, { key: 'pending', label: '待审核' },
  { key: 'public', label: '已公开' }, { key: 'private', label: '未公开' },
] as const
const sortOptions = computed(() => [
  { value: 'recent', label: tr('最近归档') }, { value: 'title', label: tr('按作品名称') },
  { value: 'duration', label: tr('按作品时长') }, { value: 'recommended', label: tr('按推荐顺序') },
])
const categoryOptions = computed(() => [{ value: '', label: tr('全部类型') }, ...(result.value?.categories ?? []).map(value => ({ value, label: value }))])
const producerOptions = computed(() => [{ value: '', label: tr('全部创作者') }, ...(result.value?.producers ?? []).map(row => ({ value: String(row.id), label: row.name }))])
const actionNames: Record<string, string> = {
  archive: '已归档', edit: '更新了作品资料', submit: '等待审核', approve: '审核通过', publish: '已公开', withdraw: '已下架', recommend: '更新了首页推荐',
}

async function load() {
  request?.abort()
  const controller = new AbortController()
  request = controller
  loading.value = true
  error.value = ''
  try {
    const response = await workApi.list({
      status: status.value, search: search.value, category: category.value, sort: sort.value,
      page: String(page.value), page_size: String(pageSize),
      ...(project.value ? { project_id: project.value } : {}),
      ...(producer.value ? { producer_id: producer.value } : {}),
    }, controller.signal)
    if (!controller.signal.aborted) result.value = response.data
  } catch (reason) {
    if (!controller.signal.aborted) error.value = reason instanceof Error ? reason.message : tr('作品加载失败')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}
function resetPage() {
  if (page.value === 1) void load()
  else page.value = 1
}
watch([status, category, producer, sort, project], resetPage)
watch(page, load)
watch(() => auth.activeTeamId, () => {
  result.value = undefined
  producer.value = ''
  category.value = ''
  resetPage()
}, { immediate: true })
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(resetPage, 180)
})
onBeforeUnmount(() => {
  request?.abort()
  clearTimeout(searchTimer)
})
</script>

<template>
  <main class="portfolio-page">
    <header class="work-header">
      <div><h1>{{ tr('作品库') }}</h1><p>{{ tr('集中管理已完成的作品，审核后公开展示') }}</p></div>
      <div class="work-actions">
        <RouterLink to="/" class="work-link"><Home :size="16" aria-hidden="true" />{{ tr('返回首页') }}</RouterLink>
      </div>
    </header>

    <section class="work-metrics" :aria-label="tr('作品概况')">
      <button v-for="metric in metrics" :key="metric.key" type="button" class="work-panel work-metric" :data-status="metric.key" :aria-pressed="status === metric.key" @click="status = metric.key">
        <span class="work-metric-icon"><component :is="metric.icon" :size="23" aria-hidden="true" /></span>
        <span>{{ tr(metric.label) }}<strong>{{ result?.counts[metric.key] ?? '—' }}</strong></span>
      </button>
    </section>

    <div class="work-filters">
      <label class="work-search"><Search :size="17" aria-hidden="true" /><input v-model="search" type="search" maxlength="255" :aria-label="tr('搜索作品名称')" :placeholder="tr('搜索作品名称')" /></label>
      <AppSelect v-model="category" :options="categoryOptions" :ariaLabel="tr('作品类型')" density="compact" />
      <AppSelect v-model="sort" :options="sortOptions" :ariaLabel="tr('作品排序')" density="compact" />
      <AppSelect v-model="producer" :options="producerOptions" :ariaLabel="tr('创作者筛选')" density="compact" />
      <AppButton v-if="project" size="sm" @click="router.replace({ query: {} })">{{ tr('清除项目筛选') }}</AppButton>
      <div class="work-view" role="group" :aria-label="tr('作品视图')">
        <AppButton size="sm" icon-only :active="layout === 'cards'" :aria-pressed="layout === 'cards'" :aria-label="tr('卡片视图')" @click="layout = 'cards'"><LayoutGrid :size="17" /></AppButton>
        <AppButton size="sm" icon-only :active="layout === 'list'" :aria-pressed="layout === 'list'" :aria-label="tr('列表视图')" @click="layout = 'list'"><List :size="17" /></AppButton>
      </div>
    </div>

    <div class="work-management">
      <section class="work-panel work-results" :aria-label="tr('作品列表')" :aria-busy="loading">
        <div class="work-tabs" role="group" :aria-label="tr('作品状态筛选')">
          <AppButton v-for="tab in tabs" :key="tab.key" size="sm" :variant="status === tab.key ? 'soft' : 'ghost'" :aria-pressed="status === tab.key" @click="status = tab.key">
            {{ tr(tab.label) }} <span v-if="result">{{ result.counts[tab.key] }}</span>
          </AppButton>
          <AppButton v-if="status === 'featured'" size="sm" variant="soft" aria-pressed="true">{{ tr('首页推荐') }} {{ result?.counts.featured }}</AppButton>
        </div>
        <p v-if="loading" class="work-state" role="status">{{ tr('正在加载作品…') }}</p>
        <div v-else-if="error" class="work-state work-error" role="alert">{{ error }} <AppButton size="sm" @click="load">{{ tr('重试') }}</AppButton></div>
        <div v-else-if="result?.items.length" class="work-grid" :class="{ 'is-list': layout === 'list' }">
          <WorkCard v-for="work in result.items" :key="work.project_id" :work="work" />
        </div>
        <p v-else class="work-state">{{ tr('没有符合条件的作品') }}</p>
        <footer v-if="pages > 1" class="work-actions work-pages">
          <AppButton size="sm" :disabled="loading || page <= 1" @click="page--">{{ tr('上一页') }}</AppButton>
          <span>{{ page }} / {{ pages }}</span>
          <AppButton size="sm" :disabled="loading || page >= pages" @click="page++">{{ tr('下一页') }}</AppButton>
        </footer>
      </section>

      <aside class="work-sidebar">
        <section class="work-panel work-side-panel">
          <h2>{{ tr('快速操作') }}</h2>
          <AppButton v-if="canManage" variant="secondary" block @click="status = 'pending'"><Shield :size="16" />{{ tr('审核待处理作品') }}<ChevronRight :size="14" /></AppButton>
          <AppButton v-if="canManage" variant="secondary" block @click="status = 'featured'"><Star :size="16" />{{ tr('管理首页推荐') }}<ChevronRight :size="14" /></AppButton>
          <AppButton variant="secondary" block @click="status = 'public'"><Play :size="16" /><span>{{ tr('查看公开作品') }}</span><ChevronRight :size="14" /></AppButton>
        </section>
        <section class="work-panel work-side-panel">
          <h2>{{ tr('最近动态') }}</h2>
          <RouterLink v-for="work in result?.recent" :key="work.project_id" :to="{ name: 'work-detail', params: { projectId: work.project_id } }" class="work-activity">
            <Clapperboard :size="17" aria-hidden="true" />
            <span><strong>{{ work.title }}</strong><small>{{ tr(actionNames[work.last_action] ?? '已归档') }} · {{ workDate(work.updated_at) }}</small></span>
          </RouterLink>
          <p v-if="!result?.recent.length" class="work-muted">{{ tr('暂无动态') }}</p>
        </section>
      </aside>
    </div>
  </main>
</template>
