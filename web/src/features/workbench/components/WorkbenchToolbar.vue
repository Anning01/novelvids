<script setup lang="ts">
import { Box, ClipboardPaste, Combine, Copy, Droplet, Image, LayoutGrid, Palette, Play, Plus, Redo2, ScanFace, StickyNote, Trash2, Undo2, Upload, Video, Volume2, X } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { WorkbenchRunState } from '../execution/workbenchCapabilities'

defineProps<{ running?: boolean; canUndo?: boolean; canRedo?: boolean; hasSelection?: boolean; canCopy?: boolean; canPaste?: boolean; canCreateSection?: boolean; runState: WorkbenchRunState }>()
defineEmits<{ addAsset: []; addShot: []; addNote: []; addWatermark: []; addComposer: []; uploadImage: []; uploadVideo: []; uploadAudio: []; addAudioReference: []; addDigitalHuman: []; createSection: []; runSelected: []; deleteSelection: []; copy: []; paste: []; undo: []; redo: []; autoArrange: [] }>()
const addMenuRoot = ref<HTMLElement | null>(null)
const addMenuTrigger = ref<HTMLButtonElement | null>(null)
const addMenuOpen = ref(false)

function closeAddMenu({ restoreFocus = false } = {}) {
  addMenuOpen.value = false
  if (restoreFocus) void nextTick(() => addMenuTrigger.value?.focus())
}
function toggleAddMenu() {
  addMenuOpen.value = !addMenuOpen.value
  if (addMenuOpen.value) void nextTick(() => addMenuRoot.value?.querySelector<HTMLElement>('[role="menuitem"]')?.focus())
}
function handleDocumentPointerDown(event: PointerEvent) {
  if (addMenuOpen.value && !addMenuRoot.value?.contains(event.target as Node)) closeAddMenu()
}
function handleDocumentKeydown(event: KeyboardEvent) {
  if (addMenuOpen.value && event.key === 'Escape') { event.preventDefault(); closeAddMenu({ restoreFocus: true }) }
}
onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeydown)
})
</script>
<template>
  <div class="workbench-toolbar nodrag nowheel" role="toolbar" aria-label="画布工具栏" @pointerdown.stop @click.stop @wheel.stop>
    <div ref="addMenuRoot" class="workbench-toolbar__add">
      <button ref="addMenuTrigger" class="workbench-toolbar__add-trigger" :class="{ 'is-open': addMenuOpen }" type="button" aria-haspopup="menu" :aria-expanded="addMenuOpen" aria-controls="workbench-add-node-menu" :aria-label="addMenuOpen ? '关闭添加节点菜单' : '添加节点'" :title="addMenuOpen ? '关闭添加节点菜单' : '添加节点'" @click="toggleAddMenu">
        <X v-if="addMenuOpen" :size="20" aria-hidden="true" />
        <Plus v-else :size="21" aria-hidden="true" />
      </button>
      <Transition name="workbench-add-menu">
        <div v-if="addMenuOpen" id="workbench-add-node-menu" class="workbench-add-menu" role="menu" aria-label="添加节点菜单">
          <p class="workbench-add-menu__heading">添加节点</p>
          <button type="button" role="menuitem" aria-label="新增空资产" @click="closeAddMenu(); $emit('addAsset')"><Box :size="18" aria-hidden="true" /><span>空资产</span></button>
          <button type="button" role="menuitem" aria-label="新增镜头" @click="closeAddMenu(); $emit('addShot')"><Plus :size="18" aria-hidden="true" /><span>镜头</span></button>
          <button type="button" role="menuitem" aria-label="新增便签" @click="closeAddMenu(); $emit('addNote')"><StickyNote :size="18" aria-hidden="true" /><span>便签</span></button>
          <button type="button" role="menuitem" aria-label="新增水印" @click="closeAddMenu(); $emit('addWatermark')"><Droplet :size="18" aria-hidden="true" /><span>水印</span></button>
          <button type="button" role="menuitem" aria-label="新增视频合成" @click="closeAddMenu(); $emit('addComposer')"><Combine :size="18" aria-hidden="true" /><span>视频合成</span></button>
          <p class="workbench-add-menu__heading workbench-add-menu__heading--resources">添加资源</p>
          <button type="button" role="menuitem" aria-label="上传图片" @click="closeAddMenu(); $emit('uploadImage')"><Image :size="18" aria-hidden="true" /><span>上传图片</span></button>
          <button type="button" role="menuitem" aria-label="上传视频" @click="closeAddMenu(); $emit('uploadVideo')"><Video :size="18" aria-hidden="true" /><span>上传视频</span></button>
          <button type="button" role="menuitem" aria-label="上传音频" @click="closeAddMenu(); $emit('uploadAudio')"><Upload :size="18" aria-hidden="true" /><span>上传音频</span></button>
          <button type="button" role="menuitem" aria-label="添加参考音频" @click="closeAddMenu(); $emit('addAudioReference')"><Volume2 :size="18" aria-hidden="true" /><span>参考音频</span></button>
          <button type="button" role="menuitem" aria-label="添加数字人" @click="closeAddMenu(); $emit('addDigitalHuman')"><ScanFace :size="18" aria-hidden="true" /><span>数字人</span></button>
        </div>
      </Transition>
    </div>
    <div class="workbench-toolbar__scroll" tabindex="0" role="group" aria-label="画布编辑工具，可横向滚动">
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="为所选节点添加背景分区" :title="canCreateSection ? '为所选节点添加背景分区' : '依次点击至少两个节点即可创建背景分区'" :disabled="running || !canCreateSection" @click="$emit('createSection')"><Palette :size="18" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="自动整理布局" title="自动整理布局" :disabled="running" @click="$emit('autoArrange')"><LayoutGrid :size="18" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="删除所选" :title="hasSelection ? '删除所选 · Delete / Backspace' : '请先选择一个节点 · Delete / Backspace'" :disabled="!hasSelection" @click="$emit('deleteSelection')"><Trash2 :size="18" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="复制所选" :title="canCopy ? '复制所选 · ⌘C' : '请选择一个可复制的节点 · ⌘C'" :disabled="!canCopy" @click="$emit('copy')"><Copy :size="18" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="粘贴" :title="canPaste ? '粘贴 · ⌘V' : '剪贴板中还没有节点 · ⌘V'" :disabled="!canPaste" @click="$emit('paste')"><ClipboardPaste :size="18" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="撤销" :title="canUndo ? '撤销 · ⌘Z' : '暂无可撤销操作 · ⌘Z'" :disabled="!canUndo" @click="$emit('undo')"><Undo2 :size="18" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" size="sm" icon-only aria-label="重做" :title="canRedo ? '重做 · ⇧⌘Z' : '暂无可重做操作 · ⇧⌘Z'" :disabled="!canRedo" @click="$emit('redo')"><Redo2 :size="18" aria-hidden="true" /></AppButton>
    </div>
    <AppButton class="workbench-toolbar__button workbench-toolbar__button--primary" type="button" :disabled="!runState.enabled || running" :title="runState.enabled ? '运行所选配置' : runState.reason" @click="$emit('runSelected')"><Play :size="16" aria-hidden="true" /><span>{{ running ? '运行中' : runState.label }}</span></AppButton>
  </div>
</template>
