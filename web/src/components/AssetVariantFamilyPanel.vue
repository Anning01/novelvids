<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  Check,
  ChevronUp,
  ImagePlus,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Star,
  Trash2,
  Upload,
  X,
} from 'lucide-vue-next'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import { api, sleep } from '@/api'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { TaskStatusEnum, type Asset, type AssetVariant } from '@/types'

const props = defineProps<{
  asset: Asset
  chapterNumber?: number
}>()

const emit = defineEmits<{
  close: []
  updated: [asset: Asset]
}>()

const variants = ref<AssetVariant[]>([])
const loading = ref(false)
const saving = ref(false)
const generatingIds = ref(new Set<number>())
const failedIds = ref(new Set<number>())
const editingId = ref<number | null>(null)
const formName = ref('')
const formDescription = ref('')
const formChapters = ref('')
const uploadInput = ref<HTMLInputElement | null>(null)
const uploadingVariantId = ref<number | null>(null)
let alive = true

const entityLabel = computed(() => ({
  1: '角色',
  2: '场景',
  3: '道具',
  4: '商品',
  5: '风格',
}[props.asset.asset_type] || '资产'))
const currentChapterVariant = computed(() => (
  variants.value
    .filter(item => props.chapterNumber && item.chapter_numbers?.includes(props.chapterNumber))
    .sort((left, right) => right.id - left.id)[0] || null
))

function variantImage(variant: AssetVariant) {
  return variant.images?.[0] || props.asset.main_image || props.asset.angle_image_1 || ''
}

function parseChapterNumbers(value: string) {
  const numbers = value
    .split(/[，,、\s]+/)
    .map(item => Number(item.trim()))
    .filter(item => Number.isInteger(item) && item > 0)
  return [...new Set(numbers)].sort((left, right) => left - right)
}

function chapterSummary(variant: AssetVariant) {
  if (!variant.chapter_numbers?.length) return '未指定集数'
  return variant.chapter_numbers.map(number => `第${number}集`).join('、')
}

function setGenerating(variantId: number, value: boolean) {
  const next = new Set(generatingIds.value)
  value ? next.add(variantId) : next.delete(variantId)
  generatingIds.value = next
}

