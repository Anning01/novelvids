<script setup lang="ts">
import { Upload, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import {
  normalizeWatermarkConfig,
  WATERMARK_PRESETS,
  watermarkPresetConfig,
  type WatermarkConfig,
  type WatermarkPreset,
} from '../config/watermarkConfig'

const props = defineProps<{ open: boolean; modelValue: WatermarkConfig; uploading?: boolean }>()
const emit = defineEmits<{ close: []; change: [value: WatermarkConfig]; upload: [file: File] }>()
const draft = ref(normalizeWatermarkConfig(props.modelValue))
const preset = computed(() => WATERMARK_PRESETS.find(item => {
  const value = watermarkPresetConfig(item.value)
  return value.x === draft.value.x && value.y === draft.value.y
})?.value || '')

watch(() => props.modelValue, value => { draft.value = normalizeWatermarkConfig(value) }, { deep: true })

function changePreset(event: Event) {
  const value = (event.target as HTMLSelectElement).value as WatermarkPreset
  if (!value) return
  draft.value = { ...draft.value, ...watermarkPresetConfig(value), resourceUrl: draft.value.resourceUrl }
  emit('change', normalizeWatermarkConfig(draft.value))
}
function changeNumber(field: 'x' | 'y' | 'scale', event: Event) {
  draft.value = normalizeWatermarkConfig({ ...draft.value, [field]: Number((event.target as HTMLInputElement).value) })
  emit('change', { ...draft.value })
}
function upload(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) emit('upload', file)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="workbench-dialog-backdrop" @mousedown.self="$emit('close')">
      <section class="workbench-watermark-dialog" role="dialog" aria-modal="true" aria-label="设置成片水印">
        <header>
          <div>
            <h2>设置成片水印</h2>
            <p>选择组织模板或上传图片，并调整水印位置和大小。</p>
          </div>
          <button type="button" aria-label="关闭水印设置" title="Close" @click="$emit('close')"><X :size="18" aria-hidden="true" /></button>
        </header>

        <div class="workbench-watermark-dialog__template-row">
          <label>组织模板
            <select aria-label="组织模板" disabled><option>不使用模板</option></select>
          </label>
          <a href="/watermark-templates" target="_blank" rel="noopener">管理模板</a>
        </div>

        <div class="workbench-watermark-dialog__preview" aria-label="水印预览">
          <span>9:16</span>
          <img
            v-if="draft.resourceUrl"
            :src="draft.resourceUrl"
            alt="水印预览图"
            :style="{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.scale * 100}%` }"
          >
          <label class="workbench-watermark-dialog__upload" :class="{ 'is-loading': uploading }">
            <Upload :size="19" aria-hidden="true" />
            {{ uploading ? '上传中…' : '上传水印图片' }}
            <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="上传水印图片" :disabled="uploading" @change="upload">
          </label>
        </div>

        <div class="workbench-watermark-dialog__fields">
          <label>预设位置
            <select aria-label="水印位置" :value="preset" @change="changePreset">
              <option v-for="item in WATERMARK_PRESETS" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label>横向位置
            <span>{{ Math.round(draft.x * 100) }}%</span>
            <input type="range" aria-label="横向位置" min="0" max="1" step="0.01" :value="draft.x" @change="changeNumber('x', $event)">
          </label>
          <label>纵向位置
            <span>{{ Math.round(draft.y * 100) }}%</span>
            <input type="range" aria-label="纵向位置" min="0" max="1" step="0.01" :value="draft.y" @change="changeNumber('y', $event)">
          </label>
          <label>缩放
            <span>{{ Math.round(draft.scale * 100) }}%</span>
            <input type="range" aria-label="缩放" min="0.05" max="1" step="0.01" :value="draft.scale" @change="changeNumber('scale', $event)">
          </label>
        </div>
      </section>
    </div>
  </Teleport>
</template>
