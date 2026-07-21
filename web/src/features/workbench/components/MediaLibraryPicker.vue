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

function assetId(item: LibraryItem) { return item.asset_id }
function name(item: LibraryItem) { return 'nickname' in item ? item.nickname : `${item.country} · ${item.occupation}` }
function detail(item: LibraryItem) { return 'audio_url' in item ? item.gender : `${item.age} 岁 · ${item.gender}` }
function preview(item: LibraryItem) { return 'avatar_url' in item ? item.avatar_url : item.image_url }

async function load(reset = false) {
  if (loading.value) return
  if (reset) { page.value = 1; items.value = [] }
  loading.value = true; error.value = ''
  try {
    const response = props.kind === 'audio' ? await api.audioReferences(page.value, search.value.trim()) : await api.digitalHumans(page.value, search.value.trim())
    items.value = reset ? response.data.items : [...items.value, ...response.data.items]
    pages.value = response.data.pagination.pages
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '资源库加载失败' }
  finally { loading.value = false }
}
function submitSearch() { load(true) }
function loadMore() { if (page.value < pages.value) { page.value += 1; load() } }
watch(() => props.open, value => { if (value) load(true) })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="media-picker-backdrop" role="presentation" @mousedown.self="$emit('close')">
      <section class="media-picker" role="dialog" aria-modal="true" :aria-label="title">
        <header><div><h2>{{ title }}</h2><p>{{ kind === 'audio' ? '从音频库选择稳定参考音色' : '仅展示纯数字人资产，不包含真人' }}</p></div><AppButton type="button" aria-label="关闭" @click="$emit('close')"><X :size="18" /></AppButton></header>
        <form class="media-picker-search" @submit.prevent="submitSearch"><Search :size="16" /><input v-model="search" :placeholder="kind === 'audio' ? '搜索昵称、性别或资产 ID' : '搜索国家、职业、性别或资产 ID'" autofocus><AppButton type="submit">搜索</AppButton></form>
        <p v-if="error" class="media-picker-error" role="alert">{{ error }}</p>
        <div class="media-picker-grid">
          <AppButton v-for="item in items" :key="assetId(item)" type="button" :class="{ 'is-selected': selectedAssetId === assetId(item) }" @click="$emit('choose', item)">
            <img :src="preview(item)" alt="" loading="lazy"><span><strong>{{ name(item) }}</strong><small>{{ detail(item) }}</small><code>{{ assetId(item) }}</code></span>
          </AppButton>
        </div>
        <div v-if="!items.length && !loading" class="media-picker-empty">没有匹配的资源</div>
        <footer><span>第 {{ page }} / {{ pages || 1 }} 页</span><AppButton v-if="page < pages" type="button" :disabled="loading" @click="loadMore"><LoaderCircle v-if="loading" class="is-spinning" :size="15" />加载更多</AppButton></footer>
      </section>
    </div>
  </Teleport>
</template>
