<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { tr } from '@/i18n'
import AppButton from './AppButton.vue'
import AppSelect from './AppSelect.vue'
import type { ImageGenerationModel } from '@/types'

defineProps<{ modelValue: string; label: string; emptyLabel: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const models = ref<ImageGenerationModel[]>([])
const loading = ref(true)
const error = ref('')
const choices = computed(() => models.value.map(model => ({ value: String(model.config_id), label: model.name || model.model })))

async function load() {
  loading.value = true
  error.value = ''
  try {
    models.value = (await api.imageGenerationModels()).data
  } catch (caught) {
    error.value = (caught as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="image-model-select">
    <AppSelect :model-value="modelValue" :ariaLabel="label" density="compact"
      :options="[{ value: '', label: emptyLabel }, ...choices]" :disabled="disabled || loading || !choices.length"
      @update:model-value="emit('update:modelValue', $event)" />
    <small v-if="loading" role="status">{{ tr('正在读取模型…') }}</small>
    <template v-else-if="error">
      <small role="alert">{{ error }}</small><AppButton size="xs" variant="ghost" @click="load">{{ tr('重试') }}</AppButton>
    </template>
    <small v-else-if="!choices.length">{{ tr('无可用模型') }}</small>
  </div>
</template>

<style scoped>
.image-model-select { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; min-width: 0; }
.image-model-select small { color: var(--app-text-secondary); }
.image-model-select small[role='alert'] { color: var(--creation-danger); }
</style>
