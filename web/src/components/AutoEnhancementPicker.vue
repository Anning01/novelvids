<script setup lang="ts">
import { computed } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import { tr } from '@/i18n'
import { money } from '@/features/billing/recordDisplay'
import { enhancementEstimate, resolutionShortSide } from '@/shared/autoEnhancement'
import type { AutoEnhancement } from '@/types'
import type { EnhancementModel } from '@/features/video-export/api'

const props = withDefaults(defineProps<{ modelValue: AutoEnhancement | null; models: EnhancementModel[]; duration?: number; sourceResolution?: string; disabled?: boolean; menuClass?: string; menuZIndex?: number }>(), { duration: 0, sourceResolution: '' })
const emit = defineEmits<{ 'update:modelValue': [value: AutoEnhancement | null] }>()
const modelId = computed({ get: () => String(props.modelValue?.model_config_id || props.models[0]?.id || ''), set: value => {
  const target = props.models.find(item => String(item.id) === value)?.resolutions.find(item => item.short_side > resolutionShortSide(props.sourceResolution))?.value
  if (target) emit('update:modelValue', { model_config_id: Number(value), resolution: target as AutoEnhancement['resolution'], ...versionFor(Number(value)) })
} })
const model = computed(() => props.models.find(item => String(item.id) === modelId.value))
const targets = computed(() => (model.value?.resolutions || []).filter(item => item.short_side > resolutionShortSide(props.sourceResolution)))
const targetOptions = computed(() => [
  ...(props.modelValue && !targets.value.some(item => item.value === props.modelValue?.resolution) ? [{ value: props.modelValue.resolution, label: tr('{p0}（不可用）', { p0: props.modelValue.resolution.toUpperCase() }) }] : []),
  ...targets.value.map(item => ({ value: item.value, label: item.value.toUpperCase() })),
])
const resolution = computed({ get: () => props.modelValue?.resolution || targets.value[0]?.value || '', set: value => emit('update:modelValue', { model_config_id: Number(modelId.value), resolution: value as AutoEnhancement['resolution'], ...versionFor(Number(modelId.value)) }) })
function versionFor(id: number) { const value = props.models.find(item => item.id === id)?.config_version; return value ? { config_version: value } : {} }
const estimate = computed(() => {
  const target = targets.value.find(item => item.value === resolution.value)
  return target && props.duration > 0 ? enhancementEstimate(model.value?.pricing, target.short_side, props.duration) : null
})
function toggle() {
  if (props.modelValue) emit('update:modelValue', null)
  else if (model.value && targets.value[0]) emit('update:modelValue', { model_config_id: model.value.id, resolution: targets.value[0].value as AutoEnhancement['resolution'], ...versionFor(model.value.id) })
}
</script>
<template>
  <section class="auto-enhancement-picker">
    <button type="button" class="auto-enhancement-toggle" role="switch" :aria-checked="Boolean(modelValue)" :aria-label="tr('生成后自动高清化')" :disabled="disabled || !models.length || (!modelValue && !targets.length)" @click="toggle"><Sparkles :size="17" aria-hidden="true" /><span><strong>{{ tr('生成后自动高清化') }}</strong><small>{{ tr('视频成功后自动增强，完成后替换当前版本') }}</small></span><i :class="{ 'is-on': modelValue }" /></button>
    <div v-if="modelValue" class="auto-enhancement-options"><AppSelect v-model="modelId" :options="models.map(item => ({ value: String(item.id), label: item.name }))" :ariaLabel="tr('自动高清化服务')" :disabled="disabled" :menu-class="menuClass" :menu-z-index="menuZIndex" /><AppSelect v-model="resolution" :options="targetOptions" :ariaLabel="tr('自动高清化目标')" :disabled="disabled" :menu-class="menuClass" :menu-z-index="menuZIndex" /><p>{{ estimate ? tr('增强预计 {p0}–{p1}，按实际时长和帧率结算', { p0: money(estimate.min), p1: money(estimate.max) }) : tr('增强费用按实际时长、帧率与所选服务价格结算') }}</p><p v-if="!targets.some(item => item.value === modelValue?.resolution)" role="alert">{{ tr('请选择高于生成分辨率且已启用的高清化目标') }}</p></div>
    <small v-else-if="!models.length">{{ tr('暂无可用增强服务，请先完成配置') }}</small>
  </section>
</template>
<style scoped>
.auto-enhancement-picker{color:var(--app-text);margin-top:12px}.auto-enhancement-toggle{display:flex;align-items:center;gap:10px;width:100%;padding:12px;border:1px solid var(--app-border);border-radius:10px;background:var(--app-surface-muted);color:var(--app-text);text-align:left;cursor:pointer}.auto-enhancement-toggle>svg{color:var(--app-accent);flex-shrink:0}.auto-enhancement-toggle>span{display:grid;gap:4px;flex:1}.auto-enhancement-toggle strong{font-size:12px}.auto-enhancement-toggle small,.auto-enhancement-picker>small{font-size:11px;color:var(--app-text-secondary);line-height:1.5}.auto-enhancement-toggle>i{display:block;flex-shrink:0;width:34px;height:21px;padding:3px;border-radius:99px;background:var(--app-border-strong)}.auto-enhancement-toggle>i::before{content:'';display:block;width:15px;height:15px;border-radius:50%;background:#fff}.auto-enhancement-toggle>i.is-on{background:var(--app-accent)}.auto-enhancement-toggle>i.is-on::before{margin-left:auto}.auto-enhancement-toggle:hover:not(:disabled){border-color:var(--app-accent)}.auto-enhancement-toggle:focus-visible{outline:2px solid var(--app-accent);outline-offset:2px}.auto-enhancement-toggle:disabled{opacity:.6;cursor:not-allowed}.auto-enhancement-options{display:grid;grid-template-columns:minmax(0,1fr) 110px;gap:8px;margin-top:8px}.auto-enhancement-options>p{grid-column:1/-1;margin:2px 0;color:var(--app-text-secondary);font-size:11px;line-height:1.6}.auto-enhancement-options>p[role=alert]{color:var(--creation-danger)}.auto-enhancement-options :deep(.app-select){min-width:0}
</style>
