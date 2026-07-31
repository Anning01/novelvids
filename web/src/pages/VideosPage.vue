<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Box,
  Check,
  ChevronRight,
  Copy,
  FolderKanban,
  Image as ImageIcon,
  Library,
  Map,
  Mic2,
  RefreshCw,
  UserRound,
  UsersRound,
  Volume2,
} from 'lucide-vue-next'
import SearchFilterBar from '@/components/SearchFilterBar.vue'
import AppTabs, { type AppTabItem } from '@/components/AppTabs.vue'
import type { SearchFilterDefinition } from '@/components/SearchFilterBar.vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { AssetTypeEnum } from '@/types'
import type { Asset, AudioReference, DigitalHuman, Novel } from '@/types'

type AssetScope = 'public' | 'project'
type PublicCategory = 'character' | 'audio'
type ProjectCategory = 'character' | 'scene' | 'prop'

const scope = ref<AssetScope>('public')
const scopeTabs: AppTabItem[] = [
  { value: 'public', label: '公共资产', icon: Library },
  { value: 'project', label: '项目资产', icon: FolderKanban },
]
const publicCategory = ref<PublicCategory>('character')
const projectCategory = ref<ProjectCategory>('character')
const search = ref('')
const loading = ref(true)
const refreshing = ref(false)
const digitalHumans = ref<DigitalHuman[]>([])
const audioReferences = ref<AudioReference[]>([])
const projects = ref<Novel[]>([])
const selectedProjectId = ref('')
const projectAssets = ref<Asset[]>([])
const characterFilterValues = ref<Record<string, string>>({ country: '', gender: '', age: '', occupation: '' })
const audioFilterValues = ref<Record<string, string>>({ gender: '' })
const characterPagination = ref({ page: 1, pages: 1, total: 0 })
const audioPagination = ref({ page: 1, pages: 1, total: 0 })
const projectPagination = ref({ page: 1, pages: 1, total: 0 })
const loadingMore = ref(false)
const loadMoreTarget = ref<HTMLElement | null>(null)
let loadMoreObserver: IntersectionObserver | null = null
let publicSearchTimer: ReturnType<typeof setTimeout> | undefined
let publicQueryVersion = 0

const publicCategories = [
  { value: 'character', label: '角色库', icon: UsersRound },
  { value: 'audio', label: '音频库', icon: Volume2 },
] satisfies Array<AppTabItem & { value: PublicCategory }>

const projectCategories = [
  { value: 'character', label: '角色', icon: UserRound, type: AssetTypeEnum.PERSON },
  { value: 'scene', label: '场景', icon: Map, type: AssetTypeEnum.SCENE },
  { value: 'prop', label: '道具', icon: Box, type: AssetTypeEnum.ITEM },
] satisfies Array<AppTabItem & { value: ProjectCategory, type: AssetTypeEnum }>

const projectOptions = computed(() => projects.value.map(item => ({ value: String(item.id), label: item.name })))
const selectedProject = computed(() => projects.value.find(item => String(item.id) === selectedProjectId.value))
const activeProjectType = computed(() => projectCategories.find(item => item.value === projectCategory.value)?.type ?? AssetTypeEnum.PERSON)

const filteredCharacters = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  const filters = characterFilterValues.value
  return digitalHumans.value.filter(item => {
    const matchesSearch = !keyword || [item.country, item.gender, item.occupation, String(item.age)].some(value => value?.toLowerCase().includes(keyword))
    const matchesCountry = !filters.country || item.country === filters.country
    const matchesGender = !filters.gender || genderMatches(item.gender, filters.gender)
    const matchesOccupation = !filters.occupation || item.occupation === filters.occupation
    const matchesAge = !filters.age || ageMatches(item.age, filters.age)
    return matchesSearch && matchesCountry && matchesGender && matchesOccupation && matchesAge
  })
})

const filteredAudio = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return audioReferences.value.filter(item => {
    const matchesSearch = !keyword || [item.nickname, item.gender].some(value => value?.toLowerCase().includes(keyword))
    const matchesGender = !audioFilterValues.value.gender || genderMatches(item.gender, audioFilterValues.value.gender)
    return matchesSearch && matchesGender
  })
})

function ageMatches(age: number, range: string) {
  if (range === 'under-20') return age < 20
  if (range === '20-29') return age >= 20 && age <= 29
  if (range === '30-39') return age >= 30 && age <= 39
  if (range === '40-59') return age >= 40 && age <= 59
  if (range === '60-plus') return age >= 60
  return true
}

