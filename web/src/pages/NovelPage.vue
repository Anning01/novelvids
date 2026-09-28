<script setup lang="ts">
import { tr } from '@/i18n'

import { ArrowLeft, FileText, Plus, Scissors, Trash2, X } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import type { Chapter, Novel } from '@/types'
const route = useRoute(); const id = Number(route.params.id); const novel = ref<Novel | null>(null); const chapters = ref<Chapter[]>([]); const showCreate = ref(false); const form = ref({ number: 1, name: '', content: '' }); const splitting = ref(false)
async function load() { try { const [a, b] = await Promise.all([api.novel(id), api.chapters(id)]); novel.value = a.data; chapters.value = b.data.items; form.value.number = Math.max(0, ...chapters.value.map(item => item.number)) + 1 } catch (error) { notice.error((error as Error).message) } }
async function create() { await api.createChapter({ ...form.value, novel_id: id }); showCreate.value = false; await load(); notice.success(tr('章节已创建')) }
async function split() { splitting.value = true; try { await api.splitNovel(id); await load(); notice.success(tr('章节拆分完成')) } catch (error) { notice.error((error as Error).message) } finally { splitting.value = false } }
async function remove(item: Chapter) {
  if (!await appConfirm({
    title: tr('删除第 {p0} 章？', { p0: item.number }),
    get message() { return tr('本章内容及相关创作数据将被删除，且无法恢复。') },
    get confirmLabel() { return tr('删除章节') },
    tone: 'danger',
  })) return
  await api.deleteChapter(item.id)
  await load()
}
onMounted(load)
</script>
<template><main class="page"><header class="page-header"><div class="title-with-back"><RouterLink to="/projects" class="icon-button"><ArrowLeft :size="18" /></RouterLink><div><span class="eyebrow">NOVEL</span><h1>{{ novel?.name || tr('加载中…') }}</h1><p>{{ novel?.description || tr('管理章节并进入创作流程') }}</p></div></div><div class="header-actions"><AppButton v-if="novel?.content" variant="secondary" :disabled="splitting" @click="split"><Scissors :size="15" />{{ splitting ? tr('拆分中…') : tr('智能拆章') }}</AppButton><AppButton variant="primary" @click="showCreate = true"><Plus :size="15" />{{ tr('新建章节') }}</AppButton></div></header><div class="chapter-list"><RouterLink v-for="item in chapters" :key="item.id" :to="`/novel/${id}/chapter/${item.id}/step/1`" class="chapter-row"><span class="chapter-number">{{ String(item.number).padStart(2, '0') }}</span><div><h3>{{ item.name }}</h3><p>{{ item.content || tr('本章暂无正文内容') }}</p></div><span class="chapter-enter">{{ tr('进入制作') }}</span><AppButton type="button" variant="danger" size="sm" icon-only :aria-label="tr('删除章节')" @click.prevent="remove(item)"><Trash2 :size="15" /></AppButton></RouterLink></div><div v-if="!chapters.length" class="empty-state"><FileText :size="30" /><h3>{{ tr('还没有章节') }}</h3><AppButton variant="secondary" @click="showCreate = true">{{ tr('添加章节') }}</AppButton></div><div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false"><form class="modal" @submit.prevent="create"><header><h2>{{ tr('新建章节') }}</h2><AppButton type="button" variant="ghost" size="sm" icon-only @click="showCreate = false"><X :size="18" /></AppButton></header><label>{{ tr('章节序号') }}<input v-model.number="form.number" type="number" min="1"></label><label>{{ tr('章节名称') }}<input v-model="form.name" required></label><label>{{ tr('正文') }}<textarea v-model="form.content" rows="12" /></label><footer><AppButton type="button" variant="secondary" @click="showCreate = false">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary">{{ tr('创建章节') }}</AppButton></footer></form></div></main></template>
