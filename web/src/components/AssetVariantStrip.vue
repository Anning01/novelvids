<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, ImagePlus, LoaderCircle, Sparkles, WandSparkles, X } from 'lucide-vue-next'
import { api } from '@/api'
import EpisodeSelectionPicker from '@/components/EpisodeSelectionPicker.vue'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { type Asset, type AssetVariant, type AssetVariantDraft } from '@/types'

const props = withDefaults(defineProps<{ asset: Asset; draft?: AssetVariantDraft | null; chapterNumber?: number; episodeNumbers?: number[] }>(), {
  draft: null,
  episodeNumbers: () => [],
})
const emit = defineEmits<{ select: [variant: AssetVariant | null]; draft: [draft: AssetVariantDraft | null] }>()

const variants = ref<AssetVariant[]>([])
const loading = ref(false)
const editingId = ref<number | null>(null)
const formName = ref('')
const formDescription = ref('')
const formChapters = ref<number[]>([])
const selectedVariantId = ref<number | null>(null)

const entityAction = computed(() => new Map<number, string>([[1, '变装'], [2, '场景状态'], [3, '道具状态']]).get(props.asset.asset_type) || '衍生')
const currentVariantId = computed(() => variants.value.find(item => props.chapterNumber && item.chapter_numbers?.includes(props.chapterNumber))?.id || 0)

function imageFor(variant: AssetVariant) {
  return variant.images?.[0] || ''
}

function selectBase() {
  selectedVariantId.value = null
  editingId.value = null
  emit('select', null)
  emit('draft', null)
}

function selectVariant(variant: AssetVariant) {
  selectedVariantId.value = variant.id
  emit('select', variant)
  beginEdit(variant)
}

function currentDraft(): AssetVariantDraft | null {
  if (editingId.value === null) return null
  return {
    id: editingId.value || null,
    name: formName.value.trim(),
    description: formDescription.value.trim(),
    chapter_numbers: formChapters.value,
    is_new: editingId.value === 0,
  }
}

function emitDraft() {
  emit('draft', currentDraft())
}

function matchesDraft(left: AssetVariantDraft | null, right: AssetVariantDraft | null) {
  if (!left || !right) return left === right
  return left.id === right.id
    && left.is_new === right.is_new
    && left.name === right.name
    && left.description === right.description
    && left.chapter_numbers.length === right.chapter_numbers.length
    && left.chapter_numbers.every((chapter, index) => chapter === right.chapter_numbers[index])
}

