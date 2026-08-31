<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, render, watch } from 'vue'
import { AtSign, Boxes, Clock3, Film, Image as ImageIcon, Map as MapIcon, Pause, UserRound, Volume2, X } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import ImageLightbox from './ImageLightbox.vue'

export type ScenePromptMentionKind = 'person' | 'scene' | 'item' | 'image' | 'video' | 'audio' | 'duration'

export interface ScenePromptMentionOption {
  id: string
  kind: ScenePromptMentionKind
  label: string
  syntax: string
  group: string
  previewUrl?: string
  audioUrl?: string
  thumbnailUrl?: string
  description?: string
  aliases?: string[]
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: ScenePromptMentionOption[]
  placeholder?: string
  embedded?: boolean
  focusMode?: boolean
}>(), {
  placeholder: '请输入分镜视频提示词。描述镜头、主体动作、运镜、光线、画面风格和声音。',
  embedded: false,
  focusMode: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const editor = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const query = ref('')
const activeIndex = ref(0)
const menuPosition = ref({ left: 0, top: 0 })
const triggerTextNode = ref<Text | null>(null)
const triggerStartOffset = ref(0)
const previewOption = ref<ScenePromptMentionOption | null>(null)
const hoverPreviewOption = ref<ScenePromptMentionOption | null>(null)
const hoverPreviewPosition = ref({ left: 0, top: 0 })
const durationAnchor = ref<HTMLElement | null>(null)
const durationInput = ref<HTMLInputElement | null>(null)
const durationEditorOpen = ref(false)
const durationValue = ref<string | number>('')
const durationPosition = ref({ left: 0, top: 0 })
const playingAudioMentionId = ref('')
let playingAudio: HTMLAudioElement | null = null

const DURATION_MENTION_PATTERN = /@\{(?:镜头|视频)时长(?::(\d+(?:\.\d+)?)s?)?\}/g

const filteredOptions = computed(() => {
  const normalized = query.value.trim().toLocaleLowerCase()
  return props.options.filter(option => !normalized
    || option.label.toLocaleLowerCase().includes(normalized)
    || option.group.toLocaleLowerCase().includes(normalized))
})

const groupedOptions = computed(() => {
  const groups = new Map<string, ScenePromptMentionOption[]>()
  for (const option of filteredOptions.value.filter(item => item.kind !== 'duration')) {
    const items = groups.get(option.group) || []
    items.push(option)
    groups.set(option.group, items)
  }
  return [...groups.entries()].map(([label, items]) => ({ label, items }))
})

const activeOption = computed(() => filteredOptions.value[activeIndex.value] || null)
const durationMentionOption = computed(() => filteredOptions.value.find(item => item.kind === 'duration') || null)
const imagePreview = computed(() => previewOption.value?.kind !== 'video' ? previewOption.value : null)
const hoverPreviewSource = computed(() => hoverPreviewOption.value?.previewUrl || hoverPreviewOption.value?.thumbnailUrl || '')
const hoverPreviewStyle = computed(() => ({ left: `${hoverPreviewPosition.value.left}px`, top: `${hoverPreviewPosition.value.top}px` }))
const menuStyle = computed(() => ({ left: `${menuPosition.value.left}px`, top: `${menuPosition.value.top}px` }))
const durationStyle = computed(() => ({ left: `${durationPosition.value.left}px`, top: `${durationPosition.value.top}px` }))
const durationNumber = computed(() => Number(durationValue.value))
const durationIsValid = computed(() => String(durationValue.value).trim() !== '' && Number.isFinite(durationNumber.value) && durationNumber.value >= 1 && durationNumber.value <= 30)

function iconFor(kind: ScenePromptMentionKind) {
  if (kind === 'person') return UserRound
  if (kind === 'scene') return MapIcon
  if (kind === 'item') return Boxes
  if (kind === 'video') return Film
  if (kind === 'audio') return Volume2
  if (kind === 'duration') return Clock3
  return ImageIcon
}

function appendTextWithBreaks(fragment: DocumentFragment, value: string) {
  const lines = value.split('\n')
  lines.forEach((line, index) => {
    if (line) fragment.append(document.createTextNode(line))
    if (index < lines.length - 1) fragment.append(document.createElement('br'))
  })
}

function createMentionNode(option: ScenePromptMentionOption) {
  const mention = document.createElement('span')
  mention.className = `scene-prompt-editor__mention is-${option.kind}`
  mention.contentEditable = 'false'
  mention.dataset.mentionId = option.id
  mention.dataset.mentionKind = option.kind
  mention.dataset.syntax = option.syntax
  const interactive = Boolean(option.previewUrl || option.audioUrl) || option.kind === 'duration'
  mention.setAttribute('role', interactive ? 'button' : 'note')
  mention.setAttribute('aria-label', option.kind === 'duration'
    ? `${option.label}，点击更改时间`
    : option.kind === 'audio' && option.audioUrl
      ? `${option.label}，点击播放音色参考`
      : option.previewUrl ? `${option.label}，点击预览` : option.label)
  if (interactive) mention.tabIndex = 0

  const thumbnail = option.thumbnailUrl || option.previewUrl
  if (option.kind === 'duration') {
    const icon = document.createElement('span')
    icon.className = 'scene-prompt-editor__duration-icon'
    icon.setAttribute('aria-hidden', 'true')
    render(h(Clock3, { size: 13, strokeWidth: 2.2 }), icon)
    mention.append(icon)
  }
  if (option.kind === 'audio') {
    const icon = document.createElement('span')
    icon.className = 'scene-prompt-editor__audio-icon'
    icon.setAttribute('aria-hidden', 'true')
    render(h(playingAudioMentionId.value === option.id ? Pause : Volume2, { size: 13, strokeWidth: 2.2 }), icon)
    mention.classList.toggle('is-playing', playingAudioMentionId.value === option.id)
    mention.append(icon)
  }
  if (thumbnail && option.kind !== 'duration') {
    if (option.kind === 'video') {
      const video = document.createElement('video')
      video.src = thumbnail
      video.muted = true
      video.preload = 'metadata'
      video.playsInline = true
      video.tabIndex = -1
      mention.append(video)
    } else {
      const image = document.createElement('img')
      image.src = thumbnail
      image.alt = ''
      image.draggable = false
      mention.append(image)
    }
  }

  const label = document.createElement('span')
  label.textContent = option.label
  mention.append(label)
  return mention
}

function findNextMention(value: string, start: number) {
  let match: { option: ScenePromptMentionOption; index: number; length: number } | null = null
  for (const option of props.options.filter(item => item.kind !== 'duration')) {
    const canonicalName = option.syntax.match(/^@\{([^{}:#]+)(?:#[^{}]+)?\}$/)?.[1]
    const legacyNames = canonicalName ? [canonicalName, ...(option.aliases || [])] : []
    const syntaxes = [option.syntax, ...legacyNames.map(name => `@${name}`)]
    for (const syntax of syntaxes) {
      const index = value.indexOf(syntax, start)
      if (index < 0 || (match && (index > match.index || (index === match.index && syntax.length <= match.length)))) continue
      match = { option, index, length: syntax.length }
    }
  }
  DURATION_MENTION_PATTERN.lastIndex = start
  const durationMatch = DURATION_MENTION_PATTERN.exec(value)
  if (durationMatch && (!match || durationMatch.index < match.index)) {
    const configured = props.options.find(item => item.kind === 'duration')
    const seconds = durationMatch[1]
    match = {
      index: durationMatch.index,
      length: durationMatch[0].length,
      option: {
        id: `duration-${durationMatch.index}-${durationMatch[0]}`,
        kind: 'duration',
        label: seconds ? `${Number(seconds)}s` : '请设置时长',
        syntax: durationMatch[0],
        group: configured?.group || '镜头参数',
        description: configured?.description || '设置 1–30 秒',
      },
    }
  }
  return match
}

function renderValue(value = props.modelValue) {
  if (!editor.value) return
  closeHoverPreview()
  editor.value.querySelectorAll<HTMLElement>('.scene-prompt-editor__duration-icon, .scene-prompt-editor__audio-icon').forEach(host => render(null, host))
  const fragment = document.createDocumentFragment()
  let offset = 0
  while (offset < value.length) {
    const match = findNextMention(value, offset)
    if (!match) {
      appendTextWithBreaks(fragment, value.slice(offset))
      break
    }
    appendTextWithBreaks(fragment, value.slice(offset, match.index))
    fragment.append(createMentionNode(match.option))
    offset = match.index + match.length
  }
  if (!value) fragment.append(document.createElement('br'))
  editor.value.replaceChildren(fragment)
  editor.value.dataset.empty = value ? 'false' : 'true'
}

function serializeNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || ''
  if (!(node instanceof HTMLElement)) return ''
  if (node.dataset.syntax) return node.dataset.syntax
  if (node.tagName === 'BR') return '\n'
  const content = [...node.childNodes].map(serializeNode).join('')
  return node.tagName === 'DIV' || node.tagName === 'P' ? `${content}\n` : content
}

function editorValue() {
  if (!editor.value) return ''
  return [...editor.value.childNodes]
    .map(serializeNode)
    .join('')
    .replace(/\u00a0/g, ' ')
    .replace(/\n$/, '')
}

function emitEditorValue() {
  const value = editorValue()
  if (value !== props.modelValue) emit('update:modelValue', value)
}

function selectionInsideEditor() {
  const selection = window.getSelection()
  const node = selection?.anchorNode
  return Boolean(selection && node && editor.value?.contains(node))
}

function placeMenu(rect?: DOMRect) {
  const anchor = rect || editor.value?.getBoundingClientRect()
  if (!anchor) return
  const width = Math.min(340, window.innerWidth - 24)
  const preferredLeft = rect ? rect.left : anchor.left + 14
  const left = Math.max(12, Math.min(preferredLeft, window.innerWidth - width - 12))
  const desiredTop = rect ? rect.bottom + 8 : anchor.top + 42
  const top = desiredTop + 340 > window.innerHeight
    ? Math.max(12, (rect?.top || anchor.top) - 348)
    : desiredTop
  menuPosition.value = { left, top }
}

function refreshMentionTrigger() {
  const selection = window.getSelection()
  if (!selection?.rangeCount || !selectionInsideEditor()) {
    menuOpen.value = false
    return
  }
  const node = selection.anchorNode
  if (!(node instanceof Text)) {
    menuOpen.value = false
    return
  }
  const textBeforeCaret = node.data.slice(0, selection.anchorOffset)
  const match = textBeforeCaret.match(/@([^@\s{}]*)$/)
  if (!match) {
    menuOpen.value = false
    return
  }
  triggerTextNode.value = node
  triggerStartOffset.value = selection.anchorOffset - match[0].length
  query.value = match[1] || ''
  activeIndex.value = 0
  const range = selection.getRangeAt(0)
  placeMenu(typeof range.getBoundingClientRect === 'function' ? range.getBoundingClientRect() : undefined)
  menuOpen.value = true
}

function handleInput() {
  if (editor.value) editor.value.dataset.empty = editorValue() ? 'false' : 'true'
  emitEditorValue()
  refreshMentionTrigger()
}

function setCaretAfter(node: Node) {
  const range = document.createRange()
  range.setStartAfter(node)
  range.collapse(true)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
}

function selectMention(option: ScenePromptMentionOption) {
  const selection = window.getSelection()
  const textNode = triggerTextNode.value
  if (!selection?.rangeCount || !textNode || !editor.value?.contains(textNode)) return
  const range = document.createRange()
  range.setStart(textNode, Math.min(triggerStartOffset.value, textNode.length))
  range.setEnd(selection.anchorNode || textNode, selection.anchorOffset)
  range.deleteContents()
  const mention = createMentionNode(option)
  const spacer = document.createTextNode(' ')
  range.insertNode(spacer)
  range.insertNode(mention)
  setCaretAfter(spacer)
  menuOpen.value = false
  query.value = ''
  emitEditorValue()
  if (option.kind === 'duration') openDurationEditor(mention)
  else editor.value.focus()
}

function openPreview(option: ScenePromptMentionOption) {
  closeHoverPreview()
  if (option.previewUrl) previewOption.value = option
}

function closeHoverPreview() {
  hoverPreviewOption.value = null
}

function placeHoverPreview(anchor: HTMLElement) {
  const rect = anchor.getBoundingClientRect()
  const width = Math.min(420, window.innerWidth - 24)
  const height = Math.min(324, window.innerHeight - 24)
  const gap = 12
  const preferredLeft = rect.right + gap
  const left = preferredLeft + width <= window.innerWidth - 12
    ? preferredLeft
    : rect.left - width - gap >= 12
      ? rect.left - width - gap
      : Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))
  const preferredTop = rect.top + rect.height / 2 - height / 2
  const top = Math.max(12, Math.min(preferredTop, window.innerHeight - height - 12))
  hoverPreviewPosition.value = { left, top }
}

function showHoverPreview(mention: HTMLElement) {
  if (!props.focusMode) return
  const option = props.options.find(item => item.id === mention.dataset.mentionId)
  if (!option || option.kind === 'audio' || option.kind === 'duration' || !(option.previewUrl || option.thumbnailUrl)) return
  placeHoverPreview(mention)
  hoverPreviewOption.value = option
}

function mentionFromEvent(event: Event) {
  const target = event.target
  return target instanceof Element ? target.closest<HTMLElement>('[data-mention-id]') : null
}

function handleEditorPointerover(event: PointerEvent) {
  const mention = mentionFromEvent(event)
  if (!mention || (event.relatedTarget instanceof Node && mention.contains(event.relatedTarget))) return
  showHoverPreview(mention)
}

function handleEditorPointerout(event: PointerEvent) {
  const mention = mentionFromEvent(event)
  if (!mention || (event.relatedTarget instanceof Node && mention.contains(event.relatedTarget))) return
  if (hoverPreviewOption.value?.id === mention.dataset.mentionId) closeHoverPreview()
}

function handleEditorFocusin(event: FocusEvent) {
  const mention = mentionFromEvent(event)
  if (mention) showHoverPreview(mention)
}

function handleEditorFocusout(event: FocusEvent) {
  const mention = mentionFromEvent(event)
  if (!mention || (event.relatedTarget instanceof Node && mention.contains(event.relatedTarget))) return
  if (hoverPreviewOption.value?.id === mention.dataset.mentionId) closeHoverPreview()
}

function syncAudioMentionState() {
  editor.value?.querySelectorAll<HTMLElement>('[data-mention-kind="audio"]').forEach(mention => {
    const isPlaying = mention.dataset.mentionId === playingAudioMentionId.value
    mention.classList.toggle('is-playing', isPlaying)
    mention.setAttribute('aria-pressed', String(isPlaying))
    const icon = mention.querySelector<HTMLElement>('.scene-prompt-editor__audio-icon')
    if (icon) render(h(isPlaying ? Pause : Volume2, { size: 13, strokeWidth: 2.2 }), icon)
  })
}

function stopAudioReference() {
  const audio = playingAudio
  playingAudio = null
  if (audio) {
    audio.onended = null
    audio.onerror = null
    audio.pause()
  }
  playingAudioMentionId.value = ''
  syncAudioMentionState()
}

function toggleAudioReference(option: ScenePromptMentionOption) {
  if (!option.audioUrl) return
  if (playingAudioMentionId.value === option.id && playingAudio) {
    stopAudioReference()
    return
  }
  stopAudioReference()
  const audio = new Audio(option.audioUrl)
  playingAudio = audio
  playingAudioMentionId.value = option.id
  const finish = () => {
    if (playingAudio === audio) stopAudioReference()
  }
  audio.onended = finish
  audio.onerror = finish
  syncAudioMentionState()
  void audio.play().catch(finish)
}

function activateMention(option: ScenePromptMentionOption) {
  if (option.kind === 'audio') toggleAudioReference(option)
  else openPreview(option)
}

function parseDurationSyntax(value = '') {
  return value.match(/^@\{(?:镜头|视频)时长(?::(\d+(?:\.\d+)?)s?)?\}$/)?.[1] || ''
}

function placeDurationEditor(anchor: HTMLElement) {
  const rect = anchor.getBoundingClientRect()
  const width = Math.min(248, window.innerWidth - 24)
  const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))
  const desiredTop = rect.bottom + 8
  durationPosition.value = {
    left,
    top: desiredTop + 174 > window.innerHeight ? Math.max(12, rect.top - 182) : desiredTop,
  }
}

