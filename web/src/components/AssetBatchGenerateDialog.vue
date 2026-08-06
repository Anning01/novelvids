<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, ImageIcon, ListChecks, LoaderCircle, Sparkles, X } from 'lucide-vue-next'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import type { AiModelConfig, Asset } from '@/types'

interface BatchGenerateOptions {
  assetIds: number[]
  modelConfigId: number
  concurrency: number
  resolution: string
  ratio: string
}

const props = defineProps<{
  open: boolean
  label: string
  assets: Asset[]
  generatingIds: Set<number>
  failedIds: Set<number>
  submitting?: boolean
}>()
const emit = defineEmits<{ close: []; generate: [options: BatchGenerateOptions] }>()

const resolutions = ['1K', '2K']
const ratios = ['1:1', '3:2', '2:3', '3:4', '4:3', '4:5', '5:4', '16:9', '9:16', '21:9']
const models = ref<AiModelConfig[]>([])
const modelId = ref('')
const resolution = ref('1K')
const ratio = ref('16:9')
const selectedIds = ref<number[]>([])
const loadingModels = ref(false)

const eligibleAssets = computed(() => props.assets.filter(asset => !asset.main_image && !props.generatingIds.has(asset.id)))
const modelOptions = computed(() => models.value.map(item => ({ value: String(item.id), label: item.name || item.model || `生图模型 ${item.id}` })))
const allSelected = computed(() => Boolean(eligibleAssets.value.length) && eligibleAssets.value.every(asset => selectedIds.value.includes(asset.id)))
const canGenerate = computed(() => selectedIds.value.length > 0 && Boolean(modelId.value) && !props.submitting)

function reset() {
  selectedIds.value = []
  resolution.value = '1K'
  ratio.value = '16:9'
}

async function loadModels() {
  loadingModels.value = true
  try {
    const response = await api.configs()
    models.value = response.data.items.filter(item => item.task_type === 2)
    modelId.value = String(models.value.find(item => item.is_active)?.id || models.value[0]?.id || '')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingModels.value = false
  }
}

function toggleAsset(asset: Asset) {
  if (asset.main_image || props.generatingIds.has(asset.id)) return
  selectedIds.value = selectedIds.value.includes(asset.id)
    ? selectedIds.value.filter(id => id !== asset.id)
    : [...selectedIds.value, asset.id]
}

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : eligibleAssets.value.map(asset => asset.id)
}

function submit() {
  if (!canGenerate.value) return
  const model = models.value.find(item => item.id === Number(modelId.value))
  emit('generate', {
    assetIds: selectedIds.value,
    modelConfigId: Number(modelId.value),
    concurrency: model?.concurrency || 1,
    resolution: resolution.value,
    ratio: ratio.value,
  })
}

