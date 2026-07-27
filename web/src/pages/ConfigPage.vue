<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Bot,
  CheckCircle2,
  Eye,
  EyeOff,
  Image,
  KeyRound,
  Pencil,
  Plus,
  Power,
  Server,
  Settings2,
  Trash2,
  Video,
  X,
  Zap,
} from 'lucide-vue-next'
import AppMultiSelect from '@/components/AppMultiSelect.vue'
import AppIconTile from '@/components/AppIconTile.vue'
import { api } from '@/api'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import type { AiModelConfig, EnumItem } from '@/types'

type ModelCategoryId = 'llm' | 'image' | 'video'

interface ModelCategory {
  id: ModelCategoryId
  label: string
  eyebrow: string
  description: string
  taskTypes: number[]
  icon: typeof Bot
}

const categories: ModelCategory[] = [
  {
    id: 'llm',
    label: 'LLM 大模型',
    eyebrow: 'LANGUAGE',
    description: '负责剧本理解、人物提取、分集规划与分镜文本生成。',
    taskTypes: [1, 3],
    icon: Bot,
  },
  {
    id: 'image',
    label: '生图模型',
    eyebrow: 'IMAGE',
    description: '负责角色定妆、场景概念图和一致性参考图生成。',
    taskTypes: [2],
    icon: Image,
  },
  {
    id: 'video',
    label: '视频模型',
    eyebrow: 'VIDEO',
    description: '负责分镜片段生成、动态镜头和最终视频合成。',
    taskTypes: [4],
    icon: Video,
  },
]

const configs = ref<AiModelConfig[]>([])
const taskTypes = ref<EnumItem[]>([])
const loading = ref(true)
const showCreate = ref(false)
const creating = ref(false)
const editingConfigId = ref<number | null>(null)
const showApiKey = ref(false)
const selectedCategoryId = ref<ModelCategoryId>('llm')
const form = ref({ task_types: ['1'], name: '', base_url: '', api_key: '', model: '', concurrency: 1, supports_json_output: false })

function configTaskTypes(item: AiModelConfig) {
  return item.task_types?.length ? item.task_types : [item.task_type]
}

const selectedCategory = computed(() => categories.find(item => item.id === selectedCategoryId.value) ?? categories[0])
const isEditing = computed(() => editingConfigId.value !== null)
const selectedConfigs = computed(() => configs.value.filter(item => configTaskTypes(item).some(value => selectedCategory.value.taskTypes.includes(value))))
const taskOptions = computed(() => selectedCategory.value.taskTypes.map(value => ({
  value: String(value),
  label: taskTypes.value.find(item => item.value === value)?.label || ({ 1: '内容理解与人物提取', 2: '角色与场景参考图', 3: '分镜规划与提示词', 4: '视频片段生成' }[value] ?? `任务 ${value}`),
})))

function iconTone(categoryId: ModelCategoryId) {
  if (categoryId === 'image') return 'image' as const
  if (categoryId === 'video') return 'video' as const
  return 'accent' as const
}

function configsFor(category: ModelCategory) {
  return configs.value.filter(item => configTaskTypes(item).some(value => category.taskTypes.includes(value)))
}

function activeCount(category: ModelCategory) {
  return new Set(configsFor(category)
    .filter(item => item.is_active)
    .flatMap(item => configTaskTypes(item).filter(value => category.taskTypes.includes(value))))
    .size
}

function taskLabel(value: number) {
  return taskTypes.value.find(item => item.value === value)?.label || ({ 1: '内容理解', 2: '参考图生成', 3: '分镜规划', 4: '视频生成' }[value] ?? `任务 ${value}`)
}

function providerHost(baseUrl?: string) {
  if (!baseUrl) return '未设置接口'
  try {
    return new URL(baseUrl).host
  } catch {
    return baseUrl
  }
}