function genderMatches(value: string, gender: string) {
  if (gender === 'male') return value === '男' || value === '男性'
  if (gender === 'female') return value === '女' || value === '女性'
  return true
}

const genderOptions = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
]

function uniqueOptions(values: Array<string | undefined>, selected = '') {
  return [...new Set([...values, selected].filter((value): value is string => Boolean(value)))].sort((a, b) => a.localeCompare(b, 'zh-CN')).map(value => ({ value, label: value }))
}

const activeFilterDefinitions = computed<SearchFilterDefinition[]>(() => {
  if (scope.value === 'project') return projectOptions.value.length ? [{ key: 'project', label: '项目', options: projectOptions.value, width: 220, required: true }] : []
  if (publicCategory.value === 'audio') return [{ key: 'gender', label: '性别', options: genderOptions }]
  return [
    { key: 'country', label: '国家', options: uniqueOptions(digitalHumans.value.map(item => item.country), characterFilterValues.value.country) },
    { key: 'gender', label: '性别', options: genderOptions },
    { key: 'age', label: '年龄', options: [
      { value: 'under-20', label: '20 岁以下' },
      { value: '20-29', label: '20–29 岁' },
      { value: '30-39', label: '30–39 岁' },
      { value: '40-59', label: '40–59 岁' },
      { value: '60-plus', label: '60 岁以上' },
    ] },
    { key: 'occupation', label: '职业', options: uniqueOptions(digitalHumans.value.map(item => item.occupation), characterFilterValues.value.occupation), width: 190 },
  ]
})

const activeFilterValues = computed<Record<string, string>>({
  get() {
    if (scope.value === 'project') return { project: selectedProjectId.value }
    return publicCategory.value === 'character' ? characterFilterValues.value : audioFilterValues.value
  },
  set(value) {
    if (scope.value === 'project') {
      if (value.project) selectedProjectId.value = value.project
    } else if (publicCategory.value === 'character') characterFilterValues.value = value
    else audioFilterValues.value = value
  },
})

const filteredProjectAssets = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return projectAssets.value.filter(item => {
    const sameType = item.asset_type === activeProjectType.value
    const matchesSearch = !keyword || [item.canonical_name, item.description, ...(item.aliases || [])].some(value => value?.toLowerCase().includes(keyword))
    return sameType && matchesSearch
  })
})

const visibleCount = computed(() => {
  if (scope.value === 'project') return filteredProjectAssets.value.length
  return publicCategory.value === 'character' ? filteredCharacters.value.length : filteredAudio.value.length
})

const activePagination = computed(() => {
  if (scope.value === 'project') return projectPagination.value
  return publicCategory.value === 'character' ? characterPagination.value : audioPagination.value
})

const hasMore = computed(() => activePagination.value.page < activePagination.value.pages)

const resultCountLabel = computed(() => {
  const hasPublicFilters = scope.value === 'public' && Object.values(publicCategory.value === 'character' ? characterFilterValues.value : audioFilterValues.value).some(Boolean)
  const { total } = activePagination.value
  if (search.value.trim() || hasPublicFilters) return total > visibleCount.value ? `已加载 ${visibleCount.value} / ${total} 项匹配` : `${visibleCount.value} 项匹配`
  return total > visibleCount.value ? `已加载 ${visibleCount.value} / ${total} 项` : `${visibleCount.value} 项资产`
})

const searchPlaceholder = computed(() => {
  if (scope.value === 'project') return `搜索${projectCategories.find(item => item.value === projectCategory.value)?.label || '项目资产'}`
  return publicCategory.value === 'character' ? '搜索职业、国家、性别或年龄' : '搜索音色名称或性别'
})

async function loadPublicAssets() {
  const [characterResponse, audioResponse] = await Promise.all([
    api.digitalHumans(1, ''),
    api.audioReferences(1, ''),
  ])
  digitalHumans.value = characterResponse.data.items
  audioReferences.value = audioResponse.data.items
  characterPagination.value = characterResponse.data.pagination
  audioPagination.value = audioResponse.data.pagination
}