function openDurationEditor(anchor: HTMLElement) {
  durationAnchor.value = anchor
  durationValue.value = parseDurationSyntax(anchor.dataset.syntax)
  placeDurationEditor(anchor)
  durationEditorOpen.value = true
  menuOpen.value = false
  void nextTick(() => durationInput.value?.focus())
}

function closeDurationEditor() {
  durationEditorOpen.value = false
  durationAnchor.value = null
}

function confirmDuration() {
  if (!durationIsValid.value || !durationAnchor.value) return
  const anchor = durationAnchor.value
  const normalized = Number(durationNumber.value.toFixed(1))
  anchor.dataset.syntax = `@{镜头时长:${normalized}s}`
  anchor.dataset.mentionId = `duration-${normalized}`
  anchor.setAttribute('aria-label', `${normalized}s，点击更改时间`)
  const label = anchor.querySelector(':scope > span:last-child')
  if (label) label.textContent = `${normalized}s`
  emitEditorValue()
  closeDurationEditor()
  void nextTick(() => {
    if (!editor.value?.contains(anchor)) return
    editor.value.focus()
    setCaretAfter(anchor)
  })
}

function handleEditorClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Element)) return
  const mention = target.closest<HTMLElement>('[data-mention-id]')
  if (!mention) return
  if (mention.dataset.mentionKind === 'duration') {
    openDurationEditor(mention)
    return
  }
  const option = props.options.find(item => item.id === mention.dataset.mentionId)
  if (option) activateMention(option)
}

