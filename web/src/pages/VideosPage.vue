<script setup lang="ts">
import { Film, Trash2 } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { api, statusLabel } from '@/api'
import { notice } from '@/shared/notice'
import type { Video } from '@/types'
const videos = ref<Video[]>([]); const loading = ref(true)
async function load() { try { videos.value = (await api.videos()).data.items } catch (error) { notice.error((error as Error).message) } finally { loading.value = false } }
async function remove(item: Video) { if (!confirm('删除这个视频？')) return; await api.deleteVideo(item.id); await load() }
onMounted(load)
</script>
<template><main class="page"><header class="page-header"><div><span class="eyebrow">VIDEO LIBRARY</span><h1>视频库</h1><p>查看所有镜头的生成结果</p></div></header><div v-if="loading" class="state">正在加载视频…</div><div v-else-if="videos.length" class="video-grid"><article v-for="item in videos" :key="item.id" class="video-card"><div><video v-if="item.url" :src="item.url" controls preload="metadata" /><Film v-else :size="30" /></div><footer><span><strong>视频 #{{ item.id }}</strong><small>{{ statusLabel(item.status) }}</small></span><button type="button" aria-label="删除视频" @click="remove(item)"><Trash2 :size="15" /></button></footer></article></div><div v-else class="empty-state"><Film :size="32" /><h3>还没有生成视频</h3><p>从章节创作画布生成第一支视频</p></div></main></template>
