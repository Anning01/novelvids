<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ImagePlus, LoaderCircle, RefreshCw, Sparkles, Upload, WandSparkles, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { api, sleep } from '@/api'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { TaskStatusEnum, type Asset, type AssetVariant } from '@/types'

const props = defineProps<{ asset: Asset; chapterNumber?: number }>()
const emit = defineEmits<{ select: [variant: AssetVariant | null] }>()

const variants = ref<AssetVariant[]>([])
const loading = ref(false)
const saving = ref(false)
const generatingId = ref(0)
const editingId = ref<number | null>(null)
const formName = ref('')
const formDescription = ref('')
const formChapters = ref('')
const uploadInput = ref<HTMLInputElement | null>(null)
const selectedVariantId = ref<number | null>(null)
let alive = true

const entityAction = computed(() => new Map<number, string>([[1, '变装'], [2, '场景状态'], [3, '道具状态']]).get(props.asset.asset_type) || '衍生')
const currentVariantId = computed(() => variants.value.find(item => props.chapterNumber && item.chapter_numbers?.includes(props.chapterNumber))?.id || 0)
const editingVariant = computed(() => variants.value.find(item => item.id === editingId.value) || null)

function imageFor(variant: AssetVariant) {
  return variant.images?.[0] || ''
}

function selectBase() {
  selectedVariantId.value = null
  editingId.value = null
  emit('select', null)
}

function selectVariant(variant: AssetVariant) {
  selectedVariantId.value = variant.id
  emit('select', variant)
  beginEdit(variant)
}

function parseChapters(value: string) {
  return [...new Set(value.split(/[，,、\s]+/).map(Number).filter(number => Number.isInteger(number) && number > 0))].sort((a, b) => a - b)
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
  editingId.value = 0
  formName.value = ''
  formDescription.value = ''
  formChapters.value = props.chapterNumber ? String(props.chapterNumber) : ''
}

function beginEdit(variant: AssetVariant) {
  editingId.value = variant.id
  formName.value = variant.name
  formDescription.value = variant.description || ''
  formChapters.value = (variant.chapter_numbers || []).join('，')
}

function closeEditor() {
  editingId.value = null
}

