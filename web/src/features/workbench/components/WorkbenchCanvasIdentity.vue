<script setup lang="ts">
import { Check, ChevronDown, Pencil } from 'lucide-vue-next'
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{ name: string; chapterNumber: number; saving?: boolean }>()
const emit = defineEmits<{ rename: [name: string] }>()
const editing = ref(false)
const draft = ref(props.name)
const input = ref<HTMLInputElement | null>(null)

watch(() => props.name, value => { if (!editing.value) draft.value = value })

function beginEdit() {
  draft.value = props.name
  editing.value = true
  void nextTick(() => { input.value?.focus(); input.value?.select() })
}
function save() {
  const value = draft.value.trim()
  editing.value = false
  if (value && value !== props.name) emit('rename', value)
}
</script>

<template>
  <div class="workbench-canvas-identity">
    <button v-if="!editing" type="button" aria-label="编辑画布名称" @click="beginEdit">
      <span>第 {{ chapterNumber }} 章</span>
      <strong>{{ name || '未命名画布' }}</strong>
      <ChevronDown :size="14" aria-hidden="true" />
    </button>
    <form v-else @submit.prevent="save">
      <span>第 {{ chapterNumber }} 章</span>
      <input ref="input" v-model="draft" maxlength="120" aria-label="画布名称" @keydown.esc.prevent="editing = false" @blur="save">
      <button type="submit" aria-label="保存画布名称" :disabled="saving"><Check v-if="!saving" :size="14" /><Pencil v-else :size="14" /></button>
    </form>
  </div>
</template>

<style scoped>
.workbench-canvas-identity { min-width: 0; }
.workbench-canvas-identity > button,
.workbench-canvas-identity form { display: flex; min-height: 34px; align-items: center; gap: 7px; padding: 3px 9px; border: 1px solid #3b3631; border-radius: 10px; color: #d8d0c8; background: rgb(33 30 27 / 92%); box-shadow: 0 8px 24px rgb(0 0 0 / 22%); }
.workbench-canvas-identity > button { cursor: pointer; }
.workbench-canvas-identity span { color: #91877e; font-size: 10px; white-space: nowrap; }
.workbench-canvas-identity strong { max-width: 260px; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.workbench-canvas-identity input { width: min(260px, 34vw); border: 0; outline: 0; color: #eee9e2; background: transparent; font: inherit; font-size: 12px; font-weight: 650; }
.workbench-canvas-identity form button { display: grid; width: 26px; height: 26px; padding: 0; border: 0; border-radius: 7px; place-items: center; color: #cfc5bb; background: #3a354f; cursor: pointer; }
</style>
