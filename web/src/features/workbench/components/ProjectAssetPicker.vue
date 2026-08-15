<script setup lang="ts">
import { Boxes, FolderKanban, Image as ImageIcon, Library, Search, UserRound, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import type { Asset } from '@/types'
import { AssetTypeEnum } from '@/types'
import { assetTypePresentationOptions } from './assetTypePresentation'
import type { ReusableAssetChoice } from './reusableAsset'

type AssetScope = 'public' | 'project'

interface PickerItem {
  key: string
  name: string
  detail: string
  image: string
  choice: ReusableAssetChoice
}

const props = defineProps<{
  open: boolean
  novelId: number
  assetType: AssetTypeEnum
  excludedIds?: number[]
}>()
const emit = defineEmits<{
  close: []
  choose: [choice: ReusableAssetChoice]
}>()

const scope = ref<AssetScope>('project')
const items = ref<PickerItem[]>([])
const search = ref('')
const page = ref(1)
const pages = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
let loadVersion = 0

const excluded = computed(() => new Set(props.excludedIds || []))
const typeLabel = computed(() => assetTypePresentationOptions.find(item => item.value === String(props.assetType))?.label || '资产')
const searchLabel = computed(() => `搜索${scope.value === 'public' ? '公共' : '项目'}${typeLabel.value}资产`)

function fallbackIcon() {
  if (props.assetType === AssetTypeEnum.PERSON) return UserRound
  if (props.assetType === AssetTypeEnum.SCENE) return ImageIcon
  return Boxes
}

function projectItems(assets: Asset[]): PickerItem[] {
  return assets
    .filter(asset => asset.asset_type === props.assetType && !excluded.value.has(asset.id))
    .map(asset => ({
      key: `project-${asset.id}`,
      name: asset.canonical_name,
      detail: asset.description || '暂无描述',
      image: asset.main_image || '',
      choice: { scope: 'project', asset },
    }))
}

function publicAssetItems(assets: Asset[]): PickerItem[] {
  return assets
    .filter(asset => asset.asset_type === props.assetType && asset.novel_id !== props.novelId)
    .map(asset => ({
      key: `public-asset-${asset.id}`,
      name: asset.canonical_name,
      detail: asset.description || '公共资产',
      image: asset.main_image || '',
      choice: { scope: 'public', asset },
    }))
}

async function requestItems(nextPage: number, requestScope: AssetScope): Promise<{ items: PickerItem[]; page: number; pages: number }> {
  if (requestScope === 'project') {
    const response = await api.projectAssetLibrary(props.novelId, nextPage, search.value.trim(), 24, props.assetType)
    return {
      items: projectItems(response.data.items),
      page: response.data.pagination.page,
      pages: response.data.pagination.pages,
    }
  }
  if (props.assetType === AssetTypeEnum.PERSON) {
    const response = await api.digitalHumans(nextPage, search.value.trim())
    return {
      items: response.data.items.map(item => ({
        key: `public-human-${item.id}`,
        name: item.occupation || '公共人物',
        detail: `${item.country} · ${item.gender} · ${item.age} 岁`,
        image: item.image_url,
        choice: { scope: 'public', digitalHuman: item },
      })),
      page: response.data.pagination.page,
      pages: response.data.pagination.pages,
    }
  }
  const response = await api.publicAssetLibrary(props.assetType, nextPage, search.value.trim())
  return {
    items: publicAssetItems(response.data.items),
    page: response.data.pagination.page,
    pages: response.data.pagination.pages,
  }
}

async function load(reset = true) {
  if (loading.value || loadingMore.value) return
  const requestScope = scope.value
  const version = ++loadVersion
  reset ? loading.value = true : loadingMore.value = true
  try {
    const result = await requestItems(reset ? 1 : page.value + 1, requestScope)
    if (version !== loadVersion || requestScope !== scope.value) return
    items.value = reset ? result.items : [...items.value, ...result.items.filter(next => !items.value.some(current => current.key === next.key))]
    page.value = result.page
    pages.value = result.pages
  } finally {
    if (version === loadVersion) {
      loading.value = false
      loadingMore.value = false
    }
  }
}

function changeScope(nextScope: AssetScope) {
  if (scope.value === nextScope) return
  loadVersion += 1
  loading.value = false
  loadingMore.value = false
  scope.value = nextScope
  items.value = []
  page.value = 1
  pages.value = 1
  void load()
}

function choose(choice: ReusableAssetChoice) {
  emit('choose', choice)
  emit('close')
}

watch(() => [props.open, props.assetType] as const, ([open]) => {
  if (!open) return
  loadVersion += 1
  loading.value = false
  loadingMore.value = false
  search.value = ''
  scope.value = props.assetType === AssetTypeEnum.PERSON ? 'public' : 'project'
  items.value = []
  void load()
}, { immediate: true })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="project-asset-picker-backdrop" @click.self="emit('close')">
      <section class="project-asset-picker" role="dialog" aria-modal="true" aria-labelledby="project-asset-picker-title">
        <header>
          <div>
            <h2 id="project-asset-picker-title">选择{{ typeLabel }}资产</h2>
            <p>只显示与当前节点类型一致的资产。</p>
          </div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭" @click="emit('close')"><X :size="18" /></AppButton>
        </header>
        <nav class="project-asset-picker__scope" aria-label="资产范围">
          <button type="button" :class="{ 'is-active': scope === 'public' }" :aria-pressed="scope === 'public'" @click="changeScope('public')"><Library :size="15" />公共资产</button>
          <button type="button" :class="{ 'is-active': scope === 'project' }" :aria-pressed="scope === 'project'" @click="changeScope('project')"><FolderKanban :size="15" />项目资产</button>
        </nav>
        <form class="project-asset-picker__search" @submit.prevent="load()">
          <Search :size="16" />
          <input v-model="search" type="search" :placeholder="searchLabel" :aria-label="searchLabel">
          <AppButton type="submit" variant="secondary" size="sm">搜索</AppButton>
        </form>
        <div class="project-asset-picker__grid">
          <p v-if="loading" class="project-asset-picker__state">正在读取{{ scope === 'public' ? '公共' : '项目' }}资产…</p>
          <button v-for="item in items" v-else :key="item.key" type="button" @click="choose(item.choice)">
            <span class="project-asset-picker__thumb">
              <img v-if="item.image" :src="item.image" :alt="item.name" loading="lazy">
              <component :is="fallbackIcon()" v-else :size="22" />
            </span>
            <span><strong>{{ item.name }}</strong><small>{{ item.detail }}</small></span>
          </button>
          <p v-if="!loading && !items.length" class="project-asset-picker__state">暂无可复用的{{ typeLabel }}{{ scope === 'public' ? '公共' : '项目' }}资产</p>
        </div>
        <footer>
          <span>已加载 {{ items.length }} 个{{ typeLabel }}资产</span>
          <AppButton v-if="page < pages" type="button" variant="secondary" size="sm" :loading="loadingMore" @click="load(false)">加载更多</AppButton>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.project-asset-picker-backdrop { position: fixed; z-index: 1400; inset: 0; display: grid; padding: 24px; place-items: center; background: rgb(8 9 13 / 72%); backdrop-filter: blur(10px); }
.project-asset-picker { display: grid; width: min(880px,94vw); max-height: min(720px,88vh); overflow: hidden; border: 1px solid var(--app-border, #403a35); border-radius: 18px; color: var(--app-text, #eee9e4); background: var(--app-surface, #211e1b); box-shadow: 0 28px 80px rgb(0 0 0 / 45%); }
.project-asset-picker > header,.project-asset-picker > footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 17px 20px; }
.project-asset-picker > header { border-bottom: 1px solid var(--app-border, #37322e); }
.project-asset-picker h2,.project-asset-picker p { margin: 0; }
.project-asset-picker h2 { font-size: 17px; }
.project-asset-picker header p,.project-asset-picker footer { margin-top: 4px; color: var(--app-text-muted, #9a9087); font-size: 11px; }
.project-asset-picker__scope { display: flex; gap: 6px; padding: 12px 20px 0; }
.project-asset-picker__scope button { display: inline-flex; height: 32px; align-items: center; gap: 6px; padding: 0 12px; border: 1px solid var(--app-border, #48413b); border-radius: 9px; color: var(--app-text-muted, #9a9087); background: transparent; cursor: pointer; font-size: 11px; }
.project-asset-picker__scope button.is-active { border-color: var(--app-accent, #7567a1); color: var(--app-text, #eee9e4); background: color-mix(in srgb, var(--app-accent, #7567a1) 18%, transparent); }
.project-asset-picker__search { display: flex; align-items: center; gap: 9px; margin: 12px 20px 0; padding: 0 8px 0 12px; border: 1px solid var(--app-border, #48413b); border-radius: 10px; background: var(--app-canvas, #171513); }
.project-asset-picker__search input { min-width: 0; height: 40px; flex: 1; border: 0; color: var(--app-text, #eee9e4); outline: 0; background: transparent; }
.project-asset-picker__grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; min-height: 240px; padding: 14px 20px; overflow: auto; }
.project-asset-picker__grid > button { display: grid; grid-template-columns: 60px minmax(0,1fr); align-items: center; gap: 11px; min-height: 72px; padding: 7px; border: 1px solid var(--app-border, #39342f); border-radius: 11px; color: inherit; text-align: left; background: color-mix(in srgb, var(--app-surface, #211e1b) 82%, black); cursor: pointer; }
.project-asset-picker__grid > button:hover,.project-asset-picker__grid > button:focus-visible { border-color: var(--app-accent, #7567a1); outline: 0; background: color-mix(in srgb, var(--app-accent, #7567a1) 13%, var(--app-surface, #211e1b)); }
.project-asset-picker__thumb { display: grid; width: 60px; height: 58px; overflow: hidden; place-items: center; border-radius: 8px; color: var(--app-accent, #9a8df7); background: color-mix(in srgb, var(--app-accent, #7567a1) 16%, var(--app-canvas, #171513)); }
.project-asset-picker__thumb img { width: 100%; height: 100%; object-fit: cover; }
.project-asset-picker__grid strong,.project-asset-picker__grid small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-asset-picker__grid strong { font-size: 12px; }
.project-asset-picker__grid small { margin-top: 5px; color: var(--app-text-muted, #8f867e); font-size: 10px; }
.project-asset-picker__state { grid-column: 1 / -1; display: grid; place-items: center; color: var(--app-text-muted, #8f867e); }
.project-asset-picker > footer { border-top: 1px solid var(--app-border, #37322e); }
@media (max-width: 760px) { .project-asset-picker__grid { grid-template-columns: 1fr; } }
</style>