async function loadVariants() {
  loading.value = true
  try {
    variants.value = (await api.assetVariants(props.asset.id)).data
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function beginCreate() {
  selectedVariantId.value = -1
  editingId.value = 0
  formName.value = ''
  formDescription.value = ''
  formChapters.value = props.chapterNumber ? [props.chapterNumber] : []
  emit('select', null)
  emitDraft()
}

function beginEdit(variant: AssetVariant) {
  editingId.value = variant.id
  formName.value = variant.name
  formDescription.value = variant.description || ''
  formChapters.value = [...(variant.chapter_numbers || [])]
  emitDraft()
}

function upsertVariant(variant: AssetVariant) {
  const existingIndex = variants.value.findIndex(item => item.id === variant.id)
  if (existingIndex === -1) variants.value.push(variant)
  else variants.value.splice(existingIndex, 1, variant)
  selectedVariantId.value = variant.id
  beginEdit(variant)
}

defineExpose({ upsertVariant })

async function removeVariant(variant: AssetVariant) {
  if (!await appConfirm({
    title: `删除「${variant.name}」？`,
    message: '该衍生形态及参考图片将被删除，主形象不受影响。',
    confirmLabel: '删除',
    tone: 'danger',
  })) return
  try {
    await api.deleteAssetVariant(props.asset.id, variant.id)
    variants.value = variants.value.filter(item => item.id !== variant.id)
    if (editingId.value === variant.id) editingId.value = null
    if (selectedVariantId.value === variant.id) selectBase()
    notice.success('衍生形态已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

watch(() => props.asset.id, () => {
  editingId.value = null
  selectedVariantId.value = null
  void loadVariants()
}, { immediate: true })

watch(() => props.draft, draft => {
  if (!draft) {
    editingId.value = null
    selectedVariantId.value = null
    return
  }
  editingId.value = draft.is_new ? 0 : draft.id
  selectedVariantId.value = draft.is_new ? -1 : draft.id
  formName.value = draft.name
  formDescription.value = draft.description
  formChapters.value = [...draft.chapter_numbers]
}, { immediate: true })

watch([formName, formDescription, formChapters], () => {
  if (editingId.value !== null && !matchesDraft(currentDraft(), props.draft)) emitDraft()
})
</script>

<template>
  <section class="asset-variant-strip" aria-label="形象衍生">
    <header><strong>形象衍生</strong><span>{{ variants.length }} 个</span></header>
    <div class="asset-variant-strip__rail">
      <button type="button" class="asset-variant-item is-base" :class="{ 'is-selected': selectedVariantId === null }" aria-label="切换到主形象" @click="selectBase">
        <span class="asset-variant-item__media">
          <img v-if="asset.main_image || asset.angle_image_1" :src="asset.main_image || asset.angle_image_1" :alt="asset.canonical_name" />
          <ImagePlus v-else :size="22" />
        </span>
        <strong>主形象</strong>
      </button>
      <i aria-hidden="true" />
      <span v-if="loading" class="asset-variant-strip__loading"><LoaderCircle :size="20" /></span>
      <article v-for="variant in variants" v-else :key="variant.id" class="asset-variant-item" :class="{ 'is-current': currentVariantId === variant.id, 'is-selected': selectedVariantId === variant.id }">
        <button type="button" class="asset-variant-item__open" :aria-label="`切换到${variant.name}`" @click="selectVariant(variant)">
          <span class="asset-variant-item__media">
            <img v-if="imageFor(variant)" :src="imageFor(variant)" :alt="variant.name" />
            <WandSparkles v-else :size="22" />
            <small v-if="currentVariantId === variant.id"><Check :size="10" />本集</small>
          </span>
          <strong>{{ variant.name }}</strong>
        </button>
        <button type="button" class="asset-variant-item__remove" :aria-label="`删除${variant.name}`" title="删除该衍生" @click="removeVariant(variant)"><X :size="9" /><span>删除</span></button>
      </article>
      <button type="button" class="asset-variant-item is-add" @click="beginCreate">
        <span class="asset-variant-item__media"><WandSparkles :size="22" /></span>
        <strong>添加{{ entityAction }}</strong>
      </button>
    </div>

    <section v-if="editingId !== null" class="asset-variant-editor" aria-label="衍生形态字段">
      <header>
        <span><Sparkles :size="15" /></span>
        <div><strong>{{ editingId ? '编辑衍生形态' : `添加${entityAction}` }}</strong><small>字段、上传与生成结果会由抽屉底部统一保存。</small></div>
      </header>
      <div class="asset-variant-editor__fields">
        <label><span>名称</span><input v-model="formName" maxlength="100" placeholder="例如：日常便装" /></label>
        <div class="is-chapters">
          <span>适用集数 <small><Sparkles :size="9" />AI 建议 · 可修改</small></span>
          <EpisodeSelectionPicker v-model="formChapters" :episode-numbers="episodeNumbers" :current-episode="chapterNumber" />
          <em>支持区间、分段与逐集微调，保存为集数列表。</em>
        </div>
        <label class="is-description"><span>变化描述</span><input v-model="formDescription" placeholder="例如：换成深色西装，左臂受伤" /></label>
      </div>
    </section>
  </section>
</template>

<style scoped>
.asset-variant-strip { display: grid; min-width: 0; gap: 9px; padding: 13px 0 4px; border-top: 1px solid var(--app-border); border-bottom: 1px solid var(--app-border); color: var(--app-text); }
.asset-variant-strip > header { display: flex; align-items: center; gap: 7px; color: var(--app-text-secondary); }
.asset-variant-strip > header strong { font-size: 12px; }
.asset-variant-strip > header span { color: var(--app-text-muted); font-size: 9px; }
.asset-variant-strip__rail { display: flex; min-width: 0; align-items: flex-start; gap: 12px; overflow-x: auto; padding: 10px 9px 8px; scrollbar-width: none; }
.asset-variant-strip__rail::-webkit-scrollbar { display: none; }
.asset-variant-strip__rail > i { width: 1px; height: 48px; flex: 0 0 1px; align-self: center; background: var(--app-border); }
.asset-variant-item { position: relative; display: grid; width: 112px; flex: 0 0 112px; gap: 6px; padding: 0; border: 0; color: var(--app-text-secondary); background: transparent; font: inherit; text-align: center; cursor: pointer; }
.asset-variant-item__open,.asset-variant-item.is-add { display: grid; gap: 6px; padding: 0; border: 0; color: inherit; background: transparent; font: inherit; cursor: pointer; }
.asset-variant-item__media { position: relative; display: grid; width: 112px; height: 58px; place-items: center; overflow: hidden; border: 1px solid var(--app-border); border-radius: 11px; color: var(--app-text-muted); background: var(--app-surface-muted); transition: border-color .16s ease,box-shadow .16s ease,transform .16s ease; }
.asset-variant-item__media img { width: 100%; height: 100%; object-fit: cover; }
.asset-variant-item strong { display: block; overflow: hidden; font-size: 10px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.asset-variant-item:hover .asset-variant-item__media,.asset-variant-item:focus-within .asset-variant-item__media { border-color: var(--app-accent); transform: translateY(-1px); }
.asset-variant-item.is-selected .asset-variant-item__media { border-color: var(--app-accent); box-shadow: 0 0 0 2px var(--app-accent-soft); }
.asset-variant-item__media small { position: absolute; right: 5px; bottom: 5px; display: flex; align-items: center; gap: 2px; padding: 2px 4px; border-radius: 5px; color: #fff; background: rgb(69 71 218 / 88%); font-size: 7px; }
.asset-variant-item__remove { position: absolute; top: 4px; right: 4px; z-index: 2; display: inline-flex; min-width: 31px; height: 16px; align-items: center; justify-content: center; gap: 2px; padding: 0 5px; border: 0; border-radius: 999px; color: #fff; background: rgb(42 45 55 / 78%); cursor: pointer; font: inherit; font-size: 7px; font-weight: 650; opacity: 0; transform: translateY(-2px); transition: opacity .14s ease,transform .14s ease,background .14s ease; backdrop-filter: blur(5px); }
.asset-variant-item__remove span { line-height: 1; }
.asset-variant-item.is-selected .asset-variant-item__remove { opacity: .78; transform: translateY(0); }
.asset-variant-item:hover .asset-variant-item__remove,.asset-variant-item:focus-within .asset-variant-item__remove { background: #d4485b; opacity: 1; transform: translateY(0); }
.asset-variant-item.is-add { color: var(--app-text-secondary); }
.asset-variant-item.is-add .asset-variant-item__media { width: 58px; margin: 0 auto; color: var(--app-text); background: var(--app-surface); }
.asset-variant-strip__loading { display: grid; width: 112px; height: 58px; flex: 0 0 112px; place-items: center; color: var(--app-accent); }
.asset-variant-strip__loading svg { animation: variant-strip-spin .8s linear infinite; }
.asset-variant-editor { display: grid; gap: 11px; padding: 12px; border-radius: 12px; background: var(--app-surface-muted); animation: variant-editor-in .18s ease; }
.asset-variant-editor > header { display: grid; grid-template-columns: 32px minmax(0,1fr); align-items: center; gap: 8px; }
.asset-variant-editor > header > span { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 9px; color: var(--app-accent); background: var(--app-accent-soft); }
.asset-variant-editor > header > div { display: grid; gap: 2px; }
.asset-variant-editor > header strong { font-size: 11px; }
.asset-variant-editor > header small { color: var(--app-text-muted); font-size: 8px; }
.asset-variant-editor__fields { display: grid; grid-template-columns: .75fr 1.1fr 1.45fr; align-items: start; gap: 8px; }
.asset-variant-editor label,.asset-variant-editor .is-chapters { display: grid; gap: 5px; color: var(--app-text-secondary); font-size: 9px; font-weight: 650; }
.asset-variant-editor label > span,.asset-variant-editor .is-chapters > span { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.asset-variant-editor label > span > small,.asset-variant-editor .is-chapters > span > small { display: inline-flex; align-items: center; gap: 3px; padding: 2px 5px; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 7px; white-space: nowrap; }
.asset-variant-editor input { min-width: 0; height: 34px; padding: 0 9px; border: 1px solid var(--app-border); border-radius: 8px; outline: 0; color: var(--app-text); background: var(--app-surface); font: inherit; font-weight: 450; }
.asset-variant-editor input:focus { border-color: var(--app-accent); box-shadow: 0 0 0 3px var(--app-accent-soft); }
.asset-variant-editor label > em,.asset-variant-editor .is-chapters > em { color: var(--app-text-muted); font-size: 7px; font-style: normal; font-weight: 450; line-height: 1.4; }
@keyframes variant-strip-spin { to { transform: rotate(360deg); } }
@keyframes variant-editor-in { from { opacity: 0; transform: translateY(-4px); } }
@media (max-width: 620px) { .asset-variant-editor__fields { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .asset-variant-item__media,.asset-variant-item__remove,.asset-variant-editor { transition: none; animation: none; } }
</style>
