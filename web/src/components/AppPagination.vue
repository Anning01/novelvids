<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  page: number
  pageSize: number
  total: number
  pageSizeOptions?: number[]
}>(), {
  pageSizeOptions: () => [10, 20, 50, 100],
})

const emit = defineEmits<{
  (event: 'page-change', page: number): void
  (event: 'size-change', pageSize: number): void
}>()

const pages = computed(() => (props.total > 0 ? Math.max(1, Math.ceil(props.total / props.pageSize)) : 0))

function changePage(next: number) {
  if (next < 1 || next > pages.value) return
  emit('page-change', next)
}
</script>

<template>
  <footer v-if="total > 0" class="app-pagination">
    <span class="app-pagination__total">共 {{ total }} 条</span>
    <div class="app-pagination__controls">
      <select
        class="app-pagination__size"
        :value="pageSize"
        aria-label="每页条数"
        @change="emit('size-change', Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="option in pageSizeOptions" :key="option" :value="option">{{ option }} 条/页</option>
      </select>
      <button type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
      <span>{{ page }} / {{ pages }}</span>
      <button type="button" :disabled="page >= pages" @click="changePage(page + 1)">下一页</button>
    </div>
  </footer>
</template>

<style scoped>
.app-pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 2px 2px; }
.app-pagination__total { color: var(--app-text-muted, #9398a8); font-size: 11px; }
.app-pagination__controls { display: flex; align-items: center; gap: 10px; }
.app-pagination__controls > span { color: var(--app-text-muted, #9398a8); font-size: 11px; font-variant-numeric: tabular-nums; }
.app-pagination button { padding: 6px 12px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 8px; color: var(--app-text-secondary, #656b7b); background: var(--app-surface, #fff); cursor: pointer; font-size: 11px; }
.app-pagination button:hover:not(:disabled) { color: var(--app-text, #303442); background: var(--app-surface-hover, #f0f1f6); }
.app-pagination button:disabled { opacity: 0.45; cursor: default; }
.app-pagination__size { height: 28px; padding: 0 8px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 8px; color: var(--app-text-secondary, #656b7b); background: var(--app-surface, #fff); font-size: 11px; }
</style>