function handleEditorPointerdown(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Element)) return
  const mention = target.closest<HTMLElement>('[data-mention-kind="audio"]')
  if (!mention) return
  // 音色标签是播放控件，不参与富文本选区，避免点击后出现浏览器蓝色选中态。
  event.preventDefault()
}

function handleEditorKeydown(event: KeyboardEvent) {
  const target = event.target
  if (target instanceof Element) {
    const mention = target.closest<HTMLElement>('[data-mention-id]')
    if (mention && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault()
      if (mention.dataset.mentionKind === 'duration') {
        openDurationEditor(mention)
        return
      }
      const option = props.options.find(item => item.id === mention.dataset.mentionId)
      if (option) activateMention(option)
      return
    }
  }
  if (!menuOpen.value) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = filteredOptions.value.length ? (activeIndex.value + 1) % filteredOptions.value.length : 0
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value = filteredOptions.value.length ? (activeIndex.value - 1 + filteredOptions.value.length) % filteredOptions.value.length : 0
  } else if (event.key === 'Enter' && activeOption.value) {
    event.preventDefault()
    selectMention(activeOption.value)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    menuOpen.value = false
  }
}

function closeMenuFromOutside(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Element)) return
  if (!target.closest('.scene-prompt-editor') && !target.closest('.scene-prompt-mentions')) menuOpen.value = false
  if (!target.closest('.scene-duration-editor') && !target.closest('[data-mention-kind="duration"]')) closeDurationEditor()
}

