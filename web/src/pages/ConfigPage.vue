<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Bot,
  Check,
  CheckCircle2,
  Eye,
  EyeOff,
  Image,
  KeyRound,
  Languages,
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
import AppTabs, { type AppTabItem } from '@/components/AppTabs.vue'
import { api } from '@/api'
import { defaultPricing } from '@/shared/modelPricing'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import type { AiModelConfig, ConfigEnumItem, EnumItem, GeneralConfig, GenerationCapabilities, ImageApiProtocol, ImageModelType, ModelPricing, VideoGenerationModelType } from '@/types'

type ModelCategoryId = 'llm' | 'image' | 'video'
type SettingsSection = 'models' | 'general'

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
    taskTypes: [1, 3, 5],
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
const settingsTabs: AppTabItem[] = [
  { value: 'models', label: '模型配置', icon: Bot },
  { value: 'general', label: '通用配置', icon: Settings2 },
]

const VIDEO_MODEL_PRESETS: Record<VideoGenerationModelType, { baseUrl: string; model: string; protocol: ImageApiProtocol }> = {
  seedance_2: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-0-260128', protocol: 'volcengine_ark' },
  seedance_2_fast: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-0-fast-260128', protocol: 'volcengine_ark' },
  seedance_2_mini: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-0-mini-260615', protocol: 'volcengine_ark' },
  seedance_2_5: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-5-260817', protocol: 'volcengine_ark' },
  minimax_h3: { baseUrl: 'https://api.minimaxi.com', model: 'MiniMax-H3', protocol: 'minimax' },
}

const configs = ref<AiModelConfig[]>([])
const generalConfig = ref<GeneralConfig | null>(null)
const taskTypes = ref<EnumItem[]>([])
const imageModelTypes = ref<ConfigEnumItem[]>([])
const videoModelTypes = ref<ConfigEnumItem[]>([])
const loading = ref(true)
const savingGeneral = ref(false)
const auth = useAuthStore()
// 平台级配置仅超管可见；团队管理员只看到/管理本团队自定义配置
const isTeamAdmin = computed(() => auth.role === 'admin')
function canManage(item: AiModelConfig) {
  if (!isTeamAdmin.value) return true
  return item.scope === 'team'
}
const activeSection = ref<SettingsSection>('models')
const promptLanguage = ref<'zh' | 'en'>('en')
const showCreate = ref(false)
const creating = ref(false)
const editingConfigId = ref<number | null>(null)
const showApiKey = ref(false)
const selectedCategoryId = ref<ModelCategoryId>('llm')
const form = ref({ task_types: ['1'], name: '', base_url: '', api_key: '', model: '', api_protocol: 'openai_compatible' as ImageApiProtocol, image_model_type: '' as ImageModelType | '', video_model_type: '' as VideoGenerationModelType | '', concurrency: 1, supports_json_output: false, max_context_characters: '' as number | '', thinking: '' as 'enabled' | 'disabled' | '', max_tokens: '' as number | '' })

function configTaskTypes(item: AiModelConfig) {
  return item.task_types?.length ? item.task_types : [item.task_type]
}

const selectedCategory = computed(() => categories.find(item => item.id === selectedCategoryId.value) ?? categories[0])
const isEditing = computed(() => editingConfigId.value !== null)
const selectedConfigs = computed(() => configs.value.filter(item => configTaskTypes(item).some(value => selectedCategory.value.taskTypes.includes(value))))
const taskOptions = computed(() => selectedCategory.value.taskTypes.map(value => ({
  value: String(value),
  label: taskTypes.value.find(item => item.value === value)?.label || ({ 1: '内容理解与人物提取', 2: '角色与场景参考图', 3: '分镜规划与提示词', 4: '视频片段生成', 5: '项目分析' }[value] ?? `任务 ${value}`),
})))

