<script setup lang="ts">
import { computed } from 'vue'
import { Filter, RotateCcw, Search, X } from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import type { AppSelectOption } from '@/components/AppSelect.vue'

export interface SearchFilterDefinition {
  key: string
  label: string
  options: AppSelectOption[]
  allLabel?: string
  width?: number
  required?: boolean
}

const props = withDefaults(defineProps<{
  modelValue: string
  filterValues: Record<string, string>
  filters?: SearchFilterDefinition[]
  placeholder?: string
  searchAriaLabel?: string
  resultLabel?: string
}>(), {
  filters: () => [],
  placeholder: '搜索',
  searchAriaLabel: '搜索',
  resultLabel: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:filterValues': [value: Record<string, string>]
}>()

const activeFilterCount = computed(() => props.filters.filter(filter => !filter.required && props.filterValues[filter.key]).length)

function optionsFor(filter: SearchFilterDefinition): AppSelectOption[] {
  return filter.required ? filter.options : [{ value: '', label: filter.allLabel || `全部${filter.label}` }, ...filter.options]
}

function updateFilter(key: string, value: string) {
  emit('update:filterValues', { ...props.filterValues, [key]: value })
}

function clearFilters() {
  emit('update:filterValues', Object.fromEntries(Object.keys(props.filterValues).map(key => {
    const definition = props.filters.find(filter => filter.key === key)
    return [key, definition?.required ? props.filterValues[key] : '']
  })))
}
</script>

<template>
  <div class="search-filter-bar">
    <label class="search-filter-bar__search">
      <Search :size="16" />
      <input
        :value="modelValue"
        type="search"
        :placeholder="placeholder"
        :aria-label="searchAriaLabel"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
      <AppButton v-if="modelValue" type="button" aria-label="清除搜索" title="清除搜索" @click="$emit('update:modelValue', '')"><X :size="15" /></AppButton>
    </label>

    <div v-if="filters.length" class="search-filter-bar__filters" aria-label="过滤条件">
      <AppSelect
        v-for="filter in filters"
        :key="filter.key"
        :model-value="filterValues[filter.key] || ''"
        :options="optionsFor(filter)"
        :ariaLabel="`${filter.label}过滤`"
        :menu-label="filter.label"
        :menu-width="filter.width"
        @update:model-value="updateFilter(filter.key, $event)"
      >
        <template #leading><Filter :size="14" /></template>
      </AppSelect>
      <AppButton v-if="activeFilterCount" class="search-filter-bar__reset" type="button" title="清除全部过滤" @click="clearFilters"><RotateCcw :size="14" /><span>清除 {{ activeFilterCount }}</span></AppButton>
    </div>

    <span v-if="resultLabel" class="search-filter-bar__result">{{ resultLabel }}</span>
  </div>
</template>

<style scoped>
.search-filter-bar { display: flex; align-items: center; gap: 9px; }
.search-filter-bar__search { display: flex; min-width: 220px; min-height: 40px; flex: 1 1 320px; align-items: center; gap: 9px; padding: 0 11px; border: 1px solid #dfe2ea; border-radius: 9px; color: #9297a6; background: #fff; transition: border-color .15s ease, box-shadow .15s ease; }
.search-filter-bar__search:focus-within { border-color: #8586f7; box-shadow: 0 0 0 3px rgb(91 92 246 / 8%); }
.search-filter-bar__search input { min-width: 0; flex: 1; border: 0; outline: 0; color: #3f4454; background: transparent; font: inherit; font-size: 11px; appearance: none; }
.search-filter-bar__search input::-webkit-search-cancel-button { display: none; }
.search-filter-bar__search input::placeholder { color: #a3a7b4; }
.search-filter-bar__search button, .search-filter-bar__reset { display: inline-flex; min-height: 28px; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 7px; color: #858a99; background: transparent; cursor: pointer; }
.search-filter-bar__search button { width: 28px; flex: 0 0 auto; padding: 0; }
.search-filter-bar__search button:hover, .search-filter-bar__reset:hover { color: #595be8; background: #f0f0ff; }
.search-filter-bar__filters { display: flex; flex: 0 1 auto; align-items: center; gap: 7px; }
.search-filter-bar__filters :deep(.app-select) { width: 128px; }
.search-filter-bar__filters :deep(.app-select__trigger) { min-height: 40px; }
.search-filter-bar__reset { flex: 0 0 auto; padding: 0 9px; font-size: 10px; white-space: nowrap; }
.search-filter-bar__result { flex: 0 0 auto; color: #9297a6; font-size: 10px; white-space: nowrap; }
@media (max-width: 980px) {
  .search-filter-bar { flex-wrap: wrap; }
  .search-filter-bar__search { flex-basis: calc(100% - 90px); }
  .search-filter-bar__filters { order: 3; width: 100%; overflow-x: auto; padding-bottom: 2px; }
}
@media (max-width: 560px) {
  .search-filter-bar__search { min-width: 0; flex-basis: 100%; }
  .search-filter-bar__result { margin-left: auto; }
  .search-filter-bar__filters :deep(.app-select) { min-width: 122px; }
}
</style>