function closePreview() {
  previewOption.value = null
}

function handleWindowKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && durationEditorOpen.value) {
    closeDurationEditor()
    return
  }
  if (event.key === 'Escape' && previewOption.value) closePreview()
}

watch(() => props.modelValue, () => {
  if (editorValue() === props.modelValue) return
  renderValue()
})

watch(() => props.options.map(option => [
  option.id,
  option.kind,
  option.label,
  option.syntax,
  option.previewUrl || '',
  option.audioUrl || '',
  option.thumbnailUrl || '',
  option.description || '',
  (option.aliases || []).join('\u0003'),
].join('\u0001')).join('\u0002'), () => {
  renderValue()
})

watch(filteredOptions, items => {
  if (activeIndex.value >= items.length) activeIndex.value = 0
})

onMounted(() => {
  renderValue()
  document.addEventListener('pointerdown', closeMenuFromOutside)
  window.addEventListener('keydown', handleWindowKeydown)
})

onBeforeUnmount(() => {
  stopAudioReference()
  editor.value?.querySelectorAll<HTMLElement>('.scene-prompt-editor__duration-icon, .scene-prompt-editor__audio-icon').forEach(host => render(null, host))
  document.removeEventListener('pointerdown', closeMenuFromOutside)
  window.removeEventListener('keydown', handleWindowKeydown)
})
</script>