watch(() => props.open, value => {
  if (!value) return
  reset()
  void loadModels()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="batch-dialog-backdrop" @click.self="emit('close')">
      <section class="batch-dialog" role="dialog" aria-modal="true" :aria-label="`批量生成${label}`">
        <header class="batch-dialog__header">
          <span><ListChecks :size="21" /></span>
          <div><small>BATCH GENERATION</small><h2>批量生成{{ label }}</h2></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭" @click="emit('close')"><X :size="18" /></AppButton>
        </header>

        <div class="batch-dialog__body">
          <p>选择需要生成参考图的{{ label }}，已完成的资产不会重复生成。</p>
          <div class="batch-assets">
            <AppButton
              v-for="asset in assets"
              :key="asset.id"
              type="button"
              variant="ghost"
              class="batch-asset"
              :class="{ 'is-selected': selectedIds.includes(asset.id), 'is-disabled': asset.main_image || generatingIds.has(asset.id) }"
              :disabled="Boolean(asset.main_image) || generatingIds.has(asset.id)"
              :aria-pressed="selectedIds.includes(asset.id)"
              @click="toggleAsset(asset)"
            >
              <span class="batch-checkbox"><Check v-if="selectedIds.includes(asset.id)" :size="13" /></span>
              <span class="batch-thumb"><img v-if="asset.main_image" :src="asset.main_image" alt="" /><ImageIcon v-else :size="18" /></span>
              <span class="batch-copy"><strong>{{ asset.canonical_name }}</strong><small>{{ asset.description || '尚未填写描述' }}</small></span>
              <AppBadge v-if="asset.main_image" class="batch-status" tone="warning" size="sm">已完成，不重复生成</AppBadge>
              <AppBadge v-else-if="generatingIds.has(asset.id)" class="batch-status is-running" tone="accent" size="sm"><LoaderCircle :size="12" />生成中</AppBadge>
              <AppBadge v-else-if="failedIds.has(asset.id)" class="batch-status" tone="danger" size="sm">上次失败，可重试</AppBadge>
              <AppBadge v-else class="batch-status" tone="accent" size="sm">待生成</AppBadge>
            </AppButton>
          </div>
        </div>

        <footer class="batch-dialog__footer">
          <div class="batch-options">
            <AppSelect v-model="modelId" :options="modelOptions" :disabled="loadingModels" ariaLabel="选择生图模型"><template #leading><Sparkles :size="14" /></template></AppSelect>
            <AppSelect v-model="resolution" :options="resolutions" ariaLabel="选择生成分辨率" />
            <AppSelect v-model="ratio" :options="ratios" ariaLabel="选择生成比例" />
          </div>
          <div class="batch-actions">
            <AppButton type="button" variant="soft" :disabled="!eligibleAssets.length" @click="toggleAll">{{ allSelected ? '取消全选' : '全选' }}</AppButton>
            <AppButton type="button" variant="secondary" @click="emit('close')">取消</AppButton>
            <AppButton type="button" variant="primary" :disabled="!canGenerate" :loading="submitting" @click="submit"><Sparkles v-if="!submitting" :size="15" />生成 {{ selectedIds.length }} 个</AppButton>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.batch-dialog-backdrop { position: fixed; inset: 0; z-index: 125; display: grid; place-items: center; padding: 22px; background: rgb(30 33 46 / 54%); backdrop-filter: blur(8px); }
.batch-dialog { display: grid; width: min(900px,100%); max-height: min(760px,calc(100vh - 44px)); grid-template-rows: auto minmax(0,1fr) auto; overflow: hidden; border-radius: 24px; background: #fff; box-shadow: 0 34px 110px rgb(19 22 34 / 32%); }
.batch-dialog__header { display: grid; grid-template-columns: 44px 1fr 36px; align-items: center; gap: 12px; padding: 18px 22px; background: linear-gradient(135deg,#fbfbff,#f4f5ff); }
.batch-dialog__header > span { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 14px; color: #5b5df0; background: #fff; box-shadow: 0 8px 22px rgb(73 75 159 / 10%); }
.batch-dialog__header small { color: #7779ef; font-size: 9px; font-weight: 800; letter-spacing: .14em; }
.batch-dialog__header h2 { margin: 2px 0 0; color: #292d3a; font-size: 19px; }
.batch-dialog__body { min-height: 0; overflow: hidden; padding: 16px 22px 18px; }
.batch-dialog__body > p { margin: 0 0 12px; color: #8c92a1; font-size: 11px; }
.batch-assets { display: grid; max-height: 500px; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; overflow-y: auto; padding: 2px 4px 12px 2px; scrollbar-width: thin; }
.batch-asset { display: grid; width: 100%; height: auto; min-height: 78px; grid-template-columns: 22px 54px minmax(0,1fr) auto; align-items: center; gap: 10px; padding: 9px 11px; border-radius: 14px; color: #4d5362; background: #f8f9fc; box-shadow: inset 0 0 0 1px transparent; text-align: left; }
.batch-asset:hover:not(:disabled),.batch-asset.is-selected { color: #4f51e6; background: #f5f5ff; box-shadow: inset 0 0 0 1px #bfc0fb; }
.batch-asset.is-disabled { opacity: .66; }
.batch-checkbox { display: grid; width: 18px; height: 18px; place-items: center; border-radius: 5px; color: #fff; background: #fff; box-shadow: inset 0 0 0 1px #d8dbe5; }
.is-selected .batch-checkbox { background: #6264ef; box-shadow: none; }
.batch-thumb { display: grid; width: 54px; height: 58px; overflow: hidden; place-items: center; border-radius: 10px; color: #a1a7b5; background: #e9ebf2; }
.batch-thumb img { width: 100%; height: 100%; object-fit: cover; }
.batch-copy { display: grid; min-width: 0; gap: 5px; }
.batch-copy strong,.batch-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch-copy strong { font-size: 12px; }
.batch-copy small { color: #969cab; font-size: 10px; font-weight: 450; }
.batch-status { white-space: nowrap; }
.batch-status.is-running svg { animation: batch-spin .8s linear infinite; }
.batch-dialog__footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 22px 18px; background: #fbfbfd; box-shadow: 0 -10px 30px rgb(36 40 57 / 4%); }
.batch-options,.batch-actions { display: flex; align-items: center; gap: 8px; }
.batch-options :deep(.app-select:first-child) { width: 220px; }
.batch-options :deep(.app-select) { width: 94px; }
@keyframes batch-spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .batch-dialog-backdrop { padding: 0; }
  .batch-dialog { width: 100%; max-height: 100vh; min-height: 100vh; border-radius: 0; }
  .batch-assets { grid-template-columns: 1fr; }
  .batch-dialog__footer { align-items: stretch; flex-direction: column; }
  .batch-options,.batch-actions { width: 100%; }
  .batch-options :deep(.app-select:first-child) { flex: 1; width: auto; }
  .batch-actions :deep(.app-button) { flex: 1; }
}
</style>
