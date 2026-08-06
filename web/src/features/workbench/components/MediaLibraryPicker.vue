<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { LoaderCircle, Search, X } from 'lucide-vue-next'
import { api } from '@/api'
import type { AudioReference, DigitalHuman } from '@/types'

type LibraryItem = AudioReference | DigitalHuman
const props = defineProps<{ open: boolean; kind: 'audio' | 'digital-human'; selectedAssetId?: string }>()
const emit = defineEmits<{ close: []; choose: [item: LibraryItem] }>()
const items = ref<LibraryItem[]>([])
const page = ref(1)
const pages = ref(1)
const search = ref('')
const loading = ref(false)
const error = ref('')
const title = computed(() => props.kind === 'audio' ? '选择参考音频' : '选择数字人')
let requestId = 0

function assetId(item: LibraryItem) { return item.asset_id }
function name(item: LibraryItem) { return 'nickname' in item ? item.nickname : `${item.country} · ${item.occupation}` }
function detail(item: LibraryItem) { return 'audio_url' in item ? item.gender : `${item.age} 岁 · ${item.gender}` }
function preview(item: LibraryItem) { return 'avatar_url' in item ? item.avatar_url : item.image_url }

async function load(reset = false) {
  if (loading.value && !reset) return
  const currentRequestId = ++requestId
  if (reset) { page.value = 1; items.value = [] }
  loading.value = true; error.value = ''
  const requestedPage = page.value
  const requestedSearch = search.value.trim()
  try {
    const response = props.kind === 'audio' ? await api.audioReferences(requestedPage, requestedSearch) : await api.digitalHumans(requestedPage, requestedSearch)
    if (currentRequestId !== requestId) return
    items.value = reset ? response.data.items : [...items.value, ...response.data.items]
    pages.value = response.data.pagination.pages
  } catch (reason) {
    if (currentRequestId === requestId) error.value = reason instanceof Error ? reason.message : '资源库加载失败'
  } finally {
    if (currentRequestId === requestId) loading.value = false
  }
}
function submitSearch() { load(true) }
function loadMore() { if (page.value < pages.value) { page.value += 1; load() } }
watch(() => props.open, value => {
  if (value) load(true)
  else {
    requestId += 1
    loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="media-picker-backdrop" role="presentation" @mousedown.self="$emit('close')">
      <section class="media-picker" role="dialog" aria-modal="true" :aria-label="title" :aria-busy="loading" @keydown.esc.stop="$emit('close')">
        <header><div><h2>{{ title }}</h2><p>{{ kind === 'audio' ? '从音频库选择稳定参考音色' : '仅展示纯数字人资产，不包含真人' }}</p></div><AppButton type="button" size="sm" icon-only aria-label="关闭" @click="$emit('close')"><X :size="20" aria-hidden="true" /></AppButton></header>
        <form class="media-picker-search" @submit.prevent="submitSearch"><Search :size="16" aria-hidden="true" /><input v-model="search" :aria-label="kind === 'audio' ? '搜索参考音频' : '搜索数字人'" :placeholder="kind === 'audio' ? '搜索昵称、性别或资产 ID' : '搜索国家、职业、性别或资产 ID'" autofocus><AppButton type="submit" :disabled="loading">搜索</AppButton></form>
        <p v-if="error" class="media-picker-error" role="alert">{{ error }}</p>
        <div class="media-picker-grid">
          <AppButton v-for="item in items" :key="assetId(item)" type="button" :class="{ 'is-selected': selectedAssetId === assetId(item) }" @click="$emit('choose', item)">
            <img :src="preview(item)" alt="" loading="lazy" decoding="async"><span><strong>{{ name(item) }}</strong><small>{{ detail(item) }}</small><code>{{ assetId(item) }}</code></span>
          </AppButton>
        </div>
        <div v-if="loading && !items.length" class="media-picker-empty" role="status"><LoaderCircle class="is-spinning" :size="24" aria-hidden="true" /><span>正在加载资源…</span></div>
        <div v-else-if="!items.length" class="media-picker-empty">没有匹配的资源</div>
        <footer><span>第 {{ page }} / {{ pages || 1 }} 页</span><AppButton v-if="page < pages" type="button" :disabled="loading" @click="loadMore"><LoaderCircle v-if="loading" class="is-spinning" :size="15" aria-hidden="true" />加载更多</AppButton></footer>
      </section>
    </div>
  </Teleport>
</template>
