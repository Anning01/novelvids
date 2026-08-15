<script setup lang="ts">
import { ChevronDown, UserRoundSearch, X } from 'lucide-vue-next'

withDefaults(defineProps<{
  modelValue?: unknown
  title?: string
  previewUrl?: string
  selected?: boolean
}>(), {
  modelValue: undefined,
  title: '选择数字人',
  previewUrl: '',
  selected: false,
})

const emit = defineEmits<{
  open: []
  clear: []
}>()
</script>

<template>
  <div class="digital-human-generation-control">
    <button
      type="button"
      class="digital-human-generation-control__trigger nodrag"
      :aria-label="selected ? `更换数字人 ${title}` : '选择数字人'"
      title="人物资产展示（非参考图）"
      @click="emit('open')"
    >
      <img v-if="previewUrl" :src="previewUrl" alt="">
      <UserRoundSearch v-else :size="16" aria-hidden="true" />
      <span>选择数字人</span>
      <ChevronDown :size="14" aria-hidden="true" />
    </button>
    <button
      v-if="selected"
      type="button"
      class="digital-human-generation-control__clear"
      aria-label="移除数字人人物"
      title="移除数字人人物"
      @click="emit('clear')"
    >
      <X :size="13" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.digital-human-generation-control {
  display: flex;
  width: 126px;
  min-width: 0;
  align-items: center;
  gap: 5px;
}
.digital-human-generation-control__trigger {
  display: flex;
  min-width: 0;
  height: 34px;
  flex: 1;
  align-items: center;
  gap: 7px;
  padding: 4px 8px;
  border: 1px solid #4a433d;
  border-radius: 9px;
  color: #ded6ce;
  background: #292522;
  cursor: pointer;
  font: inherit;
  font-size: 10px;
}
.digital-human-generation-control__trigger:hover,
.digital-human-generation-control__trigger:focus-visible,
.digital-human-generation-control__clear:hover,
.digital-human-generation-control__clear:focus-visible {
  border-color: #8f76d8;
  color: #eee8e1;
  outline: none;
}
.digital-human-generation-control__trigger img {
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: 5px;
  object-fit: cover;
}
.digital-human-generation-control__trigger > span {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.digital-human-generation-control__trigger > svg,
.digital-human-generation-control__clear {
  flex: none;
}
.digital-human-generation-control__clear {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid #4a433d;
  border-radius: 9px;
  color: #a99f96;
  background: #292522;
  cursor: pointer;
}
</style>
