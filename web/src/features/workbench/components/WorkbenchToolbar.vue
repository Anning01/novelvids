<script setup lang="ts">
import { ClipboardPaste, Copy, LayoutGrid, Palette, Play, Plus, Redo2, ScanFace, StickyNote, Trash2, Undo2, Volume2 } from 'lucide-vue-next'
import { ref } from 'vue'
defineProps<{ running?: boolean; canUndo?: boolean; canRedo?: boolean; hasSelection?: boolean; canCopy?: boolean; canPaste?: boolean; canCreateSection?: boolean }>()
defineEmits<{ addShot: []; addAudio: []; addDigitalHuman: []; addNote: []; createSection: [color: string]; generate: []; deleteSelection: []; copy: []; paste: []; undo: []; redo: []; autoArrange: [] }>()
const sectionColor = ref('#31558f')
</script>
<template>
  <div class="workbench-toolbar" role="toolbar" aria-label="画布工具栏">
    <div class="workbench-toolbar__scroll" role="group" aria-label="节点与编辑工具">
      <AppButton class="workbench-toolbar__button" type="button" @click="$emit('addShot')"><Plus :size="17" /><span>新增镜头</span></AppButton>
      <AppButton class="workbench-toolbar__button" type="button" @click="$emit('addAudio')"><Volume2 :size="17" /><span>参考音频</span></AppButton>
      <AppButton class="workbench-toolbar__button" type="button" @click="$emit('addDigitalHuman')"><ScanFace :size="17" /><span>数字人</span></AppButton>
      <AppButton class="workbench-toolbar__button" type="button" @click="$emit('addNote')"><StickyNote :size="17" /><span>便签</span></AppButton>
      <span class="workbench-toolbar__divider" />
      <label class="workbench-toolbar__section-color" title="分区背景颜色"><span class="sr-only">分区背景颜色</span><input v-model="sectionColor" type="color" aria-label="分区背景颜色" :disabled="running || !canCreateSection"></label>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="为所选节点添加背景分区" title="多选节点后添加背景分区" :disabled="running || !canCreateSection" @click="$emit('createSection', sectionColor)"><Palette :size="16" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="自动整理布局" :disabled="running" @click="$emit('autoArrange')"><LayoutGrid :size="16" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="删除所选" :disabled="!hasSelection" @click="$emit('deleteSelection')"><Trash2 :size="16" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="复制所选" :disabled="!canCopy" @click="$emit('copy')"><Copy :size="16" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="粘贴" :disabled="!canPaste" @click="$emit('paste')"><ClipboardPaste :size="16" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="撤销" :disabled="!canUndo" @click="$emit('undo')"><Undo2 :size="16" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="重做" :disabled="!canRedo" @click="$emit('redo')"><Redo2 :size="16" /></AppButton>
    </div>
    <AppButton class="workbench-toolbar__button workbench-toolbar__button--primary" type="button" :disabled="running" @click="$emit('generate')"><Play :size="16" /><span>{{ running ? '生成中' : '生成分镜' }}</span></AppButton>
  </div>
</template>
