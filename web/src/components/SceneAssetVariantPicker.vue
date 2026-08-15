<script setup lang="ts">
import { Check, ChevronRight, ImageIcon, Search, X } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Asset, AssetVariant } from '@/types'

export interface SceneAssetVariantSelection {
  assetId: number
  variantId: number | null
  selected: boolean
}

const props = withDefaults(defineProps<{
  open: boolean
  anchorId: string
  label: string
  assets: Asset[]
  selectedAssetIds: number[]
  selectedVariantIds: Record<number, number | null>
  initialAssetId?: number
  selectionMode?: 'add' | 'replace'
  placement?: 'auto' | 'below'
}>(), {
  initialAssetId: 0,
  selectionMode: 'add',
  placement: 'auto',
})

const emit = defineEmits<{
  close: []
  select: [selection: SceneAssetVariantSelection]
}>()

const PANEL_MAX_WIDTH = 520
const panel = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const activeAssetId = ref(0)
const position = ref({ top: 0, left: 0, width: PANEL_MAX_WIDTH, maxHeight: 460 })

const normalizedQuery = computed(() => query.value.trim().toLocaleLowerCase())
const filteredAssets = computed(() => {
  if (!normalizedQuery.value) return props.assets
  return props.assets.filter(asset => {
    const searchable = [
      asset.canonical_name,
      ...(asset.aliases || []),
      ...(asset.variants || []).map(variant => variant.name),
    ]
    return searchable.some(value => value.toLocaleLowerCase().includes(normalizedQuery.value))
  })
})
const activeAsset = computed(() => (
  filteredAssets.value.find(asset => asset.id === activeAssetId.value)
  || filteredAssets.value[0]
  || null
))
const visibleVariants = computed(() => {
  const asset = activeAsset.value
  if (!asset) return []
  if (!normalizedQuery.value) return asset.variants || []
  const assetMatches = [asset.canonical_name, ...(asset.aliases || [])]
    .some(value => value.toLocaleLowerCase().includes(normalizedQuery.value))
  return assetMatches
    ? asset.variants || []
    : (asset.variants || []).filter(variant => variant.name.toLocaleLowerCase().includes(normalizedQuery.value))
})
const panelStyle = computed(() => ({
  top: `${position.value.top}px`,
  left: `${position.value.left}px`,
  width: `${position.value.width}px`,
  maxHeight: `${position.value.maxHeight}px`,
}))

function hasOwnVariantSelection(assetId: number) {
  return Object.prototype.hasOwnProperty.call(props.selectedVariantIds, assetId)
}

function isSelected(assetId: number, variantId: number | null) {
  if (!props.selectedAssetIds.includes(assetId)) return false
  if (variantId === null) {
    return !hasOwnVariantSelection(assetId) || props.selectedVariantIds[assetId] === null
  }
  return props.selectedVariantIds[assetId] === variantId
}

function assetThumbnail(asset: Asset) {
  if (props.selectedAssetIds.includes(asset.id)) {
    const variantId = props.selectedVariantIds[asset.id]
    const selectedVariant = asset.variants?.find(variant => variant.id === variantId)
    if (selectedVariant?.images[0]) return selectedVariant.images[0]
  }
  return asset.main_image || asset.angle_image_1 || asset.angle_image_2 || ''
}

function variantThumbnail(asset: Asset, variant?: AssetVariant) {
  if (variant) return variant.images[0] || ''
  return asset.main_image || asset.angle_image_1 || asset.angle_image_2 || ''
}

function variantIsAvailable(variant: AssetVariant) {
  return Boolean(variant.images[0])
}

function selectAsset(assetId: number) {
  activeAssetId.value = assetId
}

function selectVariant(assetId: number, variantId: number | null) {
  if (variantId !== null) {
    const variant = props.assets
      .find(asset => asset.id === assetId)
      ?.variants?.find(item => item.id === variantId)
    if (!variant || !variantIsAvailable(variant)) return
  }
  emit('select', {
    assetId,
    variantId,
    selected: props.selectionMode === 'replace' || !isSelected(assetId, variantId),
  })
}