<template>
  <section class="scene-prompt-editor" :class="{ 'is-embedded': embedded, 'is-focus-mode': focusMode }">
    <div
      ref="editor"
      class="scene-prompt-editor__input"
      contenteditable="true"
      role="textbox"
      aria-multiline="true"
      aria-label="分镜视频提示词，输入艾特符号可添加引用"
      :data-placeholder="placeholder"
      spellcheck="true"
      @input="handleInput"
      @scroll.passive="closeHoverPreview"
      @pointerdown="handleEditorPointerdown"
      @pointerover="handleEditorPointerover"
      @pointerout="handleEditorPointerout"
      @click="handleEditorClick"
      @focusin="handleEditorFocusin"
      @focusout="handleEditorFocusout"
      @keydown="handleEditorKeydown"
    />

    <Teleport to="body">
      <Transition name="scene-prompt-hover-preview">
        <aside
          v-if="focusMode && hoverPreviewOption && hoverPreviewSource"
          class="scene-prompt-hover-preview"
          :class="`is-${hoverPreviewOption.kind}`"
          :style="hoverPreviewStyle"
          role="tooltip"
          :aria-label="`${hoverPreviewOption.label}预览`"
        >
          <video v-if="hoverPreviewOption.kind === 'video'" :src="hoverPreviewSource" muted autoplay loop playsinline preload="metadata" />
          <img v-else :src="hoverPreviewSource" :alt="hoverPreviewOption.label" />
          <footer><component :is="hoverPreviewOption.kind === 'video' ? Film : ImageIcon" :size="14" /><strong>{{ hoverPreviewOption.label }}</strong><small>{{ hoverPreviewOption.kind === 'video' ? '视频预览' : '图片预览' }}</small></footer>
        </aside>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="scene-prompt-menu">
        <section v-if="menuOpen" class="scene-prompt-mentions" :style="menuStyle" role="listbox" aria-label="选择提示词引用" @pointerdown.stop>
          <header><AtSign :size="14" /><span>选择引用</span><small>输入名称筛选</small></header>
          <div v-if="filteredOptions.length" class="scene-prompt-mentions__groups">
            <section v-for="group in groupedOptions" :key="group.label">
              <h3>{{ group.label }}</h3>
              <button
                v-for="option in group.items"
                :key="option.id"
                type="button"
                role="option"
                :aria-selected="activeOption?.id === option.id"
                :class="{ 'is-active': activeOption?.id === option.id }"
                @pointerdown.prevent="selectMention(option)"
              >
                <span class="scene-prompt-mentions__thumb">
                  <img v-if="option.thumbnailUrl && option.kind !== 'video'" :src="option.thumbnailUrl" alt="" />
                  <video v-else-if="option.thumbnailUrl && option.kind === 'video'" :src="option.thumbnailUrl" muted playsinline preload="metadata" />
                  <component :is="iconFor(option.kind)" v-else :size="16" />
                </span>
                <span><strong>{{ option.label }}</strong><small>{{ option.description || option.group }}</small></span>
              </button>
            </section>
            <section v-if="durationMentionOption" class="scene-prompt-mentions__actions">
              <button
                type="button"
                role="option"
                :aria-selected="activeOption?.id === durationMentionOption.id"
                :class="{ 'is-active': activeOption?.id === durationMentionOption.id }"
                @pointerdown.prevent="selectMention(durationMentionOption)"
              >
                <span class="scene-prompt-mentions__action-icon"><Clock3 :size="17" /></span>
                <span><strong>添加镜头时长</strong><small>插入后可点击修改 1–30 秒</small></span>
              </button>
            </section>
          </div>
          <p v-else>没有匹配的引用</p>
          <footer><kbd>↑</kbd><kbd>↓</kbd>选择 <kbd>Enter</kbd>插入 <kbd>Esc</kbd>关闭</footer>
        </section>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="scene-prompt-menu">
        <form v-if="durationEditorOpen" class="scene-duration-editor" :style="durationStyle" @submit.prevent="confirmDuration" @pointerdown.stop>
          <strong>更改时间</strong>
          <label>
            <input ref="durationInput" v-model="durationValue" type="number" min="1" max="30" step="0.5" inputmode="decimal" placeholder="请输入时长（1-30）" aria-label="镜头时长，1 到 30 秒" />
            <span>s</span>
          </label>
          <div>
            <AppButton type="button" variant="secondary" size="sm" @click="closeDurationEditor">取消</AppButton>
            <AppButton type="submit" variant="primary" size="sm" :disabled="!durationIsValid">确认</AppButton>
          </div>
        </form>
      </Transition>
    </Teleport>

    <ImageLightbox
      :open="Boolean(imagePreview?.previewUrl)"
      :src="imagePreview?.previewUrl || ''"
      :alt="imagePreview?.label || '引用图片'"
      @close="closePreview"
    />
    <Teleport to="body">
      <Transition name="scene-prompt-preview">
        <div v-if="previewOption?.kind === 'video' && previewOption.previewUrl" class="scene-prompt-video-preview" role="dialog" aria-modal="true" :aria-label="`${previewOption.label}视频预览`" @click.self="closePreview">
          <section>
            <header><div><Film :size="17" /><strong>{{ previewOption.label }}</strong></div><AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭视频预览" @click="closePreview"><X :size="18" /></AppButton></header>
            <video :src="previewOption.previewUrl" controls autoplay playsinline />
          </section>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<style scoped>