const generationCapabilities = ref<GenerationCapabilities>({ image: {}, video: {} })
const textPricing = ref({ input_price_per_1m: 0, output_price_per_1m: 0 })
const tierPrices = ref<Record<string, number>>({})
const inputImagePricing = ref({ first_free: 1, price_per_image: 0 })
const videoRefPrices = ref<Record<string, number>>({})
const discountPricing = ref({ discount: 1, description: '' })
const pricingTierOptions = computed<string[]>(() => {
  if (selectedCategoryId.value === 'image') return generationCapabilities.value.image[form.value.image_model_type] || []
  if (selectedCategoryId.value === 'video') return generationCapabilities.value.video[form.value.video_model_type] || []
  return []
})
const selectedVideoPricingPreset = computed(() => (
  form.value.video_model_type
    ? generationCapabilities.value.video_pricing?.[form.value.video_model_type]
    : undefined
))
const isSecondBillingVideo = computed(() => (
  selectedCategoryId.value === 'video'
  && selectedVideoPricingPreset.value?.billing_unit === 'second'
))

function applyVideoPricingPreset() {
  const pricing = selectedVideoPricingPreset.value
  tierPrices.value = pricing?.prices ? { ...pricing.prices } : {}
  videoRefPrices.value = pricing?.video_reference_prices
    ? { ...pricing.video_reference_prices }
    : { ...tierPrices.value }
  inputImagePricing.value = pricing?.input_image
    ? { ...pricing.input_image }
    : { first_free: 0, price_per_image: 0 }
}

function iconTone(categoryId: ModelCategoryId) {
  if (categoryId === 'image') return 'image' as const
  if (categoryId === 'video') return 'video' as const
  return 'accent' as const
}

function configsFor(category: ModelCategory) {
  return configs.value.filter(item => configTaskTypes(item).some(value => category.taskTypes.includes(value)))
}

function activeCount(category: ModelCategory) {
  return configsFor(category).filter(item => item.is_active).length
}

function taskLabel(value: number) {
  return taskTypes.value.find(item => item.value === value)?.label || ({ 1: '内容理解', 2: '参考图生成', 3: '分镜规划', 4: '视频生成', 5: '项目分析' }[value] ?? `任务 ${value}`)
}

function protocolLabel(value: ImageApiProtocol) {
  if (value === 'minimax') return 'MiniMax 官方'
  if (value === 'volcengine_ark') return '火山方舟 Seedream'
  if (value === 'openrouter_compatible') return 'OpenRouter 兼容'
  return 'OpenAI 兼容'
}

function videoProtocolFor(modelType: VideoGenerationModelType | ''): ImageApiProtocol {
  return modelType ? VIDEO_MODEL_PRESETS[modelType].protocol : 'volcengine_ark'
}

const selectedVideoProtocolLabel = computed(() => protocolLabel(videoProtocolFor(form.value.video_model_type)))
const selectedVideoProtocolHint = computed(() => form.value.video_model_type === 'minimax_h3'
  ? '提交到 /v2/video_generation，并从 /v2/query/video_generation/{task_id} 查询结果。'
  : '提交到 /contents/generations/tasks，并通过任务 ID 异步查询结果。')

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
    const [configResponse, enumResponse, generalResponse, capabilitiesResponse] = await Promise.all([
      api.configs(),
      api.enums(),
      api.generalConfig(),
      api.generationCapabilities(),
    ])
    configs.value = configResponse.data.items
    taskTypes.value = enumResponse.data.ai_task_type || []
    imageModelTypes.value = enumResponse.data.image_model_type || []
    videoModelTypes.value = enumResponse.data.video_model_type || []
    generalConfig.value = generalResponse.data
    promptLanguage.value = generalResponse.data.prompt_language
    generationCapabilities.value = capabilitiesResponse.data
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function saveGeneralConfig() {
  savingGeneral.value = true
  try {
    const response = await api.updateGeneralConfig({ prompt_language: promptLanguage.value })
    generalConfig.value = response.data
    promptLanguage.value = response.data.prompt_language
    notice.success('通用配置已保存，新提交的生成任务将使用该语言')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    savingGeneral.value = false
  }
}

function changeSettingsSection(value: string) {
  activeSection.value = value as SettingsSection
}

