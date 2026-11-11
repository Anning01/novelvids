<script setup lang="ts">
import { computed, ref } from 'vue'
import { AtSign, Film, Plus, X } from 'lucide-vue-next'
import { tr } from '@/i18n'
import MaterialMentionInput from '@/features/workbench/components/MaterialMentionInput.vue'
import { clipReferenceMentions } from './clipReferences'
import type { VideoReferenceMedia } from '@/types'

const props = defineProps<{modelValue: string; references: VideoReferenceMedia[]; uploading?: boolean; placeholder?: string}>()
const emit = defineEmits<{'update:modelValue':[value:string];remove:[index:number];upload:[];submit:[]}>()
const editor = ref<InstanceType<typeof MaterialMentionInput> | null>(null)
const mentions = computed(() => clipReferenceMentions(props.references))
function shortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !event.isComposing) {
    event.preventDefault()
    emit('submit')
  }
}
defineExpose({focus: () => editor.value?.focus()})
</script>
<template>
  <div class="clip-reference-prompt" @keydown.capture="shortcut">
    <div v-if="mentions.length" class="clip-reference-strip" :aria-label="tr('已上传参考素材')">
      <div v-for="(mention,index) in mentions" :key="mention.edgeKey" class="clip-reference">
        <button type="button" class="clip-reference-insert" :aria-label="tr('引用 {p0}', {p0:mention.name})" :title="references[index]?.name || mention.name" @mousedown.prevent @click="editor?.insertMaterial(mention)">
          <img v-if="mention.mediaKind === 'image'" :src="mention.previewUrl" :alt="mention.name"><video v-else :src="mention.previewUrl" muted playsinline preload="metadata" aria-hidden="true" /><span><Film v-if="mention.mediaKind === 'video'" :size="12" /><AtSign v-else :size="12" />{{ mention.name }}</span>
        </button>
        <button type="button" class="clip-reference-remove" :aria-label="tr('移除参考素材 {p0}', {p0:mention.name})" @click="emit('remove',index)"><X :size="12" /></button>
      </div>
      <button type="button" class="clip-reference-more" :disabled="uploading" :aria-label="tr('添加更多参考素材')" @click="emit('upload')"><Plus :size="18" /></button>
    </div>
    <MaterialMentionInput ref="editor" :model-value="modelValue" :materials="mentions" :mentions="mentions" :label="tr('创作想法')" :placeholder="placeholder ?? tr('描述画面、动作与氛围，输入 @ 引用已上传的素材…')" :show-hint="false" :show-reference-counts="false" @update:model-value="emit('update:modelValue',$event)" @add="(_material,text) => emit('update:modelValue',text)" />
    <p v-if="modelValue.length > 4000" class="clip-prompt-error" role="alert">{{ tr('创作描述不能超过 4000 字，请缩短后再提交。') }}</p>
  </div>
</template>
<style scoped>
.clip-reference-prompt { min-width: 0; }.clip-reference-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 8px 0 4px; }.clip-reference { position: relative; }.clip-reference-insert { display: flex; align-items: center; gap: 7px; max-width: 180px; padding: 4px 8px 4px 4px; border: 0; border-radius: 7px; background: var(--app-surface-muted); color: var(--app-text-secondary); cursor: pointer; }.clip-reference-insert > img,.clip-reference-insert > video { width: 42px; height: 38px; border-radius: 5px; object-fit: cover; }.clip-reference-insert > span { display: inline-flex; align-items: center; gap: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }.clip-reference-remove { position: absolute; right: -5px; top: -5px; display: grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 0; border-radius: 50%; color: var(--app-text-secondary); background: var(--app-surface-hover); cursor: pointer; }.clip-reference-more { display: grid; place-items: center; width: 38px; height: 38px; border: 0; border-radius: 7px; background: var(--app-surface-muted); color: var(--app-text-secondary); cursor: pointer; }
.clip-reference-prompt :deep(.workbench-mention-editor),.clip-reference-prompt :deep(.workbench-mention-editor.is-focused) { border: 0; box-shadow: none; background: transparent; }
.clip-reference-prompt :deep(.workbench-mention-editor__input) { min-height: 78px; max-height: 260px; padding: 12px 2px; border-radius: 0; color: var(--app-text); background: transparent; font-size: 14px; line-height: 1.8; }
.clip-reference-prompt :deep(.workbench-inline-mention) { border: 0; color: var(--app-accent); background: var(--app-accent-soft); }
.clip-reference-prompt :deep(.workbench-mention-menu) { z-index: 2000; width: min(340px, calc(100vw - 64px)); right: auto; left: 0; border: 0; color: var(--app-text); background: var(--app-surface); box-shadow: 0 12px 36px rgb(0 0 0 / 18%); }
.clip-reference-prompt :deep(.workbench-mention-menu__header),.clip-reference-prompt :deep(.workbench-mention-menu__copy strong) { color: var(--app-text); }.clip-reference-prompt :deep(.workbench-mention-menu__copy small),.clip-reference-prompt :deep(.workbench-mention-menu > p) { color: var(--app-text-secondary); }.clip-reference-prompt :deep(.workbench-mention-menu__options > button) { border: 0; color: var(--app-text); background: transparent; }.clip-reference-prompt :deep(.workbench-mention-menu__options > button.is-active),.clip-reference-prompt :deep(.workbench-mention-menu__options > button:hover) { background: var(--app-surface-hover); }
.clip-reference-prompt :deep(.workbench-mention-menu__options) { max-height: min(240px, 35vh); }.clip-reference-prompt :deep(.workbench-mention-menu__header) { border: 0; }.clip-reference-prompt :deep(.workbench-mention-editor__input:empty::before) { color: var(--app-text-muted); }
.clip-prompt-error { color: var(--creation-danger); font-size: 12px; }button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
@media(max-width:600px) { .clip-reference-prompt :deep(.workbench-mention-editor__input) { min-height: 90px; font-size: 13px; }.clip-reference-remove { width: 26px; height: 26px; } }
</style>
