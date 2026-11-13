<script setup lang="ts">
import { ref, watch } from 'vue'
import AppSelect from './AppSelect.vue'
import AppButton from './AppButton.vue'
import { agentApi } from '@/features/creation-agent/api'
import { tr } from '@/i18n'

const props = defineProps<{ projectId: number; stage: 'assets' | 'storyboard'; label: string; disabled: boolean }>()
const selected = defineModel<string>({ required: true })
const options = ref<{ value: string; label: string }[]>([])
const error = ref('')
const loading = ref(false)
const retry = ref(0)
const preferenceKey = () => `novelvids:model:${props.projectId}:${props.stage}`

watch([() => props.projectId, retry], async ([id], _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  loading.value = true
  error.value = ''
  options.value = []
  selected.value = ''
  try {
    const { data } = await agentApi.capabilities(id)
    if (!current) return
    options.value = data.models.map(model => ({value: String(model.id), label: model.name || model.model}))
    const saved = sessionStorage.getItem(preferenceKey())
    selected.value = options.value.find(option => option.value === saved)?.value ?? ''
  } catch (caught) {
    if (current) error.value = (caught as Error).message
  } finally {
    if (current) loading.value = false
  }
}, { immediate: true })

function choose(value: string) {
  selected.value = value
  sessionStorage.setItem(preferenceKey(), value)
}
</script>

<template>
  <AppSelect :model-value="selected" :ariaLabel="label" density="compact"
    :options="[{value: '', label: loading ? tr('正在读取模型…') : options.length ? label : tr('无可用模型')}, ...options]"
    :disabled="disabled || !options.length" @update:model-value="choose" />
  <template v-if="error">
    <small role="alert">{{ error }}</small>
    <AppButton variant="ghost" size="xs" @click="retry++">{{ tr('重试') }}</AppButton>
  </template>
</template>