function openCreate(categoryId: ModelCategoryId = selectedCategoryId.value) {
  selectedCategoryId.value = categoryId
  const category = categories.find(item => item.id === categoryId) ?? categories[0]
  form.value = { task_types: category.taskTypes.map(String), name: '', base_url: category.id === 'video' ? 'https://ark.cn-beijing.volces.com/api/v3' : '', api_key: '', model: '', api_protocol: category.id === 'image' || category.id === 'video' ? 'volcengine_ark' : 'openai_compatible', image_model_type: category.id === 'image' ? 'seedream_5_lite' : '', video_model_type: category.id === 'video' ? 'seedance_2' : '', concurrency: 1, supports_json_output: false, max_context_characters: '' as number | '', thinking: '' as 'enabled' | 'disabled' | '', max_tokens: '' as number | '' }
  textPricing.value = { input_price_per_1m: 0, output_price_per_1m: 0 }
  tierPrices.value = category.id === 'llm'
    ? {}
    : defaultPricing(category.id, pricingTierOptions.value).prices ?? {}
  inputImagePricing.value = { first_free: 1, price_per_image: 0 }
  videoRefPrices.value = {}
  if (category.id === 'video') applyVideoPricingPreset()
  discountPricing.value = { discount: 1, description: '' }
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
    api_protocol: item.api_protocol || (category.id === 'video' ? videoProtocolFor(item.video_model_type || '') : 'openai_compatible'),
    image_model_type: item.image_model_type || '',
    video_model_type: item.video_model_type || '',
    concurrency: item.concurrency,
    supports_json_output: item.supports_json_output ?? false,
    max_context_characters: item.max_context_characters ?? '',
    thinking: item.thinking ?? '',
    max_tokens: item.max_tokens ?? '',
  }
  textPricing.value = item.pricing?.type === 'text'
    ? { input_price_per_1m: item.pricing.input_price_per_1m ?? 0, output_price_per_1m: item.pricing.output_price_per_1m ?? 0 }
    : { input_price_per_1m: 0, output_price_per_1m: 0 }
  tierPrices.value = item.pricing?.prices ? { ...item.pricing.prices } : {}
  inputImagePricing.value = item.pricing?.input_image
    ? { first_free: item.pricing.input_image.first_free, price_per_image: item.pricing.input_image.price_per_image }
    : { first_free: 1, price_per_image: 0 }
  videoRefPrices.value = item.pricing?.video_reference_prices ? { ...item.pricing.video_reference_prices } : {}
  discountPricing.value = {
    discount: item.pricing?.discount ?? 1,
    description: item.pricing?.discount_description ?? '',
  }
  showCreate.value = true
}

function changeImageModelType() {
  if (form.value.api_protocol === 'openrouter_compatible') return
  form.value.api_protocol = form.value.image_model_type === 'gpt_image_2'
    ? 'openai_compatible'
    : 'volcengine_ark'
}

function changeVideoModelType() {
  if (!form.value.video_model_type) return
  const preset = VIDEO_MODEL_PRESETS[form.value.video_model_type]
  form.value.base_url = preset.baseUrl
  form.value.model = preset.model
  form.value.api_protocol = preset.protocol
  applyVideoPricingPreset()
}

