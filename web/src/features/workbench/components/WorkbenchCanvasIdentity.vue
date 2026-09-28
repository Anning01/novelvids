<script setup lang="ts">
import { tr } from '@/i18n'

import { ref, watch } from 'vue'

const props = defineProps<{ name: string; chapterNumber: number; saving?: boolean }>()
const emit = defineEmits<{ rename: [name: string] }>()
const expanded = ref(false)
const editing = ref(false)
const draft = ref(props.name)

watch(() => props.name, (value) => {
  if (!editing.value) draft.value = value
})

function beginEditing() {
  draft.value = props.name
  editing.value = true
}

function save() {
  const value = draft.value.trim()
  editing.value = false
  if (value && value !== props.name) emit('rename', value)
}

function cancel() {
  draft.value = props.name
  editing.value = false
}
</script>

<template>
  <div class="workbench-identity nodrag nowheel" :class="{ 'is-expanded': expanded }">
    <button
      type="button"
      class="workbench-identity__trigger"
      :aria-expanded="expanded"
      :aria-label="tr('展开画布信息')"
      :title="tr('展开或收起画布信息')"
      @click="expanded = !expanded"
    >
      <span aria-hidden="true">{{ tr('画') }}</span>
    </button>
    <label>
      <span class="sr-only">{{ tr('画布名称') }}</span>
      <input
        v-model="draft"
        maxlength="120"
        :aria-label="tr('画布名称')"
        :disabled="saving"
        @focus="beginEditing"
        @blur="save"
        @keydown.enter.prevent.stop="save"
        @keydown.esc.prevent.stop="cancel"
        @keydown.stop
      >
      <small>{{ saving ? tr('保存中…') : tr('第 {p0} 章 · 点击修改名称', { p0: chapterNumber }) }}</small>
    </label>
  </div>
</template>
