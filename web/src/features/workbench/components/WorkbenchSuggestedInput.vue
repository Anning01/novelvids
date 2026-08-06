<script setup lang="ts">
import { ChevronDown } from 'lucide-vue-next'
import { ref } from 'vue'

defineProps<{
  modelValue: string
  suggestions: Array<{ value: string; label?: string }>
  label: string
  placeholder?: string
  pattern?: string
  inputmode?: 'none' | 'text' | 'decimal' | 'numeric' | 'tel' | 'search' | 'email' | 'url'
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const open = ref(false)

function update(value: string) {
  emit('update:modelValue', value)
}

function toggleSuggestions() {
  open.value = !open.value
}

function selectSuggestion(value: string) {
  update(value)
  open.value = false
}

function handleFocusOut(event: FocusEvent) {
  const container = event.currentTarget as HTMLElement | null
  const next = event.relatedTarget as Node | null
  if (!container || !next || !container.contains(next)) open.value = false
}
</script>

<template>
  <div
    class="workbench-suggested-input nodrag nowheel"
    @focusout="handleFocusOut"
    @pointerdown.stop
    @click.stop
    @wheel.stop
  >
    <input
      type="text"
      :aria-label="label"
      :value="modelValue"
      :placeholder="placeholder"
      :pattern="pattern"
      :inputmode="inputmode"
      autocomplete="off"
      @focus="open = true"
      @keydown.down.prevent="open = true"
      @keydown.esc.stop="open = false"
      @input="update(($event.target as HTMLInputElement).value)"
    >
    <button
      type="button"
      class="workbench-suggested-input__toggle"
      :class="{ 'is-open': open }"
      :aria-label="`${open ? '关闭' : '打开'}${label}推荐值`"
      :aria-expanded="open"
      @pointerdown.prevent
      @click="toggleSuggestions"
    >
      <span aria-hidden="true"><ChevronDown :size="16" /></span>
    </button>
    <div
      v-if="open && suggestions.length"
      class="workbench-suggested-input__menu workbench-scroll-region nowheel"
      :aria-label="`${label}推荐值`"
      role="listbox"
    >
      <button
        v-for="suggestion in suggestions"
        :key="suggestion.value"
        type="button"
        role="option"
        :aria-selected="modelValue === suggestion.value"
        @pointerdown.prevent
        @click="selectSuggestion(suggestion.value)"
      >
        <strong>{{ suggestion.value }}</strong>
        <small>{{ suggestion.label || suggestion.value }}</small>
      </button>
    </div>
  </div>
</template>
