<script setup lang="ts">
import type { EnumItem } from '@/types'
import { computed } from 'vue'
import WorkbenchSelect from './WorkbenchSelect.vue'

const props = defineProps<{
  modelValue: number | null
  options: EnumItem[]
  label?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

const selectOptions = computed(() => props.options.map(option => ({
  value: String(option.value),
  label: option.label,
})))

const selectedValue = computed(() => {
  const configured = String(props.modelValue ?? '')
  return selectOptions.value.some(option => option.value === configured)
    ? configured
    : selectOptions.value[0]?.value || ''
})

function select(value: string) {
  const modelType = Number(value)
  if (Number.isFinite(modelType)) emit('update:modelValue', modelType)
}
</script>

<template>
  <div class="media-generation-model-selector">
    <WorkbenchSelect
      :model-value="selectedValue"
      :options="selectOptions"
      :label="label || '视频模型'"
      :placeholder="`选择${label || '视频模型'}`"
      @update:model-value="select"
    />
  </div>
</template>

<style scoped>
.media-generation-model-selector {
  min-width: 0;
}
</style>