function characterRequestFilters() {
  const filters = characterFilterValues.value
  const requestFilters: Record<string, string | number | undefined> = {
    country: filters.country,
    gender__in: filters.gender === 'male' ? '男,男性' : filters.gender === 'female' ? '女,女性' : undefined,
    occupation: filters.occupation,
  }
  if (filters.age === 'under-20') requestFilters.age__lt = 20
  if (filters.age === '20-29') { requestFilters.age__gte = 20; requestFilters.age__lte = 29 }
  if (filters.age === '30-39') { requestFilters.age__gte = 30; requestFilters.age__lte = 39 }
  if (filters.age === '40-59') { requestFilters.age__gte = 40; requestFilters.age__lte = 59 }
  if (filters.age === '60-plus') requestFilters.age__gte = 60
  return requestFilters
}

function audioRequestFilters() {
  const gender = audioFilterValues.value.gender
  return { gender__in: gender === 'male' ? '男,男性' : gender === 'female' ? '女,女性' : undefined }
}

async function reloadActivePublicAssets() {
  const kind = publicCategory.value
  const version = ++publicQueryVersion
  loadingMore.value = true
  try {
    if (kind === 'character') {
      const response = await api.digitalHumans(1, search.value.trim(), characterRequestFilters())
      if (version !== publicQueryVersion || publicCategory.value !== kind) return
      digitalHumans.value = response.data.items
      characterPagination.value = response.data.pagination
    } else {
      const response = await api.audioReferences(1, search.value.trim(), audioRequestFilters())
      if (version !== publicQueryVersion || publicCategory.value !== kind) return
      audioReferences.value = response.data.items
      audioPagination.value = response.data.pagination
    }
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    if (version === publicQueryVersion) {
      loadingMore.value = false
      await nextTick()
      loadMoreIfVisible()
    }
  }
}

function schedulePublicReload() {
  if (scope.value !== 'public') return
  if (publicSearchTimer) clearTimeout(publicSearchTimer)
  publicSearchTimer = setTimeout(() => void reloadActivePublicAssets(), 220)
}

async function loadProjects() {
  const response = await api.novels()
  projects.value = response.data.items
  if (!selectedProjectId.value && projects.value.length) selectedProjectId.value = String(projects.value[0].id)
}

async function loadProjectAssets() {
  if (!selectedProjectId.value) {
    projectAssets.value = []
    projectPagination.value = { page: 1, pages: 1, total: 0 }
    return
  }
  const response = await api.assets(Number(selectedProjectId.value), 1, 24)
  projectAssets.value = response.data.items
  projectPagination.value = response.data.pagination
}

function appendUnique<T extends { id: number }>(current: T[], incoming: T[]) {
  const ids = new Set(current.map(item => item.id))
  return [...current, ...incoming.filter(item => !ids.has(item.id))]
}

async function loadMore() {
  if (loading.value || loadingMore.value || !hasMore.value) return
  const requestVersion = publicQueryVersion
  loadingMore.value = true
  try {
    if (scope.value === 'public' && publicCategory.value === 'character') {
      const response = await api.digitalHumans(characterPagination.value.page + 1, search.value.trim(), characterRequestFilters())
      if (requestVersion !== publicQueryVersion) return
      digitalHumans.value = appendUnique(digitalHumans.value, response.data.items)
      characterPagination.value = response.data.pagination
    } else if (scope.value === 'public') {
      const response = await api.audioReferences(audioPagination.value.page + 1, search.value.trim(), audioRequestFilters())
      if (requestVersion !== publicQueryVersion) return
      audioReferences.value = appendUnique(audioReferences.value, response.data.items)
      audioPagination.value = response.data.pagination
    } else if (selectedProjectId.value) {
      const response = await api.assets(Number(selectedProjectId.value), projectPagination.value.page + 1, 24)
      projectAssets.value = appendUnique(projectAssets.value, response.data.items)
      projectPagination.value = response.data.pagination
    }
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingMore.value = false
    await nextTick()
    loadMoreIfVisible()
  }
}

function loadMoreIfVisible() {
  const targetTop = loadMoreTarget.value?.getBoundingClientRect().top
  if (hasMore.value && targetTop !== undefined && targetTop < window.innerHeight + 320) void loadMore()
}

async function load() {
  loading.value = true
  try {
    await Promise.all([loadPublicAssets(), loadProjects()])
    await loadProjectAssets()
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
    await nextTick()
    loadMoreIfVisible()
  }
}

async function refresh() {
  refreshing.value = true
  try {
    if (scope.value === 'public') await reloadActivePublicAssets()
    else await loadProjectAssets()
    notice.success('资产库已刷新')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    refreshing.value = false
  }
}