async function saveVariant() {
  const variantName = formName.value.trim()
  if (!variantName || saving.value) return
  saving.value = true
  const payload = {
    name: variantName,
    description: formDescription.value.trim() || undefined,
    chapter_numbers: parseChapters(formChapters.value),
  }
  try {
    if (editingId.value) {
      const updated = (await api.updateAssetVariant(props.asset.id, editingId.value, payload)).data
      variants.value = variants.value.map(item => item.id === updated.id ? updated : item)
      if (selectedVariantId.value === updated.id) emit('select', updated)
      notice.success('衍生形态已更新')
    } else {
      const created = (await api.createAssetVariant(props.asset.id, payload)).data
      variants.value.push(created)
      selectedVariantId.value = created.id
      emit('select', created)
      notice.success(`${entityAction.value}已添加`)
    }
    editingId.value = null
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

async function useForChapter(variant: AssetVariant) {
  if (!props.chapterNumber || currentVariantId.value === variant.id || saving.value) return
  saving.value = true
  try {
    variants.value = (await api.assignAssetVariantToChapter(props.asset.id, variant.id, props.chapterNumber)).data
    notice.success(`第 ${props.chapterNumber} 集已使用「${variant.name}」`)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

async function generateVariant(variant: AssetVariant) {
  if (generatingId.value) return
  generatingId.value = variant.id
  try {
    let task = (await api.generateAsset(props.asset.id, variant.id)).data
    while (alive && ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(task.status)) {
      await sleep(1800)
      task = (await api.task(task.id)).data
    }
    if (!alive) return
    if (task.status !== TaskStatusEnum.COMPLETED) throw new Error(task.error_message || '衍生参考图生成失败')
    await loadVariants()
    notice.success('衍生参考图已生成')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    generatingId.value = 0
  }
}

function generateEditingVariant() {
  if (editingVariant.value) void generateVariant(editingVariant.value)
}

function useEditingVariant() {
  if (editingVariant.value) void useForChapter(editingVariant.value)
}

async function chooseUpload() {
  await nextTick()
  uploadInput.value?.click()
}

async function uploadImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !editingId.value) return
  saving.value = true
  try {
    const current = variants.value.find(item => item.id === editingId.value)
    if (!current) return
    const uploaded = await api.upload(file)
    const updated = (await api.updateAssetVariant(props.asset.id, current.id, {
      images: [`/media/${uploaded.filename}`, ...(current.images || []).filter(Boolean)],
    })).data
    variants.value = variants.value.map(item => item.id === updated.id ? updated : item)
    if (selectedVariantId.value === updated.id) emit('select', updated)
    notice.success('衍生图片已上传')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

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

onBeforeUnmount(() => { alive = false })
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
        <button type="button" class="asset-variant-item__remove" :aria-label="`删除${variant.name}`" title="删除" @click="removeVariant(variant)"><X :size="13" /></button>
      </article>
      <button type="button" class="asset-variant-item is-add" @click="beginCreate">
        <span class="asset-variant-item__media"><WandSparkles :size="22" /></span>
        <strong>添加{{ entityAction }}</strong>
      </button>
    </div>

    <form v-if="editingId !== null" class="asset-variant-editor" @submit.prevent="saveVariant">
      <header>
        <span><Sparkles :size="15" /></span>
        <div><strong>{{ editingId ? '编辑衍生形态' : `添加${entityAction}` }}</strong><small>保留主体特征，只描述发生的变化。</small></div>
        <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="关闭衍生编辑" @click="closeEditor"><X :size="14" /></AppButton>
      </header>
      <div class="asset-variant-editor__fields">
        <label><span>名称</span><input v-model="formName" maxlength="100" placeholder="例如：日常便装" /></label>
        <label><span>适用集数</span><input v-model="formChapters" placeholder="例如：1，2，5" /></label>
        <label class="is-description"><span>变化描述</span><input v-model="formDescription" placeholder="例如：换成深色西装，左臂受伤" /></label>
      </div>
      <footer>
        <div>
          <AppButton v-if="editingId" type="button" variant="secondary" size="sm" @click="chooseUpload"><Upload :size="14" />上传</AppButton>
          <AppButton v-if="editingId" type="button" variant="secondary" size="sm" :loading="generatingId === editingId" @click="generateEditingVariant"><RefreshCw :size="14" />生成</AppButton>
          <AppButton v-if="editingId && chapterNumber" type="button" variant="secondary" size="sm" :disabled="currentVariantId === editingId" @click="useEditingVariant"><Check :size="14" />本集使用</AppButton>
        </div>
        <div><AppButton type="button" variant="secondary" size="sm" @click="closeEditor">取消</AppButton><AppButton type="submit" variant="primary" size="sm" :loading="saving" :disabled="!formName.trim()">保存</AppButton></div>
      </footer>
    </form>
    <input ref="uploadInput" class="asset-variant-strip__upload" type="file" accept="image/*" @change="uploadImage" />
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
.asset-variant-item__remove { position: absolute; top: -7px; right: -7px; z-index: 2; display: grid; width: 22px; height: 22px; place-items: center; padding: 0; border: 2px solid var(--app-surface); border-radius: 50%; color: #fff; background: #4b4f5c; cursor: pointer; opacity: 0; transform: scale(.84); transition: opacity .14s ease,transform .14s ease; }
.asset-variant-item:hover .asset-variant-item__remove,.asset-variant-item:focus-within .asset-variant-item__remove { opacity: 1; transform: scale(1); }
.asset-variant-item.is-add { color: var(--app-text-secondary); }
.asset-variant-item.is-add .asset-variant-item__media { width: 58px; margin: 0 auto; color: var(--app-text); background: var(--app-surface); }
.asset-variant-strip__loading { display: grid; width: 112px; height: 58px; flex: 0 0 112px; place-items: center; color: var(--app-accent); }
.asset-variant-strip__loading svg { animation: variant-strip-spin .8s linear infinite; }
.asset-variant-editor { display: grid; gap: 11px; padding: 12px; border-radius: 12px; background: var(--app-surface-muted); animation: variant-editor-in .18s ease; }
.asset-variant-editor > header { display: grid; grid-template-columns: 32px minmax(0,1fr) 28px; align-items: center; gap: 8px; }
.asset-variant-editor > header > span { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 9px; color: var(--app-accent); background: var(--app-accent-soft); }
.asset-variant-editor > header > div { display: grid; gap: 2px; }
.asset-variant-editor > header strong { font-size: 11px; }
.asset-variant-editor > header small { color: var(--app-text-muted); font-size: 8px; }
.asset-variant-editor__fields { display: grid; grid-template-columns: .8fr .7fr 1.5fr; gap: 8px; }
.asset-variant-editor label { display: grid; gap: 5px; color: var(--app-text-secondary); font-size: 9px; font-weight: 650; }
.asset-variant-editor input { min-width: 0; height: 34px; padding: 0 9px; border: 1px solid var(--app-border); border-radius: 8px; outline: 0; color: var(--app-text); background: var(--app-surface); font: inherit; font-weight: 450; }
.asset-variant-editor input:focus { border-color: var(--app-accent); box-shadow: 0 0 0 3px var(--app-accent-soft); }
.asset-variant-editor footer,.asset-variant-editor footer > div { display: flex; align-items: center; gap: 6px; }
.asset-variant-editor footer { justify-content: space-between; }
.asset-variant-strip__upload { position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
@keyframes variant-strip-spin { to { transform: rotate(360deg); } }
@keyframes variant-editor-in { from { opacity: 0; transform: translateY(-4px); } }
@media (max-width: 620px) { .asset-variant-editor__fields { grid-template-columns: 1fr; } .asset-variant-editor footer { align-items: stretch; flex-direction: column; } }
@media (prefers-reduced-motion: reduce) { .asset-variant-item__media,.asset-variant-item__remove,.asset-variant-editor { transition: none; animation: none; } }
</style>