function updatePlacement() {
  if (!props.open) return
  const anchor = document.getElementById(props.anchorId)
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  const viewportPadding = 12
  const width = Math.min(PANEL_MAX_WIDTH, window.innerWidth - viewportPadding * 2)
  const belowTop = rect.bottom + 8
  const availableBelow = window.innerHeight - belowTop - viewportPadding
  const maxHeight = props.placement === 'below'
    ? Math.min(460, Math.max(180, availableBelow))
    : Math.min(460, window.innerHeight - viewportPadding * 2)
  const measuredHeight = Math.min(panel.value?.scrollHeight || 360, maxHeight)
  const roomBelow = window.innerHeight - rect.bottom - viewportPadding
  const opensUp = props.placement === 'auto' && roomBelow < measuredHeight && rect.top > roomBelow
  const top = opensUp
    ? Math.max(viewportPadding, rect.top - measuredHeight - 8)
    : props.placement === 'below'
      ? belowTop
      : Math.min(belowTop, window.innerHeight - measuredHeight - viewportPadding)
  position.value = {
    top,
    left: Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - width - viewportPadding)),
    width,
    maxHeight,
  }
}

function closeFromOutside(event: PointerEvent) {
  if (!props.open) return
  const target = event.target as Node
  const anchor = document.getElementById(props.anchorId)
  if (!panel.value?.contains(target) && !anchor?.contains(target)) emit('close')
}

function closeFromEscape(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape') emit('close')
}

watch(() => props.open, async open => {
  if (!open) {
    query.value = ''
    return
  }
  activeAssetId.value = props.initialAssetId || props.selectedAssetIds[0] || props.assets[0]?.id || 0
  await nextTick()
  updatePlacement()
  searchInput.value?.focus()
})

watch(filteredAssets, items => {
  if (!items.some(asset => asset.id === activeAssetId.value)) activeAssetId.value = items[0]?.id || 0
})