async function load() {
  loading.value = true
  try {
    const [configResponse, enumResponse] = await Promise.all([api.configs(), api.enums()])
    configs.value = configResponse.data.items
    taskTypes.value = enumResponse.data.ai_task_type || []
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function openCreate(categoryId: ModelCategoryId = selectedCategoryId.value) {
  selectedCategoryId.value = categoryId
  const category = categories.find(item => item.id === categoryId) ?? categories[0]
  form.value = { task_types: category.taskTypes.map(String), name: '', base_url: '', api_key: '', model: '', concurrency: 1, supports_json_output: false }
  editingConfigId.value = null
  showApiKey.value = false
  showCreate.value = true
}

function openEdit(item: AiModelConfig) {
  const category = categories.find(value => value.taskTypes.includes(item.task_type)) ?? categories[0]
  selectedCategoryId.value = category.id
  editingConfigId.value = item.id
  showApiKey.value = false
  form.value = {
    task_types: configTaskTypes(item).map(String),
    name: item.name,
    base_url: item.base_url || '',
    api_key: item.api_key || '',
    model: item.model || '',
    concurrency: item.concurrency,
    supports_json_output: item.supports_json_output ?? false,
  }
  showCreate.value = true
}

async function saveConfig() {
  if (!form.value.task_types.length) {
    notice.error('请至少选择一个能力用途')
    return
  }
  creating.value = true
  try {
    const taskTypes = form.value.task_types.map(Number)
    const payload = { ...form.value, task_type: taskTypes[0], task_types: taskTypes }
    if (editingConfigId.value !== null) {
      await api.updateConfig(editingConfigId.value, payload)
    } else {
      await api.createConfig(payload)
    }
    showCreate.value = false
    await load()
    notice.success(isEditing.value ? '模型配置已更新' : '模型配置已创建')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    creating.value = false
  }
}

async function activate(item: AiModelConfig) {
  try {
    await api.activateConfig(item.id)
    await load()
    notice.success(`已启用 ${item.name}`)
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function remove(item: AiModelConfig) {
  if (!await appConfirm({
    title: `删除模型配置「${item.name}」？`,
    message: '删除后该模型将无法继续用于新的生成任务。',
    confirmLabel: '删除配置',
    tone: 'danger',
  })) return
  try {
    await api.deleteConfig(item.id)
    await load()
    notice.success('模型配置已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <main class="model-settings-page">
    <header class="model-settings-header">
      <div>
        <span>MODEL CAPABILITIES</span>
        <h1>模型配置</h1>
        <p>按创作能力管理模型，分别服务于文本理解、视觉生成与动态视频。</p>
      </div>
      <AppButton variant="primary" size="lg" type="button" @click="openCreate()"><Plus :size="16" />添加模型</AppButton>
    </header>

    <section class="model-category-grid" aria-label="模型能力分类">
      <AppButton
        v-for="category in categories"
        :key="category.id"
        type="button"
        variant="ghost"
        :active="selectedCategoryId === category.id"
        class="model-category-card"
        :class="[`is-${category.id}`, { 'is-active': selectedCategoryId === category.id }]"
        :aria-pressed="selectedCategoryId === category.id"
        @click="selectedCategoryId = category.id"
      >
        <AppIconTile :tone="iconTone(category.id)" size="lg"><component :is="category.icon" :size="22" /></AppIconTile>
        <span class="category-copy"><small>{{ category.eyebrow }}</small><strong>{{ category.label }}</strong><p>{{ category.description }}</p></span>
        <span class="category-status"><i :class="{ 'is-ready': activeCount(category) }" />{{ activeCount(category) ? `${activeCount(category)} 个用途已就绪` : '尚未启用' }}</span>
      </AppButton>
    </section>

    <section class="model-config-section">
      <header>
        <div>
          <span>{{ selectedCategory.eyebrow }} MODELS</span>
          <h2>{{ selectedCategory.label }}</h2>
          <p>{{ selectedCategory.description }}</p>
        </div>
        <AppButton variant="secondary" size="sm" type="button" @click="openCreate(selectedCategory.id)"><Plus :size="15" />添加{{ selectedCategory.label }}</AppButton>
      </header>

      <div v-if="loading" class="model-state">正在读取模型配置…</div>
      <div v-else-if="selectedConfigs.length" class="model-config-list">
        <article v-for="item in selectedConfigs" :key="item.id" class="model-config-card" :class="{ 'is-active': item.is_active }">
          <AppIconTile :tone="iconTone(selectedCategory.id)"><component :is="selectedCategory.icon" :size="19" /></AppIconTile>
          <div class="config-main">
            <div class="config-title"><h3>{{ item.name }}</h3><span :class="{ 'is-active': item.is_active }">{{ item.is_active ? '当前启用' : '备用配置' }}</span></div>
            <p>{{ configTaskTypes(item).map(taskLabel).join(' · ') }}</p>
            <div class="config-metadata">
              <span><Settings2 :size="13" />{{ item.model || '未设置模型名称' }}</span>
              <span><Server :size="13" />{{ providerHost(item.base_url) }}</span>
              <span><Zap :size="13" />并发 {{ item.concurrency }}</span>
              <span v-if="selectedCategory.id === 'llm'">{{ item.supports_json_output ? 'JSON 格式化' : '提示词 JSON' }}</span>
            </div>
          </div>
          <div class="config-actions">
            <AppButton v-if="!item.is_active" variant="soft" size="sm" type="button" title="启用配置" @click="activate(item)"><Power :size="15" /><span>启用</span></AppButton>
            <span v-else class="active-check"><CheckCircle2 :size="16" />运行中</span>
            <span class="config-icon-actions">
              <AppButton variant="secondary" size="sm" icon-only type="button" aria-label="编辑配置" title="编辑配置" @click="openEdit(item)"><Pencil :size="15" /></AppButton>
              <AppButton variant="danger" size="sm" icon-only type="button" aria-label="删除配置" title="删除配置" @click="remove(item)"><Trash2 :size="15" /></AppButton>
            </span>
          </div>
        </article>
      </div>
      <div v-else class="model-empty-state">
        <span><component :is="selectedCategory.icon" :size="25" /></span>
        <h3>还没有{{ selectedCategory.label }}</h3>
        <p>{{ selectedCategory.description }}</p>
        <AppButton variant="primary" size="sm" type="button" @click="openCreate(selectedCategory.id)"><Plus :size="15" />添加第一个配置</AppButton>
      </div>
    </section>

    <div v-if="showCreate" class="model-modal-backdrop" @click.self="showCreate = false">
      <form class="model-modal" autocomplete="off" @submit.prevent="saveConfig">
        <header>
          <div><AppIconTile :tone="iconTone(selectedCategory.id)" size="sm"><component :is="selectedCategory.icon" :size="18" /></AppIconTile><div><small>{{ isEditing ? 'EDIT MODEL' : 'ADD MODEL' }}</small><h2>{{ isEditing ? '编辑' : '添加' }}{{ selectedCategory.label }}</h2></div></div>
          <AppButton variant="soft" size="sm" icon-only type="button" aria-label="关闭" @click="showCreate = false"><X :size="18" /></AppButton>
        </header>

        <div class="model-form-grid">
          <label v-if="selectedCategory.taskTypes.length > 1" class="is-full">
            <span>能力用途</span>
            <AppMultiSelect v-model="form.task_types" ariaLabel="能力用途" :options="taskOptions" />
            <small>可同时选择多个用途，同一个 LLM 能用于内容理解和分镜规划。</small>
          </label>
          <label class="is-full"><span>配置名称</span><input v-model="form.name" name="model-config-name" required autocomplete="off" placeholder="例如：豆包 Seed 1.6" /></label>
          <label class="is-full"><span>Base URL</span><span class="input-with-icon"><Server :size="15" /><input v-model="form.base_url" name="model-service-base-url" required autocomplete="off" inputmode="url" spellcheck="false" placeholder="https://api.example.com/v1" /></span></label>
          <label class="is-full">
            <span>API Key</span>
            <span class="input-with-icon secret-input">
              <KeyRound :size="15" />
              <input v-model="form.api_key" name="model-service-api-key" :type="showApiKey ? 'text' : 'password'" required autocomplete="new-password" autocapitalize="none" spellcheck="false" placeholder="输入模型服务密钥" />
              <AppButton variant="ghost" size="sm" icon-only type="button" :aria-label="showApiKey ? '隐藏 API Key' : '显示 API Key'" :title="showApiKey ? '隐藏 API Key' : '显示 API Key'" @click="showApiKey = !showApiKey">
                <EyeOff v-if="showApiKey" :size="16" />
                <Eye v-else :size="16" />
              </AppButton>
            </span>
          </label>
          <label><span>模型名称</span><input v-model="form.model" name="model-id" required autocomplete="off" spellcheck="false" placeholder="模型 ID" /></label>
          <label><span>并发数</span><input v-model.number="form.concurrency" name="model-concurrency" type="number" min="1" required /></label>
          <label v-if="selectedCategory.id === 'llm'" class="is-full json-capability-field">
            <span class="json-capability-copy">
              <strong>结构化 JSON 输出</strong>
              <small>开启后发送 response_format=json_object；关闭后仅使用提示词约束 JSON。</small>
            </span>
            <input v-model="form.supports_json_output" type="checkbox" role="switch" aria-label="结构化 JSON 输出" />
          </label>
        </div>

        <footer><AppButton variant="secondary" size="sm" type="button" @click="showCreate = false">取消</AppButton><AppButton variant="primary" size="sm" type="submit" :loading="creating">{{ creating ? '保存中…' : (isEditing ? '保存修改' : '创建配置') }}</AppButton></footer>
      </form>
    </div>
  </main>
</template>

<style scoped>
.model-settings-page { min-height: 100%; padding: 36px 22px 80px; color: #303442; background: #fff; }
.model-settings-header { display: flex; width: 100%; align-items: flex-start; justify-content: space-between; gap: 24px; margin: 0 0 28px; padding-bottom: 28px; border-bottom: 1px solid #eceef3; }
.model-settings-header > div, .model-config-section > header > div { display: grid; gap: 5px; }
.model-settings-header span, .model-config-section > header > div > span { color: #686af0; font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.model-settings-header h1 { margin: 0; color: #252937; font-size: clamp(28px, 3vw, 38px); letter-spacing: -.035em; }
.model-settings-header p, .model-config-section > header p { margin: 0; color: #848a9a; font-size: 12px; line-height: 1.6; }
.settings-primary-button, .model-config-section > header > button, .model-empty-state button { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; padding: 0 14px; border: 1px solid #5b5cf6; border-radius: 10px; color: #fff; background: #5b5cf6; box-shadow: 0 8px 20px rgb(91 92 246 / 18%); cursor: pointer; font-size: 12px; font-weight: 600; }
.settings-primary-button:hover, .model-config-section > header > button:hover, .model-empty-state button:hover { background: #4d4ee8; }
.model-category-grid { display: grid; width: 100%; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0; }
.model-category-card { position: relative; display: grid; min-height: 158px; grid-template-columns: 46px minmax(0, 1fr); align-content: start; gap: 13px; padding: 18px; overflow: hidden; border: 1px solid #e6e8ef; border-radius: 15px; color: #303442; background: #fff; cursor: pointer; text-align: left; box-shadow: 0 10px 30px rgb(37 41 57 / 4%); transition: border-color .16s ease, transform .16s ease, box-shadow .16s ease; }
.model-category-card:hover { border-color: #d6d9e5; box-shadow: 0 14px 34px rgb(37 41 57 / 7%); transform: translateY(-1px); }
.model-category-card.is-active { border-color: #bfc1ff; box-shadow: 0 14px 34px rgb(91 92 246 / 10%); }
.category-copy { display: grid; gap: 4px; }
.category-copy small { color: #989dac; font-size: 8px; font-weight: 750; letter-spacing: .14em; }
.category-copy strong { font-size: 14px; }
.category-copy p { margin: 1px 0 0; color: #7d8393; font-size: 10px; line-height: 1.55; }
.category-status { display: inline-flex; grid-column: 1 / -1; align-items: center; gap: 6px; align-self: end; color: #8c91a0; font-size: 9px; }
.category-status i { width: 7px; height: 7px; border-radius: 50%; background: #d3d6de; }
.category-status i.is-ready { background: #43a77d; box-shadow: 0 0 0 3px #eaf6f1; }
.model-config-section { width: 100%; margin: 38px 0 0; }
.model-config-section > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 14px; }
.model-config-section > header h2 { margin: 0; font-size: 18px; }
.model-config-section > header > button { min-height: 36px; border-color: #e0e3eb; color: #575d6e; background: #fff; box-shadow: none; }
.model-config-section > header > button:hover { border-color: #cfd2dd; color: #343948; background: #f8f9fb; }
.model-config-list { display: grid; gap: 9px; }
.model-config-card { display: grid; min-height: 96px; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 14px; padding: 15px 16px; border: 1px solid #e5e7ee; border-radius: 13px; background: #fff; transition: border-color .15s ease, box-shadow .15s ease; }
.model-config-card.is-active { border-color: #d5d6fb; box-shadow: 0 10px 26px rgb(91 92 246 / 6%); }
.config-main { display: grid; min-width: 0; gap: 5px; }
.config-title { display: flex; align-items: center; gap: 8px; }
.config-title h3 { margin: 0; font-size: 13px; }
.config-title span { padding: 3px 6px; border-radius: 999px; color: #858a99; background: #f0f1f4; font-size: 8px; }
.config-title span.is-active { color: #258662; background: #e8f6f0; }
.config-main > p { margin: 0; color: #777cf0; font-size: 9px; }
.config-metadata { display: flex; min-width: 0; flex-wrap: wrap; gap: 8px 14px; color: #8a8f9f; font-size: 9px; }
.config-metadata span { display: inline-flex; min-width: 0; align-items: center; gap: 5px; }
.config-metadata span:first-child { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.config-actions { display: flex; align-items: center; gap: 7px; }
.config-icon-actions { display: inline-flex; align-items: center; gap: 5px; }
.config-actions button { display: inline-flex; min-height: 34px; align-items: center; justify-content: center; gap: 5px; padding: 0 9px; border: 1px solid #e0e3ea; border-radius: 8px; color: #666c7c; background: #fff; cursor: pointer; font-size: 10px; }
.config-actions button:hover { border-color: #cfd3df; background: #f8f9fb; }
.config-actions .icon-only-action { width: 34px; padding: 0; }
.config-actions .delete-config { width: 34px; padding: 0; color: #9a7b7b; }
.config-actions .delete-config:hover { color: #cf6259; background: #fff5f4; }
.active-check { display: inline-flex; align-items: center; gap: 5px; color: #328966; font-size: 10px; }
.model-state, .model-empty-state { display: grid; min-height: 260px; place-items: center; align-content: center; gap: 8px; border: 1px dashed #e1e4eb; border-radius: 14px; color: #9095a4; font-size: 11px; text-align: center; }
.model-empty-state > span { display: grid; width: 50px; height: 50px; margin-bottom: 4px; place-items: center; border-radius: 14px; color: #6b6def; background: #eff0ff; }
.model-empty-state h3 { margin: 0; color: #434858; font-size: 14px; }
.model-empty-state p { max-width: 360px; margin: 0 0 8px; color: #8d92a1; font-size: 10px; line-height: 1.6; }
.model-empty-state button { min-height: 36px; }
.model-modal-backdrop { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 20px; background: rgb(8 9 12 / 64%); backdrop-filter: blur(8px); }
.model-modal { display: grid; width: min(600px, 100%); max-height: calc(100vh - 40px); gap: 20px; overflow: auto; padding: 22px; border: 1px solid var(--app-border); border-radius: 17px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 24px 70px rgb(0 0 0 / 28%); }
.model-modal > header, .model-modal > footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.model-modal > header > div { display: flex; align-items: center; gap: 11px; }
.model-modal header small { color: var(--app-accent); font-size: 8px; font-weight: 750; letter-spacing: .14em; }
.model-modal h2 { margin: 3px 0 0; font-size: 17px; }
.model-modal header > button { display: grid; width: 34px; height: 34px; place-items: center; border: 0; border-radius: 8px; cursor: pointer; }
.model-form-grid { display: grid; grid-template-columns: 1fr 140px; gap: 13px; }
.model-form-grid label { display: grid; gap: 7px; color: var(--app-text-secondary); font-size: 10px; }
.model-form-grid label.is-full { grid-column: 1 / -1; }
.model-form-grid label > span:first-child { font-weight: 600; }
.model-form-grid label > small { color: var(--app-text-muted); font-size: 9px; }
.model-form-grid input { width: 100%; min-height: 39px; padding: 0 11px; border: 1px solid var(--app-border); border-radius: 9px; outline: 0; color: var(--app-text); background: var(--app-surface-muted); caret-color: var(--app-text); font-size: 11px; transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease; }
.model-form-grid input::placeholder { color: var(--app-text-muted); opacity: 1; }
.model-form-grid input:hover { border-color: var(--app-border-strong); }
.model-form-grid input:focus { border-color: var(--app-accent); color: var(--app-text); background: var(--app-surface-hover); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.model-form-grid input:-webkit-autofill,
.model-form-grid input:-webkit-autofill:hover,
.model-form-grid input:-webkit-autofill:focus { border-color: var(--app-border-strong); -webkit-text-fill-color: var(--app-text); caret-color: var(--app-text); box-shadow: 0 0 0 1000px var(--app-surface-muted) inset; }
.json-capability-field { display: flex !important; min-height: 64px; flex-direction: row; align-items: center; justify-content: space-between; gap: 16px !important; padding: 12px 14px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.json-capability-copy { display: grid; gap: 4px; }
.json-capability-copy strong { color: var(--app-text); font-size: 11px; }
.json-capability-copy small { color: var(--app-text-muted); font-size: 9px; line-height: 1.5; }
.model-form-grid .json-capability-field > input { position: relative; width: 38px; min-width: 38px; height: 22px; min-height: 22px; margin: 0; padding: 0; border: 0; border-radius: 999px; appearance: none; background: var(--app-border-strong); cursor: pointer; transition: background .16s ease; }
.model-form-grid .json-capability-field > input::after { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: var(--app-surface); box-shadow: 0 1px 4px rgb(0 0 0 / 24%); content: ''; transition: transform .16s ease; }
.model-form-grid .json-capability-field > input:checked { background: var(--app-accent); }
.model-form-grid .json-capability-field > input:checked::after { transform: translateX(16px); }
.model-form-grid .json-capability-field > input:focus-visible { outline: 3px solid color-mix(in srgb,var(--app-accent) 20%,transparent); outline-offset: 2px; box-shadow: none; }
.input-with-icon { position: relative; display: flex; align-items: center; }
.input-with-icon > svg { position: absolute; left: 11px; z-index: 1; color: var(--app-text-muted); }
.input-with-icon > input { padding-left: 34px; }
.secret-input > input { padding-right: 42px; }
.secret-input > button { position: absolute; right: 5px; display: grid; width: 32px; height: 30px; place-items: center; border: 0; border-radius: 7px; color: var(--app-text-muted); background: transparent; cursor: pointer; }
.secret-input > button:hover { color: var(--app-accent); background: var(--app-accent-soft); }
.model-modal > footer { justify-content: flex-end; padding-top: 3px; }
.model-modal > footer .app-button { min-height: 38px; padding: 0 14px; border-radius: 9px; cursor: pointer; font-size: 11px; }
.model-modal > footer button:disabled { cursor: not-allowed; opacity: .55; }
@media (max-width: 860px) {
  .model-category-grid { grid-template-columns: 1fr; }
  .model-category-card { min-height: 130px; }
}
@media (max-width: 620px) {
  .model-settings-page { padding: 30px 16px 60px; }
  .model-settings-header, .model-config-section > header { align-items: stretch; flex-direction: column; }
  .settings-primary-button { width: 100%; }
  .model-config-card { grid-template-columns: 42px minmax(0, 1fr); }
  .config-actions { grid-column: 1 / -1; justify-content: flex-end; padding-top: 10px; border-top: 1px solid #eff0f4; }
  .model-form-grid { grid-template-columns: 1fr; }
  .model-form-grid label, .model-form-grid label.is-full { grid-column: 1; }
}
</style>
