<script setup lang="ts">
import { ClipboardPaste, Copy, LayoutGrid, Palette, Play, Plus, Redo2, ScanFace, StickyNote, Trash2, Undo2, Volume2, X } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
defineProps<{ running?: boolean; canUndo?: boolean; canRedo?: boolean; hasSelection?: boolean; canCopy?: boolean; canPaste?: boolean; canCreateSection?: boolean }>()
const emit = defineEmits<{ addShot: []; addAudio: []; addDigitalHuman: []; addNote: []; createSection: []; generate: []; deleteSelection: []; copy: []; paste: []; undo: []; redo: []; autoArrange: [] }>()
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
function addNode(kind: 'shot' | 'audio' | 'digitalHuman' | 'note') {
  closeAddMenu()
  if (kind === 'shot') emit('addShot')
  else if (kind === 'audio') emit('addAudio')
  else if (kind === 'digitalHuman') emit('addDigitalHuman')
  else emit('addNote')
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
          <button type="button" role="menuitem" aria-label="新增镜头" @click="addNode('shot')"><Plus :size="18" aria-hidden="true" /><span>镜头</span></button>
          <button type="button" role="menuitem" aria-label="新增便签" @click="addNode('note')"><StickyNote :size="18" aria-hidden="true" /><span>便签</span></button>
          <p class="workbench-add-menu__heading workbench-add-menu__heading--resources">添加资源</p>
          <button type="button" role="menuitem" aria-label="添加参考音频" @click="addNode('audio')"><Volume2 :size="18" aria-hidden="true" /><span>参考音频</span></button>
          <button type="button" role="menuitem" aria-label="添加数字人" @click="addNode('digitalHuman')"><ScanFace :size="18" aria-hidden="true" /><span>数字人</span></button>
        </div>
      </Transition>
    </div>
    <div class="workbench-toolbar__scroll" tabindex="0" role="group" aria-label="画布编辑工具，可横向滚动">
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="为所选节点添加背景分区" title="多选节点后添加背景分区" :disabled="running || !canCreateSection" @click="$emit('createSection')"><Palette :size="16" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="自动整理布局" :disabled="running" @click="$emit('autoArrange')"><LayoutGrid :size="16" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="删除所选" :disabled="!hasSelection" @click="$emit('deleteSelection')"><Trash2 :size="16" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="复制所选" :disabled="!canCopy" @click="$emit('copy')"><Copy :size="16" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="粘贴" :disabled="!canPaste" @click="$emit('paste')"><ClipboardPaste :size="16" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="撤销" :disabled="!canUndo" @click="$emit('undo')"><Undo2 :size="16" aria-hidden="true" /></AppButton>
      <AppButton class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="重做" :disabled="!canRedo" @click="$emit('redo')"><Redo2 :size="16" aria-hidden="true" /></AppButton>
    </div>
    <AppButton class="workbench-toolbar__button workbench-toolbar__button--primary" type="button" :disabled="running" @click="$emit('generate')"><Play :size="16" aria-hidden="true" /><span>{{ running ? '生成中' : '生成分镜' }}</span></AppButton>
  </div>
</template>