function changeScope(value: AssetScope) {
  scope.value = value
  search.value = ''
}

function changeScopeFromTab(value: string) {
  changeScope(value as AssetScope)
}

function selectPublicCategory(value: PublicCategory) {
  publicCategory.value = value
  search.value = ''
}

function changePublicCategoryFromTab(value: string) {
  selectPublicCategory(value as PublicCategory)
}

function selectProjectCategory(value: ProjectCategory) {
  projectCategory.value = value
  search.value = ''
}

function changeProjectCategoryFromTab(value: string) {
  selectProjectCategory(value as ProjectCategory)
}

async function copyAssetId(assetId: string) {
  try {
    await navigator.clipboard.writeText(assetId)
    notice.success('资产 ID 已复制')
  } catch {
    notice.error('复制失败，请稍后重试')
  }
}

watch(selectedProjectId, async (value, previous) => {
  if (!value || value === previous || loading.value) return
  try {
    await loadProjectAssets()
  } catch (error) {
    notice.error((error as Error).message)
  }
})

watch([scope, publicCategory, projectCategory], async () => {
  await nextTick()
  loadMoreIfVisible()
})

watch(search, () => schedulePublicReload())

watch([characterFilterValues, audioFilterValues], () => schedulePublicReload(), { deep: true })

onMounted(load)

onMounted(() => {
  loadMoreObserver = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) void loadMore()
  }, { rootMargin: '320px 0px' })
  if (loadMoreTarget.value) loadMoreObserver.observe(loadMoreTarget.value)
})

onBeforeUnmount(() => {
  loadMoreObserver?.disconnect()
  if (publicSearchTimer) clearTimeout(publicSearchTimer)
})
</script>

<template>
  <main class="assets-page">
    <header class="assets-heading">
      <div>
        <span>ASSET LIBRARY</span>
        <h1>资产</h1>
        <p>统一管理可跨项目复用的公共素材，以及每个短剧项目独立的角色、场景和道具。</p>
      </div>
      <AppButton class="refresh-assets" variant="secondary" size="sm" type="button" :loading="refreshing" @click="refresh"><RefreshCw v-if="!refreshing" :size="16" />刷新</AppButton>
    </header>

    <AppTabs class="asset-scope-tabs" :model-value="scope" :items="scopeTabs" label="资产范围" @update:model-value="changeScopeFromTab" />

    <section class="asset-workspace">
      <header class="workspace-header">
        <AppTabs v-if="scope === 'public'" class="asset-category-tabs" :model-value="publicCategory" :items="publicCategories" label="公共资产分类" @update:model-value="changePublicCategoryFromTab" />
        <AppTabs v-else class="asset-category-tabs" :model-value="projectCategory" :items="projectCategories" label="项目资产分类" @update:model-value="changeProjectCategoryFromTab" />

        <SearchFilterBar v-model="search" v-model:filter-values="activeFilterValues" :filters="activeFilterDefinitions" :placeholder="searchPlaceholder" :search-aria-label="searchPlaceholder" :result-label="resultCountLabel" />
      </header>

      <div v-if="loading" class="asset-state"><RefreshCw class="is-spinning" :size="23" /><span>正在加载资产库…</span></div>

      <template v-else-if="scope === 'public'">
        <div v-if="publicCategory === 'character' && filteredCharacters.length" class="public-character-grid">
          <article v-for="item in filteredCharacters" :key="item.id" class="public-character-card">
            <div class="character-image"><img :src="item.image_url" :alt="`${item.occupation}角色`" /><span v-if="item.is_active"><Check :size="12" />可用</span></div>
            <div class="character-copy"><div><h2>{{ item.occupation || '公共角色' }}</h2><AppButton type="button" variant="ghost" size="xs" icon-only aria-label="复制资产 ID" title="复制资产 ID" @click="copyAssetId(item.asset_id)"><Copy :size="14" /></AppButton></div><p>{{ item.country }} · {{ item.gender }} · {{ item.age }} 岁</p><small>{{ item.asset_id }}</small></div>
          </article>
        </div>

        <div v-else-if="publicCategory === 'audio' && filteredAudio.length" class="audio-library-list">
          <article v-for="item in filteredAudio" :key="item.id" class="audio-reference-card">
            <img :src="item.avatar_url" :alt="item.nickname" />
            <div class="audio-copy"><span><Mic2 :size="13" />{{ item.gender }}声音</span><h2>{{ item.nickname }}</h2><small>{{ item.asset_id }}</small></div>
            <audio :src="item.audio_url" controls preload="none" />
            <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="复制资产 ID" title="复制资产 ID" @click="copyAssetId(item.asset_id)"><Copy :size="14" /></AppButton>
          </article>
        </div>

        <div v-else class="asset-state is-empty"><span><component :is="publicCategory === 'character' ? UsersRound : Volume2" :size="26" /></span><h2>没有找到匹配的{{ publicCategory === 'character' ? '角色' : '音频' }}</h2><p>换一个关键词试试。</p></div>
      </template>

      <template v-else>
        <div v-if="!projects.length" class="asset-state is-empty"><span><FolderKanban :size="26" /></span><h2>还没有项目资产</h2><p>先创建一个短剧项目，角色、场景和道具会按项目归档。</p><RouterLink to="/projects">前往项目<ChevronRight :size="15" /></RouterLink></div>

        <div v-else-if="filteredProjectAssets.length" class="project-asset-grid">
          <article v-for="item in filteredProjectAssets" :key="item.id" class="project-asset-card">
            <div class="project-asset-image">
              <img v-if="item.main_image" :src="item.main_image" :alt="item.canonical_name" loading="lazy" />
              <component :is="projectCategory === 'character' ? UserRound : projectCategory === 'scene' ? ImageIcon : Box" v-else :size="30" />
            </div>
            <div><span>{{ selectedProject?.name }}</span><h2>{{ item.canonical_name }}</h2><p>{{ item.description || '暂无资产描述' }}</p><small v-if="item.source_chapters?.length">出现于第 {{ item.source_chapters.join('、') }} 集</small></div>
          </article>
        </div>

        <div v-else class="asset-state is-empty"><span><component :is="projectCategory === 'character' ? UserRound : projectCategory === 'scene' ? Map : Box" :size="26" /></span><h2>暂无{{ projectCategories.find(item => item.value === projectCategory)?.label }}资产</h2><p>{{ selectedProject?.name }}还没有生成这一类资产。</p></div>
      </template>

      <div ref="loadMoreTarget" class="load-more-sentinel" aria-live="polite">
        <span v-if="loadingMore"><RefreshCw class="is-spinning" :size="16" />正在加载更多资产…</span>
        <span v-else-if="hasMore">继续下滑加载更多</span>
        <span v-else-if="visibleCount">已加载全部资产</span>
      </div>
    </section>
  </main>
