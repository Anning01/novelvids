<script setup lang="ts">
import {
  AudioLines,
  Box,
  Clapperboard,
  ClipboardPaste,
  Copy,
  Film,
  Image,
  ImageUp,
  LayoutGrid,
  Library,
  Palette,
  Play,
  Plus,
  Redo2,
  StickyNote,
  Trash2,
  Undo2,
  Video,
  X,
} from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { WorkbenchRunState } from '../execution/workbenchCapabilities'

const props = defineProps<{
  running?: boolean
  canUndo?: boolean
  canRedo?: boolean
  hasSelection?: boolean
  canCopy?: boolean
  canPaste?: boolean
  canCreateSection?: boolean
  runState: WorkbenchRunState
  watermarkEnabled?: boolean
  composerEnabled?: boolean
}>()

const emit = defineEmits<{
  addAsset: []
  reuseAsset: []
  addShot: []
  addNote: []
  addWatermark: []
  addComposer: []
  uploadImage: [file: File]
  uploadVideo: [file: File]
  uploadAudio: [file: File]
  createSection: []
  runSelected: []
  deleteSelection: []
  copy: []
  paste: []
  undo: []
  redo: []
  autoArrange: []
}>()

const imageInput = ref<HTMLInputElement | null>(null)
const videoInput = ref<HTMLInputElement | null>(null)
const audioInput = ref<HTMLInputElement | null>(null)
const addMenuRoot = ref<HTMLElement | null>(null)
const addMenuTrigger = ref<HTMLButtonElement | null>(null)
const addMenuOpen = ref(false)

function closeAddMenu({ restoreFocus = false } = {}) {
  addMenuOpen.value = false
  if (restoreFocus) void nextTick(() => addMenuTrigger.value?.focus())
}

function toggleAddMenu() {
  addMenuOpen.value = !addMenuOpen.value
  if (addMenuOpen.value) {
    void nextTick(() => addMenuRoot.value?.querySelector<HTMLElement>('[role="menuitem"]')?.focus())
  }
}

function handleDocumentPointerDown(event: PointerEvent) {
  if (addMenuOpen.value && !addMenuRoot.value?.contains(event.target as Node)) closeAddMenu()
}

function handleDocumentKeydown(event: KeyboardEvent) {
  if (addMenuOpen.value && event.key === 'Escape') {
    event.preventDefault()
    closeAddMenu({ restoreFocus: true })
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeydown)
})

function addNode(event: 'addAsset' | 'reuseAsset' | 'addShot' | 'addNote' | 'addWatermark' | 'addComposer') {
  closeAddMenu()
  if (event === 'addAsset') emit('addAsset')
  if (event === 'reuseAsset') emit('reuseAsset')
  if (event === 'addShot') emit('addShot')
  if (event === 'addNote') emit('addNote')
  if (event === 'addWatermark') emit('addWatermark')
  if (event === 'addComposer') emit('addComposer')
}

function chooseFiles(input: HTMLInputElement | null) {
  closeAddMenu()
  input?.click()
}

function emitFiles(kind: 'image' | 'video' | 'audio', event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  for (const file of files) {
    if (kind === 'image') emit('uploadImage', file)
    if (kind === 'video') emit('uploadVideo', file)
    if (kind === 'audio') emit('uploadAudio', file)
  }
}
</script>