onMounted(() => {
  window.addEventListener('pointerdown', closeFromOutside)
  window.addEventListener('keydown', closeFromEscape)
  window.addEventListener('resize', updatePlacement)
  window.addEventListener('scroll', updatePlacement, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', closeFromOutside)
  window.removeEventListener('keydown', closeFromEscape)
  window.removeEventListener('resize', updatePlacement)
  window.removeEventListener('scroll', updatePlacement, true)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="asset-variant-picker">
      <section
        v-if="open"
        ref="panel"
        class="scene-asset-variant-picker"
        :style="panelStyle"
        role="dialog"
        :aria-label="`${selectionMode === 'replace' ? '替换' : '选择'}${label}及衍生状态`"
      >
        <header class="scene-asset-variant-picker__header">
          <label>
            <Search :size="17" />
            <input ref="searchInput" v-model="query" type="search" :placeholder="`搜索${selectionMode === 'replace' ? '替换' : ''}${label}或衍生状态`" @keydown.esc.stop="emit('close')">
          </label>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭资产选择器" @click="emit('close')"><X :size="16" /></AppButton>
        </header>

        <div v-if="filteredAssets.length" class="scene-asset-variant-picker__body">
          <nav :aria-label="`${label}主体`">
            <button
              v-for="asset in filteredAssets"
              :key="asset.id"
              type="button"
              :class="{ 'is-active': activeAsset?.id === asset.id, 'is-selected': selectedAssetIds.includes(asset.id) }"
              @click="selectAsset(asset.id)"
            >
              <span class="scene-asset-variant-picker__thumb"><img v-if="assetThumbnail(asset)" :src="assetThumbnail(asset)" alt=""><ImageIcon v-else :size="16" /></span>
              <span><strong>{{ asset.canonical_name }}</strong><small v-if="asset.variants?.length">{{ asset.variants.length }} 个衍生状态</small><small v-else>仅基础形态</small></span>
              <Check v-if="selectedAssetIds.includes(asset.id)" class="scene-asset-variant-picker__selected-mark" :size="14" />
              <ChevronRight v-else :size="15" />
            </button>
          </nav>

          <div v-if="activeAsset" class="scene-asset-variant-picker__variants" :aria-label="`${activeAsset.canonical_name}的衍生状态`">
            <button
              type="button"
              :class="{ 'is-selected': isSelected(activeAsset.id, null) }"
              @click="selectVariant(activeAsset.id, null)"
            >
              <span class="scene-asset-variant-picker__thumb"><img v-if="variantThumbnail(activeAsset)" :src="variantThumbnail(activeAsset)" alt=""><ImageIcon v-else :size="16" /></span>
              <span><strong>{{ activeAsset.canonical_name }}</strong><small>基础形态</small></span>
              <span class="scene-asset-variant-picker__check"><Check v-if="isSelected(activeAsset.id, null)" :size="14" /></span>
            </button>
            <button
              v-for="variant in visibleVariants"
              :key="variant.id"
              type="button"
              :disabled="!variantIsAvailable(variant)"
              :aria-disabled="!variantIsAvailable(variant)"
              :class="{ 'is-selected': isSelected(activeAsset.id, variant.id), 'is-unavailable': !variantIsAvailable(variant) }"
              @click="selectVariant(activeAsset.id, variant.id)"
            >
              <span class="scene-asset-variant-picker__thumb" :class="{ 'is-empty': !variantIsAvailable(variant) }"><img v-if="variantThumbnail(activeAsset, variant)" :src="variantThumbnail(activeAsset, variant)" alt=""></span>
              <span><strong>{{ activeAsset.canonical_name }} · {{ variant.name }}</strong><small>{{ variantIsAvailable(variant) ? (variant.description || '衍生形态') : '尚未生成' }}</small></span>
              <span class="scene-asset-variant-picker__check"><Check v-if="variantIsAvailable(variant) && isSelected(activeAsset.id, variant.id)" :size="14" /></span>
            </button>
            <p v-if="normalizedQuery && !visibleVariants.length">该主体没有匹配的衍生状态，可选择基础形态。</p>
          </div>
        </div>
        <p v-else class="scene-asset-variant-picker__empty">没有匹配的资产或衍生状态</p>
      </section>
    </Transition>
  </Teleport>
</template>

<style scoped>
.scene-asset-variant-picker { position: fixed; z-index: 120; display: grid; overflow: hidden; grid-template-rows: auto minmax(0,1fr); border-radius: 14px; color: var(--app-text); background: var(--app-surface-raised); box-shadow: 0 18px 48px rgb(35 39 58 / 16%), inset 0 0 0 1px var(--app-border); backdrop-filter: blur(18px); }
.scene-asset-variant-picker__header { display: flex; align-items: center; gap: 8px; padding: 10px; border-bottom: 1px solid var(--app-border); }
.scene-asset-variant-picker__header label { display: flex; min-width: 0; min-height: 42px; flex: 1; align-items: center; gap: 9px; padding: 0 12px; border-radius: 10px; color: var(--app-text-muted); background: var(--app-surface); box-shadow: inset 0 0 0 1px var(--app-border-strong); }
.scene-asset-variant-picker__header label:focus-within { color: var(--app-accent); box-shadow: inset 0 0 0 2px color-mix(in srgb,var(--app-accent) 36%,transparent); }
.scene-asset-variant-picker__header input { min-width: 0; flex: 1; border: 0; outline: 0; color: var(--app-text); background: transparent; font: inherit; font-size: 12px; }
.scene-asset-variant-picker__body { display: grid; min-height: 230px; overflow: hidden; grid-template-columns: minmax(190px,40%) minmax(0,1fr); }
.scene-asset-variant-picker nav,.scene-asset-variant-picker__variants { min-height: 0; overflow-y: auto; padding: 8px; }
.scene-asset-variant-picker nav,.scene-asset-variant-picker__variants { scrollbar-width: none; }
.scene-asset-variant-picker nav::-webkit-scrollbar,.scene-asset-variant-picker__variants::-webkit-scrollbar { display: none; }
.scene-asset-variant-picker nav { border-right: 1px solid var(--app-border); }
.scene-asset-variant-picker button { width: 100%; border: 0; color: var(--app-text-secondary); background: transparent; font: inherit; cursor: pointer; }
.scene-asset-variant-picker nav button,.scene-asset-variant-picker__variants button { display: grid; min-height: 54px; grid-template-columns: 38px minmax(0,1fr) 18px; align-items: center; gap: 9px; padding: 8px; border-radius: 9px; text-align: left; transition: color 140ms ease,background 140ms ease,transform 140ms ease; }
.scene-asset-variant-picker nav button:hover,.scene-asset-variant-picker__variants button:hover { color: var(--app-text); background: var(--app-surface-hover); }
.scene-asset-variant-picker nav button:active,.scene-asset-variant-picker__variants button:active { transform: scale(.992); }
.scene-asset-variant-picker nav button.is-active,.scene-asset-variant-picker__variants button.is-selected { color: var(--app-accent); background: var(--app-accent-soft); }
.scene-asset-variant-picker__variants button.is-unavailable { color: var(--app-text-muted); background: transparent; cursor: not-allowed; opacity: .58; }
.scene-asset-variant-picker__variants button.is-unavailable:hover { color: var(--app-text-muted); background: transparent; }
.scene-asset-variant-picker__variants button.is-unavailable:active { transform: none; }
.scene-asset-variant-picker button > span:nth-child(2) { display: grid; min-width: 0; gap: 3px; }
.scene-asset-variant-picker button strong,.scene-asset-variant-picker button small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scene-asset-variant-picker button strong { font-size: 12px; font-weight: 650; }
.scene-asset-variant-picker button small { color: var(--app-text-muted); font-size: 9px; font-weight: 450; }
.scene-asset-variant-picker__thumb { display: grid; width: 38px; height: 38px; overflow: hidden; place-items: center; border-radius: 8px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.scene-asset-variant-picker__thumb.is-empty { box-shadow: inset 0 0 0 1px var(--app-border); }
.scene-asset-variant-picker__thumb img { width: 100%; height: 100%; object-fit: cover; }
.scene-asset-variant-picker__selected-mark { color: var(--app-accent); }
.scene-asset-variant-picker__check { display: grid; width: 18px; height: 18px; place-items: center; border-radius: 6px; color: #fff; background: transparent; box-shadow: inset 0 0 0 1px var(--app-border-strong); }
.scene-asset-variant-picker__variants button.is-selected .scene-asset-variant-picker__check { background: var(--app-accent); box-shadow: none; }
.scene-asset-variant-picker__variants > p,.scene-asset-variant-picker__empty { margin: 0; color: var(--app-text-muted); font-size: 10px; text-align: center; }
.scene-asset-variant-picker__variants > p { padding: 18px 8px; }
.scene-asset-variant-picker__empty { display: grid; min-height: 180px; place-items: center; padding: 20px; }
.asset-variant-picker-enter-active,.asset-variant-picker-leave-active { transition: opacity 150ms ease,transform 180ms cubic-bezier(.2,.8,.2,1); transform-origin: top left; }
.asset-variant-picker-enter-from,.asset-variant-picker-leave-to { opacity: 0; transform: translateY(-5px) scale(.985); }
@media (max-width: 620px) { .scene-asset-variant-picker__body { grid-template-columns: minmax(126px,40%) minmax(0,1fr); }.scene-asset-variant-picker nav,.scene-asset-variant-picker__variants { padding: 5px; }.scene-asset-variant-picker nav button,.scene-asset-variant-picker__variants button { grid-template-columns: 32px minmax(0,1fr) 16px; gap: 6px; padding: 6px; }.scene-asset-variant-picker__thumb { width: 32px; height: 32px; } }
@media (prefers-reduced-motion: reduce) { .scene-asset-variant-picker * { transition-duration: 1ms !important; } }
</style>
