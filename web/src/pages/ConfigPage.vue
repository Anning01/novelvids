<script setup lang="ts">
import { Plus, Power, Settings, Trash2, X } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import type { AiModelConfig, EnumItem } from '@/types'
const configs = ref<AiModelConfig[]>([]); const taskTypes = ref<EnumItem[]>([]); const showCreate = ref(false); const form = ref({ task_type: 1, name: '', base_url: '', api_key: '', model: '', concurrency: 1 })
async function load() { try { const [a, b] = await Promise.all([api.configs(), api.enums()]); configs.value = a.data.items; taskTypes.value = b.data.ai_task_type || [] } catch (error) { notice.error((error as Error).message) } }
async function create() { await api.createConfig(form.value); showCreate.value = false; await load(); notice.success('模型配置已创建') }
async function activate(item: AiModelConfig) { await api.activateConfig(item.id); await load(); notice.success('配置已启用') }
async function remove(item: AiModelConfig) { if (!confirm(`删除「${item.name}」？`)) return; await api.deleteConfig(item.id); await load() }
const taskLabel = (value: number) => taskTypes.value.find(item => item.value === value)?.label || `任务 ${value}`
onMounted(load)
</script>
<template><main class="page"><header class="page-header"><div><span class="eyebrow">MODEL SETTINGS</span><h1>模型配置</h1><p>管理各创作阶段使用的模型能力</p></div><button class="button is-primary" @click="showCreate = true"><Plus :size="16" />添加配置</button></header><div class="config-list"><article v-for="item in configs" :key="item.id" class="config-row"><span class="config-icon"><Settings :size="18" /></span><div><h3>{{ item.name }}</h3><p>{{ taskLabel(item.task_type) }} · {{ item.model || '未设置模型' }}</p></div><span class="status-pill" :class="{ 'is-active': item.is_active }">{{ item.is_active ? '已启用' : '未启用' }}</span><button v-if="!item.is_active" class="icon-button" title="启用" @click="activate(item)"><Power :size="15" /></button><button class="icon-button" title="删除" @click="remove(item)"><Trash2 :size="15" /></button></article></div><div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false"><form class="modal" @submit.prevent="create"><header><h2>添加模型配置</h2><button type="button" @click="showCreate = false"><X :size="18" /></button></header><label>任务类型<select v-model.number="form.task_type"><option v-for="item in taskTypes" :key="item.value" :value="item.value">{{ item.label }}</option></select></label><label>配置名称<input v-model="form.name" required></label><label>Base URL<input v-model="form.base_url"></label><label>API Key<input v-model="form.api_key" type="password"></label><label>模型名称<input v-model="form.model"></label><label>并发数<input v-model.number="form.concurrency" type="number" min="1"></label><footer><button type="button" class="button" @click="showCreate = false">取消</button><button class="button is-primary">创建配置</button></footer></form></div></main></template>
