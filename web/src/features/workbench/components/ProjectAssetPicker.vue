<script setup lang="ts">
import { Boxes, Image as ImageIcon, Search, UserRound, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import type { Asset } from '@/types'
import { AssetTypeEnum } from '@/types'

const props = defineProps<{
  open: boolean
  novelId: number
  excludedIds?: number[]
}>()
const emit = defineEmits<{
  close: []
  choose: [asset: Asset]
}>()

const items = ref<Asset[]>([])
const search = ref('')
const page = ref(1)
const pages = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const excluded = computed(() => new Set(props.excludedIds || []))
const visibleItems = computed(() => items.value.filter(asset => !excluded.value.has(asset.id)))

function iconFor(asset: Asset) {
  if (asset.asset_type === AssetTypeEnum.PERSON) return UserRound
  if (asset.asset_type === AssetTypeEnum.SCENE) return ImageIcon
  return Boxes
}

async function load(reset = true) {
  if (loading.value || loadingMore.value) return
  reset ? loading.value = true : loadingMore.value = true
  try {
    const nextPage = reset ? 1 : page.value + 1
    const response = await api.projectAssetLibrary(props.novelId, nextPage, search.value.trim())
    items.value = reset ? response.data.items : [...items.value, ...response.data.items]
    page.value = response.data.pagination.page
    pages.value = response.data.pagination.pages
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function choose(asset: Asset) {
  emit('choose', asset)
  emit('close')
}

watch(() => props.open, (open) => {
  if (!open) return
  search.value = ''
  void load()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="project-asset-picker-backdrop" @click.self="emit('close')">
      <section class="project-asset-picker" role="dialog" aria-modal="true" aria-labelledby="project-asset-picker-title">
        <header>
          <div><h2 id="project-asset-picker-title">复用项目资产</h2><p>只把选中的资产加入当前章节画布，不复制资产。</p></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭" @click="emit('close')"><X :size="18" /></AppButton>
        </header>
        <form class="project-asset-picker__search" @submit.prevent="load()">
          <Search :size="16" />
          <input v-model="search" type="search" placeholder="搜索人物、场景或道具" aria-label="搜索项目资产">
          <AppButton type="submit" variant="secondary" size="sm">搜索</AppButton>
        </form>
        <div class="project-asset-picker__grid">
          <p v-if="loading" class="project-asset-picker__state">正在读取项目资产…</p>
          <button v-for="asset in visibleItems" v-else :key="asset.id" type="button" @click="choose(asset)">
            <span class="project-asset-picker__thumb">
              <img v-if="asset.main_image" :src="asset.main_image" :alt="asset.canonical_name" loading="lazy">
              <component :is="iconFor(asset)" v-else :size="22" />
            </span>
            <span><strong>{{ asset.canonical_name }}</strong><small>{{ asset.description || '暂无描述' }}</small></span>
          </button>
          <p v-if="!loading && !visibleItems.length" class="project-asset-picker__state">没有可复用的资产</p>
        </div>
        <footer>
          <span>已加载 {{ visibleItems.length }} 个</span>
          <AppButton v-if="page < pages" type="button" variant="secondary" size="sm" :loading="loadingMore" @click="load(false)">加载更多</AppButton>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.project-asset-picker-backdrop { position: fixed; z-index: 1400; inset: 0; display: grid; padding: 24px; place-items: center; background: rgb(8 9 13 / 72%); backdrop-filter: blur(10px); }
.project-asset-picker { display: grid; width: min(880px,94vw); max-height: min(720px,88vh); overflow: hidden; border: 1px solid #403a35; border-radius: 18px; color: #eee9e4; background: #211e1b; box-shadow: 0 28px 80px rgb(0 0 0 / 45%); }
.project-asset-picker > header,.project-asset-picker > footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 17px 20px; }
.project-asset-picker > header { border-bottom: 1px solid #37322e; }
.project-asset-picker h2,.project-asset-picker p { margin: 0; }
.project-asset-picker h2 { font-size: 17px; }
.project-asset-picker header p,.project-asset-picker footer { margin-top: 4px; color: #9a9087; font-size: 11px; }
.project-asset-picker__search { display: flex; align-items: center; gap: 9px; margin: 14px 20px 0; padding: 0 8px 0 12px; border: 1px solid #48413b; border-radius: 10px; background: #171513; }
.project-asset-picker__search input { min-width: 0; height: 40px; flex: 1; border: 0; color: #eee9e4; outline: 0; background: transparent; }
.project-asset-picker__grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; min-height: 240px; padding: 14px 20px; overflow: auto; }
.project-asset-picker__grid > button { display: grid; grid-template-columns: 60px minmax(0,1fr); align-items: center; gap: 11px; min-height: 72px; padding: 7px; border: 1px solid #39342f; border-radius: 11px; color: inherit; text-align: left; background: #191715; cursor: pointer; }
.project-asset-picker__grid > button:hover,.project-asset-picker__grid > button:focus-visible { border-color: #7567a1; outline: 0; background: #282229; }
.project-asset-picker__thumb { display: grid; width: 60px; height: 58px; overflow: hidden; place-items: center; border-radius: 8px; color: #9a8df7; background: #29252f; }
.project-asset-picker__thumb img { width: 100%; height: 100%; object-fit: cover; }
.project-asset-picker__grid strong,.project-asset-picker__grid small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-asset-picker__grid strong { font-size: 12px; }
.project-asset-picker__grid small { margin-top: 5px; color: #8f867e; font-size: 10px; }
.project-asset-picker__state { grid-column: 1 / -1; display: grid; place-items: center; color: #8f867e; }
.project-asset-picker > footer { border-top: 1px solid #37322e; }
@media (max-width: 760px) { .project-asset-picker__grid { grid-template-columns: 1fr; } }
</style>