function setFailed(variantId: number, value: boolean) {
  const next = new Set(failedIds.value)
  value ? next.add(variantId) : next.delete(variantId)
  failedIds.value = next
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

function cancelEdit() {
  editingId.value = null
}

async function saveVariant() {
  const name = formName.value.trim()
  if (!name || saving.value) return
  saving.value = true
  const payload = {
    name,
    description: formDescription.value.trim() || undefined,
    chapter_numbers: parseChapterNumbers(formChapters.value),
  }
  try {
    if (editingId.value) {
      const updated = (await api.updateAssetVariant(props.asset.id, editingId.value, payload)).data
      variants.value = variants.value.map(item => item.id === updated.id ? updated : item)
      notice.success('衍生形态已更新')
    } else {
      const created = (await api.createAssetVariant(props.asset.id, payload)).data
      variants.value.push(created)
      notice.success('衍生形态已创建')
    }
    editingId.value = null
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

async function setForCurrentChapter(variant: AssetVariant) {
  const chapterNumber = props.chapterNumber
  if (!chapterNumber) {
    notice.info('请先选择一个章节')
    return
  }
  saving.value = true
  try {
    variants.value = (await api.assignAssetVariantToChapter(props.asset.id, variant.id, chapterNumber)).data
    notice.success(`第 ${chapterNumber} 集已切换为「${variant.name}」`)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

async function generateVariant(variant: AssetVariant) {
  if (generatingIds.value.has(variant.id)) return
  setGenerating(variant.id, true)
  setFailed(variant.id, false)
  try {
    let task = (await api.generateAsset(props.asset.id, variant.id)).data
    while (alive && ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(task.status)) {
      await sleep(1800)
      task = (await api.task(task.id)).data
    }
    if (!alive) return
    if (task.status !== TaskStatusEnum.COMPLETED) throw new Error(task.error_message || '衍生参考图生成失败')
    await loadVariants()
    notice.success(`「${variant.name}」参考图已生成`)
  } catch (error) {
    setFailed(variant.id, true)
    notice.error((error as Error).message)
  } finally {
    setGenerating(variant.id, false)
  }
}

function chooseUpload(variant: AssetVariant) {
  uploadingVariantId.value = variant.id
  nextTick(() => uploadInput.value?.click())
}

async function uploadVariantImage(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  const variantId = uploadingVariantId.value
  target.value = ''
  if (!file || !variantId) return
  saving.value = true
  try {
    const uploaded = await api.upload(file)
    const existing = variants.value.find(item => item.id === variantId)
    if (!existing) return
    const updated = (await api.updateAssetVariant(props.asset.id, variantId, {
      images: [`/media/${uploaded.filename}`, ...(existing.images || []).filter(Boolean)],
    })).data
    variants.value = variants.value.map(item => item.id === updated.id ? updated : item)
    notice.success('衍生图片已上传')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
    uploadingVariantId.value = null
  }
}

async function removeVariant(variant: AssetVariant) {
  if (!await appConfirm({
    title: `删除衍生形态「${variant.name}」？`,
    message: '该衍生形态及其参考图片会被删除，但不会影响主体资产。',
    confirmLabel: '删除衍生',
    tone: 'danger',
  })) return
  try {
    await api.deleteAssetVariant(props.asset.id, variant.id)
    variants.value = variants.value.filter(item => item.id !== variant.id)
    notice.success('衍生形态已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

watch(() => props.asset.id, () => {
  editingId.value = null
  void loadVariants()
}, { immediate: true })

onBeforeUnmount(() => { alive = false })
</script>

<template>
  <section class="asset-family-panel" :aria-label="`${asset.canonical_name}的衍生形态`">
    <header class="asset-family-panel__header">
      <div>
        <span>{{ entityLabel }}资产族</span>
        <h3>{{ asset.canonical_name }}的衍生形态 <AppBadge tone="accent" size="sm">{{ variants.length }} 个衍生</AppBadge></h3>
        <p>主体形象保持不变，衍生状态可分别用于不同集数与分镜。</p>
      </div>
      <AppButton type="button" variant="ghost" size="sm" @click="emit('close')"><ChevronUp :size="15" />收起</AppButton>
    </header>

    <div v-if="loading" class="asset-family-panel__loading"><LoaderCircle :size="22" /><span>正在加载衍生形态…</span></div>
    <div v-else class="asset-family-panel__rail">
      <article class="variant-tile is-base">
        <div class="variant-tile__image">
          <img v-if="asset.main_image || asset.angle_image_1" :src="asset.main_image || asset.angle_image_1" :alt="asset.canonical_name" />
          <ImagePlus v-else :size="28" />
          <AppBadge tone="neutral" size="sm">主体</AppBadge>
        </div>
        <div class="variant-tile__copy"><strong>默认形态</strong><small>所有衍生的基础形象</small></div>
      </article>

      <article
        v-for="variant in variants"
        :key="variant.id"
        class="variant-tile"
        :class="{ 'is-current': currentChapterVariant?.id === variant.id, 'is-failed': failedIds.has(variant.id) }"
      >
        <div class="variant-tile__image">
          <img v-if="variantImage(variant)" :src="variantImage(variant)" :alt="variant.name" />
          <ImagePlus v-else :size="28" />
          <AppBadge v-if="currentChapterVariant?.id === variant.id" tone="accent" size="sm"><Check :size="10" />本章使用</AppBadge>
          <AppBadge v-else-if="failedIds.has(variant.id)" tone="danger" size="sm">生成失败</AppBadge>
          <span v-if="generatingIds.has(variant.id)" class="variant-tile__generating"><LoaderCircle :size="22" /><small>生成中</small></span>
        </div>
        <div class="variant-tile__copy">
          <strong>{{ variant.name }}</strong>
          <small>{{ chapterSummary(variant) }}</small>
        </div>
        <div class="variant-tile__actions" aria-label="衍生形态操作">
          <AppButton type="button" variant="ghost" size="xs" icon-only title="编辑衍生" :aria-label="`编辑${variant.name}`" @click="beginEdit(variant)"><Pencil :size="13" /></AppButton>
          <AppButton type="button" variant="ghost" size="xs" icon-only title="生成或重新生成" :aria-label="`生成${variant.name}`" :loading="generatingIds.has(variant.id)" @click="generateVariant(variant)"><RefreshCw v-if="variant.images.length" :size="13" /><Sparkles v-else :size="13" /></AppButton>
          <AppButton type="button" variant="ghost" size="xs" icon-only title="上传图片" :aria-label="`为${variant.name}上传图片`" @click="chooseUpload(variant)"><Upload :size="13" /></AppButton>
          <AppButton type="button" variant="ghost" size="xs" icon-only title="设为本章使用" :aria-label="`将${variant.name}设为本章使用`" :disabled="!chapterNumber || currentChapterVariant?.id === variant.id" @click="setForCurrentChapter(variant)"><Star :size="13" /></AppButton>
          <AppButton type="button" variant="ghost" size="xs" icon-only title="删除衍生" :aria-label="`删除${variant.name}`" @click="removeVariant(variant)"><Trash2 :size="13" /></AppButton>
        </div>
      </article>

      <button class="variant-tile variant-tile--new" type="button" @click="beginCreate">
        <span><Plus :size="20" /></span>
        <strong>新建衍生</strong>
        <small>成长、换装、受伤或环境变化</small>
      </button>
    </div>

    <form v-if="editingId !== null" class="variant-editor" @submit.prevent="saveVariant">
      <div class="variant-editor__title">
        <span><Sparkles :size="15" /></span>
        <div><strong>{{ editingId ? '编辑衍生形态' : '新建衍生形态' }}</strong><small>用于人物、场景和道具的不同状态。</small></div>
        <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="关闭编辑" @click="cancelEdit"><X :size="14" /></AppButton>
      </div>
      <label><span>形态名称</span><input v-model="formName" maxlength="100" placeholder="例如：日常便装、冬季、断裂状态" autofocus /></label>
      <label><span>适用集数</span><input v-model="formChapters" placeholder="例如：1，2，5" /><small>同一集只能匹配一个衍生形态。</small></label>
      <label class="variant-editor__description"><span>状态描述</span><textarea v-model="formDescription" rows="2" placeholder="描述相对主体发生的变化，生成时会继承主体特征。" /></label>
      <footer><AppButton type="button" variant="secondary" size="sm" @click="cancelEdit">取消</AppButton><AppButton type="submit" variant="primary" size="sm" :loading="saving" :disabled="!formName.trim()">保存衍生</AppButton></footer>
    </form>

    <input ref="uploadInput" class="asset-family-panel__upload" type="file" accept="image/*" @change="uploadVariantImage" />
  </section>
</template>

<style scoped>
.asset-family-panel { grid-column: 1/-1; display: grid; gap: 16px; padding: 18px 18px 20px; border-top: 1px solid var(--app-border); border-bottom: 1px solid var(--app-border); color: var(--app-text); background: color-mix(in srgb,var(--app-surface) 72%,transparent); animation: family-panel-in .24s cubic-bezier(.2,.72,.2,1); }
.asset-family-panel__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.asset-family-panel__header > div { display: grid; gap: 4px; }
.asset-family-panel__header > div > span { color: var(--app-accent); font-size: 9px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
.asset-family-panel__header h3 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 15px; line-height: 1.35; }
.asset-family-panel__header p { margin: 0; color: var(--app-text-muted); font-size: 10px; }
.asset-family-panel__loading { display: flex; min-height: 190px; align-items: center; justify-content: center; flex-direction: column; gap: 8px; color: var(--app-text-muted); font-size: 11px; }
.asset-family-panel__loading svg,.variant-tile__generating svg { animation: variant-spin .85s linear infinite; }
.asset-family-panel__rail { display: grid; grid-template-columns: repeat(auto-fill,minmax(148px,172px)); gap: 14px; align-items: start; }
.variant-tile { position: relative; display: grid; min-width: 0; overflow: hidden; border: 1px solid transparent; border-radius: 13px; color: var(--app-text); background: var(--app-surface-muted); transition: border-color .18s ease,box-shadow .18s ease,transform .18s ease; }
.variant-tile:hover,.variant-tile:focus-within { border-color: var(--app-border-strong); box-shadow: var(--app-shadow); transform: translateY(-2px); }
.variant-tile.is-current { border-color: var(--app-accent); box-shadow: 0 0 0 2px var(--app-accent-soft); }
.variant-tile.is-failed { border-color: color-mix(in srgb,#c45461 45%,var(--app-border)); }
.variant-tile__image { position: relative; display: grid; aspect-ratio: 1/1; place-items: center; overflow: hidden; color: var(--app-text-muted); background: var(--app-surface-muted); }
.variant-tile__image img { width: 100%; height: 100%; object-fit: cover; }
.variant-tile__image > .app-badge { position: absolute; top: 8px; left: 8px; z-index: 2; }
.variant-tile__generating { position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: 5px; color: var(--app-accent); background: color-mix(in srgb,var(--app-surface-raised) 82%,transparent); backdrop-filter: blur(4px); }
.variant-tile__copy { display: grid; min-width: 0; gap: 3px; padding: 9px 10px 7px; background: var(--app-surface); }
.variant-tile__copy strong,.variant-tile--new strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.variant-tile__copy small,.variant-tile--new small { overflow: hidden; color: var(--app-text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.variant-tile__actions { display: flex; align-items: center; justify-content: space-between; gap: 1px; padding: 0 5px 6px; background: var(--app-surface); }
.variant-tile__actions :deep(.app-button) { color: var(--app-text-secondary); }
.variant-tile__actions :deep(.app-button:last-child:hover) { color: #c45461; background: #fff1f2; }
.variant-tile--new { min-height: 218px; place-items: center; align-content: center; gap: 7px; padding: 16px; border: 1px dashed var(--app-border-strong); background: transparent; text-align: center; cursor: pointer; }
.variant-tile--new > span { display: grid; width: 38px; height: 38px; place-items: center; color: var(--app-accent); border-radius: 12px; background: var(--app-accent-soft); }
.variant-editor { display: grid; grid-template-columns: minmax(160px,.8fr) minmax(190px,.9fr) minmax(260px,1.7fr) auto; align-items: end; gap: 12px; padding-top: 16px; border-top: 1px solid var(--app-border); }
.variant-editor__title { grid-column: 1/-1; display: grid; grid-template-columns: 34px minmax(0,1fr) 30px; align-items: center; gap: 9px; }
.variant-editor__title > span { display: grid; width: 34px; height: 34px; place-items: center; color: var(--app-accent); border-radius: 10px; background: var(--app-accent-soft); }
.variant-editor__title > div { display: grid; gap: 2px; }
.variant-editor__title strong { font-size: 11px; }
.variant-editor__title small,.variant-editor label small { color: var(--app-text-muted); font-size: 9px; }
.variant-editor label { display: grid; gap: 6px; color: var(--app-text-secondary); font-size: 10px; font-weight: 700; }
.variant-editor input,.variant-editor textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--app-border); border-radius: 9px; outline: none; color: var(--app-text); background: var(--app-surface); font: inherit; font-weight: 400; resize: vertical; }
.variant-editor input:focus,.variant-editor textarea:focus { border-color: var(--app-accent); box-shadow: 0 0 0 3px var(--app-accent-soft); }
.variant-editor footer { display: flex; align-items: center; gap: 7px; padding-bottom: 1px; }
.asset-family-panel__upload { position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
@keyframes family-panel-in { from { opacity: 0; transform: translateY(-9px); } }
@keyframes variant-spin { to { transform: rotate(360deg); } }
@media (max-width: 960px) { .variant-editor { grid-template-columns: 1fr 1fr; } .variant-editor__description { grid-column: 1/-1; } }
@media (max-width: 620px) { .asset-family-panel { padding: 15px 0; } .asset-family-panel__rail { grid-template-columns: repeat(2,minmax(0,1fr)); } .variant-editor { grid-template-columns: 1fr; } .variant-editor__description,.variant-editor footer { grid-column: auto; } }
@media (prefers-reduced-motion: reduce) { .asset-family-panel,.variant-tile { animation: none; transition: none; } }
</style>