async function saveConfig() {
  if (!form.value.task_types.length) {
    notice.error('请至少选择一个能力用途')
    return
  }
  creating.value = true
  try {
    const taskTypes = form.value.task_types.map(Number)
    const tierPriceEntries = (source: Record<string, number>) => Object.fromEntries(
      pricingTierOptions.value.map(tier => {
        const value = source[tier]
        return [tier, typeof value === 'number' && !Number.isNaN(value) ? value : 0]
      })
    )
    let pricing: ModelPricing
    if (selectedCategoryId.value === 'llm') {
      pricing = {
        type: 'text',
        currency: 'CNY',
        input_price_per_1m: Number(textPricing.value.input_price_per_1m) || 0,
        output_price_per_1m: Number(textPricing.value.output_price_per_1m) || 0,
      }
    } else if (selectedCategoryId.value === 'image') {
      pricing = {
        type: 'image',
        currency: 'CNY',
        prices: tierPriceEntries(tierPrices.value),
        input_image: {
          first_free: Number(inputImagePricing.value.first_free) || 0,
          price_per_image: Number(inputImagePricing.value.price_per_image) || 0,
        },
      }
    } else {
      pricing = {
        type: 'video',
        currency: 'CNY',
        billing_unit: isSecondBillingVideo.value ? 'second' : 'token',
        prices: tierPriceEntries(tierPrices.value),
        video_reference_prices: tierPriceEntries(videoRefPrices.value),
      }
      if (isSecondBillingVideo.value) {
        pricing.input_image = {
          first_free: Number(inputImagePricing.value.first_free) || 0,
          price_per_image: Number(inputImagePricing.value.price_per_image) || 0,
        }
      }
    }
    pricing.discount = Number(discountPricing.value.discount) || 1
    const discountDescription = discountPricing.value.description.trim()
    if (discountDescription) pricing.discount_description = discountDescription
    const payload = {
      ...form.value,
      api_protocol: selectedCategoryId.value === 'video'
        ? videoProtocolFor(form.value.video_model_type)
        : form.value.api_protocol,
      task_type: taskTypes[0],
      task_types: taskTypes,
      max_context_characters: form.value.max_context_characters || null,
      thinking: form.value.thinking || null,
      max_tokens: form.value.max_tokens || null,
      image_model_type: selectedCategoryId.value === 'image' ? form.value.image_model_type || null : null,
      video_model_type: selectedCategoryId.value === 'video' ? form.value.video_model_type || null : null,
      pricing,
    }
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

async function deactivate(item: AiModelConfig) {
  try {
    await api.deactivateConfig(item.id)
    await load()
    notice.success(`已停用 ${item.name}`)
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
        <span>APPLICATION SETTINGS</span>
        <h1>设置</h1>
        <p>统一管理生成模型与全局创作偏好。</p>
      </div>
      <AppButton v-if="activeSection === 'models'" variant="primary" size="lg" type="button" @click="openCreate()"><Plus :size="16" />添加模型</AppButton>
    </header>

    <AppTabs class="settings-section-tabs" :model-value="activeSection" :items="settingsTabs" label="设置分类" @update:model-value="changeSettingsSection" />

    <template v-if="activeSection === 'models'">
    <section v-if="isTeamAdmin" class="model-source-banner">
      <div class="model-source-copy">
        <strong>{{ configs.length ? `本团队已配置 ${configs.length} 个模型` : '尚未配置团队模型' }}</strong>
        <p>此处只管理本团队自己的模型配置；平台模型不对团队显示。未配置时，生成任务将使用平台模型，费用从团队余额扣除。</p>
      </div>
    </section>
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
        <span class="category-status"><i :class="{ 'is-ready': activeCount(category) }" />{{ activeCount(category) ? `${activeCount(category)} 个模型运行中` : '尚未启用' }}</span>
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
            <div class="config-title">
              <h3>{{ item.name }}</h3>
              <span v-if="!isTeamAdmin && item.scope" class="scope-badge" :class="item.scope === 'official' ? 'is-official' : 'is-team'">{{ item.scope === 'official' ? '平台配置' : '团队配置' }}</span>
              <span :class="{ 'is-active': item.is_active }">{{ item.is_active ? '已启动' : '未启动' }}</span>
            </div>
            <p>{{ configTaskTypes(item).map(taskLabel).join(' · ') }}</p>
            <div class="config-metadata">
              <span><Settings2 :size="13" />{{ item.model || '未设置模型名称' }}</span>
              <span><Server :size="13" />{{ providerHost(item.base_url) }}</span>
              <span><Zap :size="13" />并发 {{ item.concurrency }}</span>
              <span v-if="selectedCategory.id === 'image'">{{ protocolLabel(item.api_protocol) }}</span>
              <span v-if="selectedCategory.id === 'image'">{{ imageModelTypes.find(type => type.value === item.image_model_type)?.label || '未选择受支持类型' }}</span>
              <span v-if="selectedCategory.id === 'video'">{{ videoModelTypes.find(type => type.value === item.video_model_type)?.label || '未选择受支持类型' }}</span>
              <span v-if="selectedCategory.id === 'llm'">{{ item.supports_json_output ? 'JSON 格式化' : '提示词 JSON' }}</span>
            </div>
          </div>
          <div class="config-actions">
            <template v-if="canManage(item)">
              <AppButton v-if="!item.is_active" variant="soft" size="sm" type="button" title="启用配置" @click="activate(item)"><Power :size="15" /><span>启用</span></AppButton>
              <template v-else>
                <span class="active-check"><CheckCircle2 :size="16" />运行中</span>
                <AppButton variant="soft" size="sm" type="button" title="停用配置" @click="deactivate(item)"><Power :size="15" /><span>停用</span></AppButton>
              </template>
              <span class="config-icon-actions">
                <AppButton variant="secondary" size="sm" icon-only type="button" aria-label="编辑配置" title="编辑配置" @click="openEdit(item)"><Pencil :size="15" /></AppButton>
                <AppButton variant="danger" size="sm" icon-only type="button" aria-label="删除配置" title="删除配置" @click="remove(item)"><Trash2 :size="15" /></AppButton>
              </span>
            </template>
            <span v-else class="official-badge" title="官方配置由平台维护，团队管理员只读">只读</span>
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
    </template>

    <section v-else class="general-settings-section">
      <header>
        <div>
          <span>GENERAL PREFERENCES</span>
          <h2>通用配置</h2>
          <p>这些设置作用于之后新提交的生成任务，不会改写已有资产和分镜。</p>
        </div>
      </header>

      <article class="general-setting-card">
        <div class="general-setting-heading">
          <AppIconTile tone="accent" size="lg"><Languages :size="22" /></AppIconTile>
          <div>
            <h3>提示词语言</h3>
            <p>同时控制图片提示词、资产视觉特征与镜头提示词的输出语言。</p>
          </div>
          <span class="general-setting-status"><CheckCircle2 :size="14" />全局生效</span>
        </div>

        <div class="prompt-language-options" role="radiogroup" aria-label="提示词语言">
          <button
            type="button"
            role="radio"
            :aria-checked="promptLanguage === 'zh'"
            :class="{ 'is-selected': promptLanguage === 'zh' }"
            @click="promptLanguage = 'zh'"
          >
            <span class="language-mark">中</span>
            <span><strong>中文</strong><small>生成简体中文图片与镜头提示词</small></span>
            <Check v-if="promptLanguage === 'zh'" :size="17" />
          </button>
          <button
            type="button"
            role="radio"
            :aria-checked="promptLanguage === 'en'"
            :class="{ 'is-selected': promptLanguage === 'en' }"
            @click="promptLanguage = 'en'"
          >
            <span class="language-mark">EN</span>
            <span><strong>English</strong><small>Generate image and shot prompts in English</small></span>
            <Check v-if="promptLanguage === 'en'" :size="17" />
          </button>
        </div>

        <div class="general-setting-note">
          <strong>生效范围</strong>
          <span>章节资产提取、人物/场景/道具参考图、项目封面与自动分镜。</span>
        </div>

        <footer>
          <span v-if="generalConfig">当前已保存：{{ generalConfig.prompt_language === 'zh' ? '中文' : 'English' }}</span>
          <AppButton variant="primary" size="lg" type="button" :loading="savingGeneral" @click="saveGeneralConfig">
            {{ savingGeneral ? '保存中…' : '保存通用配置' }}
          </AppButton>
        </footer>
      </article>
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
          <label v-if="selectedCategory.id === 'image'" class="is-full">
            <span>生图模型类型</span>
            <select v-model="form.image_model_type" name="image-model-type" required @change="changeImageModelType">
              <option disabled value="">请选择受支持的模型</option>
              <option v-for="item in imageModelTypes" :key="String(item.value)" :value="item.value">{{ item.label }}</option>
            </select>
            <small>仅支持 Lite、Pro 和 GPT Image 2；清晰度、比例与格式由所选类型的后台能力定义。</small>
          </label>
          <label v-if="selectedCategory.id === 'video'" class="is-full">
            <span>视频模型类型</span>
            <select v-model="form.video_model_type" name="video-model-type" required @change="changeVideoModelType">
              <option disabled value="">请选择受支持的视频模型</option>
              <option v-for="item in videoModelTypes" :key="String(item.value)" :value="item.value">{{ item.label }}</option>
            </select>
            <small>支持 Seedance 系列与 MiniMax H3；分辨率、比例、时长和请求格式由后台能力与适配器定义。</small>
          </label>
          <label v-if="selectedCategory.id === 'video'" class="is-full">
            <span>接口协议</span>
            <output class="model-readonly-value" aria-label="视频接口协议">{{ selectedVideoProtocolLabel }}</output>
            <small>{{ selectedVideoProtocolHint }}</small>
          </label>
          <label v-if="selectedCategory.id === 'image'" class="is-full">
            <span>接口协议</span>
            <select v-model="form.api_protocol" name="image-api-protocol">
              <option value="openai_compatible">OpenAI 兼容（GPT Image / 中转服务）</option>
              <option value="openrouter_compatible">OpenRouter 兼容（/images）</option>
              <option value="volcengine_ark">火山方舟 Seedream</option>
            </select>
            <small>协议决定请求字段与尺寸适配，不依赖模型名称猜测供应商。</small>
          </label>
          <label v-if="selectedCategory.id === 'llm'">
            <span>上下文字符上限</span>
            <input
              v-model.number="form.max_context_characters"
              name="model-max-context-characters"
              type="number"
              min="1"
              placeholder="留空表示不预检"
            />
          </label>
          <label v-if="selectedCategory.id === 'llm'">
            <span>思考模式</span>
            <select v-model="form.thinking" name="model-thinking">
              <option value="">按模型默认</option>
              <option value="enabled">开启思考（enabled）</option>
              <option value="disabled">关闭思考（disabled）</option>
            </select>
            <small>深度思考/推理模型可关闭思考以提速并避免正文被 reasoning 挤占。</small>
          </label>
          <label v-if="selectedCategory.id === 'llm'">
            <span>最大输出 token</span>
            <input
              v-model.number="form.max_tokens"
              name="model-max-tokens"
              type="number"
              min="1"
              placeholder="留空按模型默认"
            />
            <small>限制单次请求输出，避免 JSON 因达到 token 上限被截断。</small>
          </label>
          <label v-if="selectedCategory.id === 'llm'" class="is-full json-capability-field">
            <span class="json-capability-copy">
              <strong>结构化 JSON 输出</strong>
              <small>开启后发送 response_format=json_object；关闭后仅使用提示词约束 JSON。</small>
            </span>
            <input v-model="form.supports_json_output" type="checkbox" role="switch" aria-label="结构化 JSON 输出" />
          </label>
        </div>

        <section v-if="selectedCategoryId === 'llm'" class="pricing-editor">
          <span class="pricing-title">费用设置（元 / 百万 token）</span>
          <div class="pricing-grid">
            <label><span>输入单价</span><input v-model.number="textPricing.input_price_per_1m" type="number" min="0" step="0.01" /></label>
            <label><span>输出单价</span><input v-model.number="textPricing.output_price_per_1m" type="number" min="0" step="0.01" /></label>
          </div>
        </section>
        <section v-else-if="selectedCategoryId === 'image' && pricingTierOptions.length" class="pricing-editor">
          <span class="pricing-title">输出图费用（元 / 张）</span>
          <div class="pricing-grid">
            <label v-for="tier in pricingTierOptions" :key="tier">
              <span>清晰度 {{ tier }}</span>
              <input v-model.number="tierPrices[tier]" type="number" min="0" step="0.01" />
            </label>
          </div>
          <div class="pricing-sub">
            <span class="pricing-title">输入图费用（图生图）</span>
            <div class="pricing-grid">
              <label><span>免费张数</span><input v-model.number="inputImagePricing.first_free" type="number" min="0" step="1" /></label>
              <label><span>超出单价（元 / 张）</span><input v-model.number="inputImagePricing.price_per_image" type="number" min="0" step="0.01" /></label>
            </div>
          </div>
        </section>
        <section v-else-if="selectedCategoryId === 'video' && pricingTierOptions.length" class="pricing-editor">
          <span class="pricing-title">{{ isSecondBillingVideo ? '生成视频（元 / 秒）' : '无视频参考（元 / 百万 token）' }}</span>
          <div class="pricing-grid">
            <label v-for="tier in pricingTierOptions" :key="tier">
              <span>分辨率 {{ tier }}</span>
              <input v-model.number="tierPrices[tier]" type="number" min="0" step="0.01" />
            </label>
          </div>
          <div class="pricing-sub">
            <span class="pricing-title">{{ isSecondBillingVideo ? '输入参考视频（元 / 秒，按输入时长）' : '有视频参考（元 / 百万 token）' }}</span>
            <div class="pricing-grid">
              <label v-for="tier in pricingTierOptions" :key="tier">
                <span>分辨率 {{ tier }}</span>
                <input v-model.number="videoRefPrices[tier]" type="number" min="0" step="0.01" />
              </label>
            </div>
          </div>
          <div v-if="isSecondBillingVideo" class="pricing-sub">
            <span class="pricing-title">输入参考图片</span>
            <div class="pricing-grid">
              <label><span>免费张数</span><input v-model.number="inputImagePricing.first_free" type="number" min="0" step="1" /></label>
              <label><span>超出单价（元 / 张）</span><input v-model.number="inputImagePricing.price_per_image" type="number" min="0" step="0.01" /></label>
            </div>
            <small>输入音频免费，不计入费用。</small>
          </div>
        </section>

        <section class="pricing-editor">
          <span class="pricing-title">折扣设置（1=无折扣，0.9=9折，大于 1=加价倍数）</span>
          <div class="pricing-grid">
            <label><span>折扣倍数</span><input v-model.number="discountPricing.discount" type="number" min="0.01" step="0.01" /></label>
            <label><span>折扣描述（可选）</span><input v-model="discountPricing.description" type="text" placeholder="例如：限时9折" /></label>
          </div>
        </section>

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
.settings-section-tabs { margin: 0 0 28px; }
.general-settings-section { display: grid; width: min(860px, 100%); gap: 15px; }
.general-settings-section > header > div { display: grid; gap: 5px; }
.general-settings-section > header span { color: var(--app-accent); font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.general-settings-section > header h2 { margin: 0; color: var(--app-text); font-size: 18px; }
.general-settings-section > header p { margin: 0; color: var(--app-text-muted); font-size: 11px; line-height: 1.6; }
.general-setting-card { display: grid; gap: 22px; padding: 22px; border: 1px solid var(--app-border); border-radius: 16px; color: var(--app-text); background: var(--app-surface); box-shadow: var(--app-shadow); }
.general-setting-heading { display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; align-items: center; gap: 13px; }
.general-setting-heading h3 { margin: 0 0 4px; color: var(--app-text); font-size: 14px; }
.general-setting-heading p { margin: 0; color: var(--app-text-muted); font-size: 10px; line-height: 1.55; }
.general-setting-status { display: inline-flex; align-items: center; gap: 5px; color: #258662; font-size: 9px; }
.prompt-language-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.prompt-language-options button { display: grid; min-height: 88px; grid-template-columns: 42px minmax(0, 1fr) 18px; align-items: center; gap: 12px; padding: 14px; border: 1px solid var(--app-border); border-radius: 13px; outline: none; color: var(--app-text-secondary); background: var(--app-surface-muted); cursor: pointer; text-align: left; transition: border-color .16s ease, background-color .16s ease, box-shadow .16s ease; }
.prompt-language-options button:hover { border-color: var(--app-border-strong); color: var(--app-text); background: var(--app-surface-hover); }
.prompt-language-options button:focus-visible { box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 18%,transparent); }
.prompt-language-options button.is-selected { border-color: color-mix(in srgb,var(--app-accent) 58%,var(--app-border)); color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 18%,transparent); }
.prompt-language-options button > span:nth-child(2) { display: grid; gap: 4px; }
.prompt-language-options button strong { color: inherit; font-size: 12px; }
.prompt-language-options button small { color: var(--app-text-muted); font-size: 9px; line-height: 1.45; }
.language-mark { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 11px; color: var(--app-accent); background: var(--app-surface); box-shadow: inset 0 0 0 1px var(--app-border); font-size: 11px; font-weight: 750; }
.general-setting-note { display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; border-radius: 10px; color: var(--app-text-muted); background: var(--app-surface-muted); font-size: 9px; line-height: 1.55; }
.general-setting-note strong { color: var(--app-text-secondary); white-space: nowrap; }
.general-setting-card > footer { display: flex; align-items: center; justify-content: flex-end; gap: 14px; padding-top: 2px; }
.general-setting-card > footer > span { margin-right: auto; color: var(--app-text-muted); font-size: 9px; }
.settings-primary-button, .model-config-section > header > button, .model-empty-state button { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; padding: 0 14px; border: 1px solid #5b5cf6; border-radius: 10px; color: #fff; background: #5b5cf6; box-shadow: 0 8px 20px rgb(91 92 246 / 18%); cursor: pointer; font-size: 12px; font-weight: 600; }
.settings-primary-button:hover, .model-config-section > header > button:hover, .model-empty-state button:hover { background: #4d4ee8; }
.model-source-banner { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; padding: 14px 16px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.model-source-copy strong { font-size: 13px; color: var(--app-text); }
.model-source-copy p { margin: 4px 0 0; font-size: 12px; color: var(--app-text-muted); }
.scope-badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.scope-badge.is-official { color: var(--app-accent); background: var(--app-accent-soft); }
.scope-badge.is-team { color: #059669; background: rgb(16 185 129 / 12%); }
.official-badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 12px; font-weight: 600; white-space: nowrap; }
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
.model-form-grid input, .model-form-grid select { width: 100%; min-height: 39px; padding: 0 11px; border: 1px solid var(--app-border); border-radius: 9px; outline: 0; color: var(--app-text); background: var(--app-surface-muted); caret-color: var(--app-text); font-size: 11px; transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease; }
.model-readonly-value { display: flex; width: 100%; min-height: 39px; align-items: center; padding: 0 11px; border-radius: 9px; color: var(--app-text); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); font-size: 11px; }
.model-form-grid input::placeholder { color: var(--app-text-muted); opacity: 1; }
.model-form-grid input:hover, .model-form-grid select:hover { border-color: var(--app-border-strong); }
.model-form-grid input:focus { border-color: var(--app-accent); color: var(--app-text); background: var(--app-surface-hover); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.model-form-grid select:focus { border-color: var(--app-accent); color: var(--app-text); background: var(--app-surface-hover); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
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
.pricing-editor { display: grid; gap: 10px; margin-top: 2px; padding: 14px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.pricing-sub { display: grid; gap: 8px; margin-top: 4px; padding-top: 10px; border-top: 1px dashed var(--app-border); }
.pricing-title { color: var(--app-text-secondary); font-size: 10px; font-weight: 600; }
.pricing-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.pricing-grid label { display: grid; gap: 6px; color: var(--app-text-muted); font-size: 10px; }
.pricing-grid input { width: 100%; min-height: 36px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 8px; outline: 0; color: var(--app-text); background: var(--app-surface); font-size: 11px; }
.pricing-grid input:focus { border-color: var(--app-accent); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
@media (max-width: 860px) {
  .model-source-banner { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; padding: 14px 16px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.model-source-copy strong { font-size: 13px; color: var(--app-text); }
.model-source-copy p { margin: 4px 0 0; font-size: 12px; color: var(--app-text-muted); }
.scope-badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.scope-badge.is-official { color: var(--app-accent); background: var(--app-accent-soft); }
.scope-badge.is-team { color: #059669; background: rgb(16 185 129 / 12%); }
.official-badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 12px; font-weight: 600; white-space: nowrap; }
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
  .prompt-language-options { grid-template-columns: 1fr; }
  .general-setting-heading { grid-template-columns: 46px minmax(0, 1fr); }
  .general-setting-status { grid-column: 2; }
  .general-setting-card > footer { align-items: stretch; flex-direction: column; }
  .general-setting-card > footer > span { margin-right: 0; }
}
</style>