</template>

<style scoped>
.assets-page { min-height: 100%; padding: 36px 22px 80px; color: var(--app-text); background: var(--app-canvas); }
.assets-heading { display: flex; width: 100%; align-items: flex-start; justify-content: space-between; gap: 24px; margin: 0 0 24px; padding-bottom: 24px; border-bottom: 1px solid var(--app-border); }
.assets-heading > div { display: grid; gap: 5px; }
.assets-heading > div > span { color: var(--app-accent); font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.assets-heading h1 { margin: 0; color: var(--app-text); font-size: clamp(28px, 3vw, 38px); letter-spacing: -.035em; }
.assets-heading p { max-width: 660px; margin: 0; color: var(--app-text-muted); font-size: 12px; line-height: 1.6; }
.refresh-assets { display: inline-flex; min-height: 38px; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--app-border); border-radius: 9px; color: var(--app-text-secondary); background: var(--app-surface); cursor: pointer; font-size: 11px; }
.refresh-assets:hover { border-color: var(--app-border-strong); color: var(--app-text); background: var(--app-surface-hover); }
.refresh-assets:disabled { cursor: wait; opacity: .6; }
.asset-scope-tabs { margin: 0 0 22px; }
.asset-workspace { width: 100%; min-height: 520px; margin: 0; }
.workspace-header { display: grid; gap: 14px; padding-bottom: 13px; border-bottom: 1px solid var(--app-border); }
.public-character-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 13px; padding-top: 20px; }
.public-character-card { overflow: hidden; border: 1px solid var(--app-border); border-radius: 13px; background: var(--app-surface); box-shadow: var(--app-shadow); transition: border-color .16s ease, transform .16s ease, box-shadow .16s ease; }
.public-character-card:hover { border-color: var(--app-border-strong); box-shadow: 0 16px 34px rgb(0 0 0 / 14%); transform: translateY(-2px); }
.character-image { position: relative; aspect-ratio: 4 / 5; overflow: hidden; background: var(--app-surface-muted); }
.character-image img { width: 100%; height: 100%; object-fit: cover; }
.character-image > span { position: absolute; top: 10px; right: 10px; display: inline-flex; align-items: center; gap: 4px; padding: 5px 7px; border: 1px solid rgb(255 255 255 / 60%); border-radius: 999px; color: #258662; background: rgb(255 255 255 / 90%); font-size: 8px; backdrop-filter: blur(8px); }
.character-copy { display: grid; gap: 5px; padding: 13px; }
.character-copy > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.character-copy h2, .audio-copy h2, .project-asset-card h2 { overflow: hidden; margin: 0; color: var(--app-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.character-copy button, .audio-reference-card > button { display: grid; width: 28px; height: 28px; flex: 0 0 auto; place-items: center; border: 0; border-radius: 7px; color: var(--app-text-muted); background: transparent; cursor: pointer; }
.character-copy button:hover, .audio-reference-card > button:hover { color: var(--app-accent); background: var(--app-accent-soft); }
.character-copy p { margin: 0; color: var(--app-text-secondary); font-size: 10px; }
.character-copy small, .audio-copy small { overflow: hidden; color: var(--app-text-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.audio-library-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding-top: 20px; }
.audio-reference-card { display: grid; min-width: 0; grid-template-columns: 54px minmax(0, 1fr) minmax(190px, 260px) 30px; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.audio-reference-card > img { width: 54px; height: 54px; border-radius: 12px; object-fit: cover; background: var(--app-surface-muted); }
.audio-copy { display: grid; min-width: 0; gap: 3px; }
.audio-copy > span { display: inline-flex; align-items: center; gap: 4px; color: var(--app-accent); font-size: 8px; }
.audio-reference-card audio { width: 100%; height: 32px; }
.project-asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 13px; padding-top: 20px; }
.project-asset-card { display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 13px; padding: 12px; border: 1px solid var(--app-border); border-radius: 13px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.project-asset-image { display: grid; min-height: 116px; overflow: hidden; place-items: center; border-radius: 10px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.project-asset-image img { width: 100%; height: 100%; object-fit: cover; }
.project-asset-card > div:last-child { display: grid; min-width: 0; align-content: start; gap: 6px; }
.project-asset-card > div:last-child > span { color: var(--app-accent); font-size: 8px; font-weight: 600; }
.project-asset-card p { display: -webkit-box; overflow: hidden; margin: 0; color: var(--app-text-secondary); font-size: 10px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.project-asset-card small { color: var(--app-text-muted); font-size: 8px; }
.asset-state { display: grid; min-height: 420px; place-items: center; align-content: center; gap: 9px; color: var(--app-text-muted); font-size: 11px; text-align: center; }
.asset-state.is-empty > span { display: grid; width: 52px; height: 52px; margin-bottom: 3px; place-items: center; border-radius: 14px; color: var(--app-accent); background: var(--app-accent-soft); }
.asset-state h2 { margin: 0; color: var(--app-text); font-size: 14px; }
.asset-state p { max-width: 380px; margin: 0; color: var(--app-text-muted); font-size: 10px; line-height: 1.6; }
.asset-state a { display: inline-flex; min-height: 34px; align-items: center; gap: 5px; margin-top: 5px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-accent); background: var(--app-surface); font-size: 10px; }
.load-more-sentinel { display: grid; min-height: 64px; place-items: center; color: var(--app-text-muted); font-size: 10px; }
.load-more-sentinel span { display: inline-flex; align-items: center; gap: 7px; }
.is-spinning { animation: asset-spin .9s linear infinite; }
@keyframes asset-spin { to { transform: rotate(360deg); } }
@media (max-width: 1000px) {
  .audio-library-list { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .assets-page { padding: 30px 16px 60px; }
  .assets-heading { align-items: stretch; flex-direction: column; }
  .refresh-assets { justify-content: center; }
  .public-character-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
  .audio-reference-card { grid-template-columns: 48px minmax(0, 1fr) 30px; }
  .audio-reference-card > img { width: 48px; height: 48px; }
  .audio-reference-card audio { grid-column: 1 / -1; }
}
@media (max-width: 420px) {
  .public-character-grid { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .public-character-card, .refresh-assets svg { transition: none; animation: none; }
}
</style>