.scene-prompt-editor { display: grid; min-width: 0; min-height: 420px; grid-template-rows: minmax(0,1fr); overflow: hidden; border: 1px solid color-mix(in srgb,var(--app-border) 84%,transparent); border-radius: 14px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 1px 2px rgb(17 24 39 / 3%),0 8px 24px rgb(17 24 39 / 2%); transition: border-color .18s ease,box-shadow .18s ease; }
.scene-prompt-editor:focus-within { border-color: color-mix(in srgb,var(--app-accent) 46%,var(--app-border)); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 9%,transparent),0 10px 28px rgb(17 24 39 / 4%); }
.scene-prompt-editor.is-embedded { min-height: 320px; max-height: 600px; align-self: start; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.scene-prompt-editor.is-embedded:focus-within { border-color: transparent; box-shadow: none; }
.scene-prompt-editor.is-focus-mode { width: 100%; height: 100%; min-height: 0; max-height: none; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.scene-prompt-editor.is-focus-mode:focus-within { border-color: transparent; box-shadow: none; }
.scene-prompt-editor__input { min-width: 0; min-height: 420px; overflow: auto; padding: 1px 16px 20px; outline: 0; color: var(--app-text-secondary); background: var(--app-surface); font-size: 11px; line-height: 1.9; white-space: pre-wrap; overflow-wrap: anywhere; caret-color: var(--app-accent); }
.scene-prompt-editor.is-embedded .scene-prompt-editor__input { min-height: 320px; max-height: 600px; overflow-y: auto; background: transparent; scrollbar-width: none; }
.scene-prompt-editor.is-embedded .scene-prompt-editor__input::-webkit-scrollbar { display: none; }
.scene-prompt-editor.is-focus-mode .scene-prompt-editor__input { height: 100%; min-height: 0; max-height: none; padding: 24px 28px 40px; background: transparent; font-size: 14px; line-height: 2; scrollbar-width: thin; scrollbar-color: var(--app-border-strong) transparent; }
.scene-prompt-editor__input:focus { background: color-mix(in srgb,var(--app-surface) 98%,var(--app-accent)); }
.scene-prompt-editor__input[data-empty='true']::before { color: var(--app-text-muted); content: attr(data-placeholder); pointer-events: none; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention) { display: inline-flex; max-width: 220px; min-height: 24px; align-items: center; gap: 5px; margin: 0 2px; padding: 2px 7px 2px 3px; border-radius: 7px; color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); font-size: 10px; font-weight: 650; line-height: 20px; vertical-align: middle; user-select: all; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention[role='button']) { cursor: zoom-in; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-audio[role='button']) { cursor: pointer; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention[role='button']:hover),.scene-prompt-editor__input :deep(.scene-prompt-editor__mention[role='button']:focus-visible) { color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px var(--app-border-strong); }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention img),.scene-prompt-editor__input :deep(.scene-prompt-editor__mention video) { width: 22px; height: 20px; flex: 0 0 22px; border-radius: 5px; object-fit: cover; pointer-events: none; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention > span) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-duration) { padding-left: 7px; color: var(--app-accent); background: var(--app-accent-soft); }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-audio) { min-height: 22px; gap: 4px; padding: 1px 7px 1px 3px; border-radius: 8px; color: var(--app-text-secondary); background: color-mix(in srgb,var(--app-accent) 6%,var(--app-surface)); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 16%,var(--app-border)); user-select: none; -webkit-user-select: none; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-audio:hover),.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-audio:focus-visible) { color: var(--app-accent); background: color-mix(in srgb,var(--app-accent) 9%,var(--app-surface)); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 28%,var(--app-border)); }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-audio.is-playing) { color: var(--app-accent); background: color-mix(in srgb,var(--app-accent) 11%,var(--app-surface)); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--app-accent) 38%,var(--app-border)); }
.scene-prompt-editor__input :deep(.scene-prompt-editor__duration-icon),.scene-prompt-editor__input :deep(.scene-prompt-editor__audio-icon) { display: inline-grid; width: 14px; height: 14px; flex: 0 0 14px; place-items: center; color: currentColor; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__audio-icon) { width: 18px; height: 18px; flex-basis: 18px; border-radius: 6px; color: var(--app-accent); background: color-mix(in srgb,var(--app-accent) 10%,transparent); transition: color .16s ease,background .16s ease,transform .16s ease; }
.scene-prompt-editor__input :deep(.scene-prompt-editor__mention.is-audio.is-playing .scene-prompt-editor__audio-icon) { color: #fff; background: var(--app-accent); transform: scale(.94); }
.scene-prompt-hover-preview { position: fixed; z-index: 178; display: grid; width: min(420px,calc(100vw - 24px)); grid-template-rows: minmax(0,280px) 44px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 16px; color: var(--app-text); background: var(--app-surface-raised); box-shadow: 0 24px 70px rgb(12 16 28 / 28%); pointer-events: none; }
.scene-prompt-hover-preview > img,.scene-prompt-hover-preview > video { display: block; width: 100%; height: 280px; background: #171a21; object-fit: contain; }
.scene-prompt-hover-preview > footer { display: grid; min-width: 0; grid-template-columns: 18px minmax(0,1fr) auto; align-items: center; gap: 7px; padding: 0 12px; border-top: 1px solid var(--app-border); background: var(--app-surface); }
.scene-prompt-hover-preview > footer svg { color: var(--app-accent); }
.scene-prompt-hover-preview > footer strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.scene-prompt-hover-preview > footer small { color: var(--app-text-muted); font-size: 9px; }
.scene-prompt-hover-preview-enter-active,.scene-prompt-hover-preview-leave-active { transition: opacity .14s ease,transform .16s cubic-bezier(.2,.72,.2,1); transform-origin: center; }
.scene-prompt-hover-preview-enter-from,.scene-prompt-hover-preview-leave-to { opacity: 0; transform: translateY(4px) scale(.985); }
.scene-prompt-mentions { position: fixed; z-index: 170; display: grid; width: min(340px,calc(100vw - 24px)); max-height: 340px; grid-template-rows: auto minmax(0,1fr) auto; overflow: hidden; border-radius: 13px; color: var(--app-text-secondary); background: var(--app-surface-raised); box-shadow: var(--app-shadow), inset 0 0 0 1px var(--app-border); backdrop-filter: blur(16px); }
.scene-prompt-mentions > header { display: flex; min-height: 40px; align-items: center; gap: 7px; padding: 0 11px; border-bottom: 1px solid var(--app-border); }
.scene-prompt-mentions > header svg { color: var(--app-accent); }
.scene-prompt-mentions > header span { font-size: 11px; font-weight: 750; }
.scene-prompt-mentions > header small { margin-left: auto; color: var(--app-text-muted); font-size: 8px; }
.scene-prompt-mentions__groups { overflow-y: auto; padding: 5px; scrollbar-width: none; }
.scene-prompt-mentions__groups::-webkit-scrollbar { display: none; }
.scene-prompt-mentions__groups section + section { margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--app-border); }
.scene-prompt-mentions h3 { margin: 0; padding: 5px 7px 3px; color: var(--app-text-muted); font-size: 8px; font-weight: 700; letter-spacing: .08em; }
.scene-prompt-mentions button { display: grid; width: 100%; min-width: 0; grid-template-columns: 34px minmax(0,1fr); align-items: center; gap: 8px; padding: 6px; border: 0; border-radius: 9px; color: var(--app-text-secondary); background: transparent; font: inherit; text-align: left; cursor: pointer; }
.scene-prompt-mentions button:hover,.scene-prompt-mentions button.is-active { color: var(--app-accent); background: var(--app-accent-soft); }
.scene-prompt-mentions__thumb { display: grid; width: 34px; height: 30px; overflow: hidden; place-items: center; border-radius: 7px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.scene-prompt-mentions__thumb img,.scene-prompt-mentions__thumb video { width: 100%; height: 100%; object-fit: cover; }
.scene-prompt-mentions__actions button { grid-template-columns: 34px minmax(0,1fr); }
.scene-prompt-mentions__action-icon { display: grid; width: 34px; height: 30px; place-items: center; border-radius: 7px; color: var(--app-text-secondary); background: var(--app-surface-muted); }
.scene-prompt-mentions button > span:last-child { display: grid; min-width: 0; gap: 2px; }
.scene-prompt-mentions button strong,.scene-prompt-mentions button small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scene-prompt-mentions button strong { font-size: 10px; }
.scene-prompt-mentions button small { color: var(--app-text-muted); font-size: 8px; font-weight: 450; }
.scene-prompt-mentions > p { margin: 0; padding: 28px 12px; color: var(--app-text-muted); font-size: 10px; text-align: center; }
.scene-prompt-mentions > footer { display: flex; min-height: 30px; align-items: center; gap: 4px; padding: 0 10px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); font-size: 8px; }
.scene-prompt-mentions kbd { padding: 2px 4px; border-radius: 4px; color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); font: inherit; }
.scene-prompt-menu-enter-active,.scene-prompt-menu-leave-active { transition: opacity .16s ease,transform .18s cubic-bezier(.2,.72,.2,1); transform-origin: top left; }
.scene-prompt-menu-enter-from,.scene-prompt-menu-leave-to { opacity: 0; transform: translateY(-4px) scale(.98); }
.scene-duration-editor { position: fixed; z-index: 175; display: grid; width: min(248px,calc(100vw - 24px)); gap: 10px; padding: 14px; border-radius: 14px; color: var(--app-text); background: var(--app-surface-raised); box-shadow: var(--app-shadow),inset 0 0 0 1px var(--app-border); }
.scene-duration-editor > strong { font-size: 12px; }
.scene-duration-editor > label { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 8px; }
.scene-duration-editor input { width: 100%; min-width: 0; height: 38px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 9px; outline: 0; color: var(--app-text); background: var(--app-surface); font: inherit; font-size: 11px; }
.scene-duration-editor input:focus { border-color: var(--app-accent); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.scene-duration-editor > label > span { color: var(--app-text-secondary); font-size: 11px; font-weight: 650; }
.scene-duration-editor > div { display: flex; justify-content: flex-end; gap: 8px; }
.scene-prompt-video-preview { position: fixed; inset: 0; z-index: 181; display: grid; place-items: center; padding: 24px; background: rgb(26 29 37 / 76%); backdrop-filter: blur(10px); }
.scene-prompt-video-preview > section { display: grid; width: min(980px,calc(100vw - 48px)); max-height: calc(100dvh - 48px); grid-template-rows: 54px minmax(0,1fr); overflow: hidden; border-radius: 18px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 24px 72px rgb(12 15 24 / 30%); }
.scene-prompt-video-preview header { display: flex; align-items: center; justify-content: space-between; padding: 0 14px 0 18px; }
.scene-prompt-video-preview header > div { display: flex; min-width: 0; align-items: center; gap: 8px; }
.scene-prompt-video-preview header strong { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.scene-prompt-video-preview video { width: 100%; max-height: calc(100dvh - 102px); background: #171a21; object-fit: contain; }
.scene-prompt-preview-enter-active,.scene-prompt-preview-leave-active { transition: opacity .2s ease; }
.scene-prompt-preview-enter-from,.scene-prompt-preview-leave-to { opacity: 0; }
@media (max-width: 520px) {
  .scene-prompt-editor { min-height: 320px; }
  .scene-prompt-editor__input { min-height: 320px; }
  .scene-prompt-video-preview { padding: 10px; }
  .scene-prompt-video-preview > section { width: calc(100vw - 20px); max-height: calc(100dvh - 20px); }
}
@media (hover: none) { .scene-prompt-hover-preview { display: none; } }
@media (prefers-reduced-motion: reduce) {
  .scene-prompt-menu-enter-active,.scene-prompt-menu-leave-active,.scene-prompt-preview-enter-active,.scene-prompt-preview-leave-active,.scene-prompt-hover-preview-enter-active,.scene-prompt-hover-preview-leave-active { transition-duration: .01ms !important; }
}
</style>
