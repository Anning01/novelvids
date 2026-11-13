<script setup lang="ts">
import { tr } from '@/i18n'
import ImageModelSelect from './ImageModelSelect.vue'

defineProps<{ enabled: boolean; disabled: boolean }>()
const model = defineModel<string>({required: true})
const emit = defineEmits<{ toggle: [enabled: boolean] }>()
</script>
<template>
  <div class="sheet-options">
    <label><input type="checkbox" :checked="enabled" :disabled="disabled"
      @change="emit('toggle', ($event.target as HTMLInputElement).checked)" />{{ tr('同时生成故事版') }}</label>
    <ImageModelSelect v-if="enabled" v-model="model" :label="tr('线稿生图模型')" :empty-label="tr('选择故事版生图模型')" :disabled="disabled" />
  </div>
</template>
<style scoped>
.sheet-options, .sheet-options label { display: inline-flex; align-items: center; gap: 6px; }
.sheet-options { flex-wrap: wrap; }
.sheet-options label { color: var(--app-text-secondary); font-size: 12px; white-space: nowrap; }
.sheet-options input { accent-color: var(--app-accent); }
</style>