<template>
  <div class="workbench-toolbar nodrag nowheel" role="toolbar" aria-label="画布工具栏" @pointerdown.stop @click.stop @wheel.stop>
    <div ref="addMenuRoot" class="workbench-toolbar__add">
      <button
        ref="addMenuTrigger"
        class="workbench-toolbar__add-trigger"
        :class="{ 'is-open': addMenuOpen }"
        type="button"
        aria-haspopup="menu"
        :aria-expanded="addMenuOpen"
        aria-controls="workbench-add-node-menu"
        :aria-label="addMenuOpen ? '关闭添加节点菜单' : '添加节点'"
        :title="addMenuOpen ? '关闭添加节点菜单' : '添加节点'"
        @click="toggleAddMenu"
      >
        <X v-if="addMenuOpen" :size="20" aria-hidden="true" />
        <Plus v-else :size="21" aria-hidden="true" />
      </button>

      <Transition name="workbench-add-menu">
        <div v-if="addMenuOpen" id="workbench-add-node-menu" class="workbench-add-menu" role="menu" aria-label="添加节点菜单">
          <p class="workbench-add-menu__heading">添加节点</p>
          <button type="button" role="menuitem" aria-label="新增资产" @click="addNode('addAsset')">
            <Box :size="18" aria-hidden="true" />
            <span>空白资产</span>
          </button>
          <button type="button" role="menuitem" aria-label="复用项目资产" @click="addNode('reuseAsset')">
            <Library :size="18" aria-hidden="true" />
            <span>复用项目资产</span>
          </button>
          <button type="button" role="menuitem" aria-label="新增镜头" @click="addNode('addShot')">
            <Clapperboard :size="18" aria-hidden="true" />
            <span>镜头</span>
          </button>
          <button type="button" role="menuitem" aria-label="新增便签" @click="addNode('addNote')">
            <StickyNote :size="18" aria-hidden="true" />
            <span>便签</span>
          </button>
          <button v-if="watermarkEnabled" type="button" role="menuitem" aria-label="新增水印" @click="addNode('addWatermark')">
            <Image :size="18" aria-hidden="true" />
            <span>水印</span>
          </button>
          <button v-if="composerEnabled" type="button" role="menuitem" aria-label="新增视频合成器" @click="addNode('addComposer')">
            <Film :size="18" aria-hidden="true" />
            <span>视频合成器</span>
          </button>

          <p class="workbench-add-menu__heading workbench-add-menu__heading--resources">添加资源</p>
          <button type="button" role="menuitem" @click="chooseFiles(imageInput)">
            <ImageUp :size="18" aria-hidden="true" />
            <span>上传图片</span>
          </button>
          <button type="button" role="menuitem" @click="chooseFiles(videoInput)">
            <Video :size="18" aria-hidden="true" />
            <span>上传视频</span>
          </button>
          <button type="button" role="menuitem" @click="chooseFiles(audioInput)">
            <AudioLines :size="18" aria-hidden="true" />
            <span>上传音频</span>
          </button>
        </div>
      </Transition>
    </div>

    <input ref="imageInput" class="workbench-toolbar__file-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple aria-label="选择上传图片文件" @change="emitFiles('image', $event)">
    <input ref="videoInput" class="workbench-toolbar__file-input" type="file" accept="video/mp4,video/quicktime,.mp4,.mov" multiple aria-label="选择上传视频文件" @change="emitFiles('video', $event)">
    <input ref="audioInput" class="workbench-toolbar__file-input" type="file" accept="audio/wav,audio/x-wav,audio/mpeg,.wav,.mp3" multiple aria-label="选择上传音频文件" @change="emitFiles('audio', $event)">

    <div class="workbench-toolbar__scroll" tabindex="0" role="group" aria-label="画布节点与编辑工具，可横向滚动">
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="为所选节点添加背景分区" title="多选节点后添加背景分区" :disabled="running || !canCreateSection" @click="$emit('createSection')">
        <Palette :size="16" aria-hidden="true" />
      </button>
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="自动整理布局" title="按连接关系分列并自动避让" :disabled="running" @click="$emit('autoArrange')">
        <LayoutGrid :size="16" aria-hidden="true" />
      </button>
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="删除所选" title="删除所选（Delete）" :disabled="running || !hasSelection" @click="$emit('deleteSelection')">
        <Trash2 :size="16" aria-hidden="true" />
      </button>
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="复制所选" title="复制所选（Ctrl/Cmd+C）" :disabled="running || !canCopy" @click="$emit('copy')">
        <Copy :size="16" aria-hidden="true" />
      </button>
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="粘贴" title="粘贴（Ctrl/Cmd+V）" :disabled="running || !canPaste" @click="$emit('paste')">
        <ClipboardPaste :size="16" aria-hidden="true" />
      </button>
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="撤销" title="撤销（Ctrl/Cmd+Z）" :disabled="running || !canUndo" @click="$emit('undo')">
        <Undo2 :size="16" aria-hidden="true" />
      </button>
      <button class="workbench-toolbar__button workbench-toolbar__button--icon" type="button" aria-label="重做" title="重做（Ctrl/Cmd+Shift+Z）" :disabled="running || !canRedo" @click="$emit('redo')">
        <Redo2 :size="16" aria-hidden="true" />
      </button>
    </div>

    <button
      class="workbench-toolbar__button workbench-toolbar__button--primary"
      type="button"
      :disabled="running || !runState.enabled"
      :aria-label="!runState.enabled ? '请先选择可执行节点' : running ? '正在批量执行' : '运行所选配置'"
      :title="runState.enabled ? undefined : runState.reason"
      @click="$emit('runSelected')"
    >
      <Play :size="16" aria-hidden="true" />
      <span>{{ running ? '执行中' : '运行此配置' }}</span>
    </button>
  </div>
</template>
