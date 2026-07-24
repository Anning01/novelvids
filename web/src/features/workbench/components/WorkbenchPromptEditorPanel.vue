<script setup lang="ts">
import type { CSSProperties } from 'vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { LoaderCircle, Maximize2, Minimize2, Play, Save, X } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  open: boolean
  nodeKey: string
  label: string
  modelValue: string
  placeholder?: string
  hint?: string
  busy?: boolean
  runEnabled?: boolean
  saveLabel?: string
  runLabel?: string
  busyLabel?: string
  references?: Array<{
    key: string
    name: string
    url: string
    nodeKey?: string
    removable?: boolean
  }>
}>(), {
  placeholder: '输入生成提示词…',
  hint: '',
  busy: false,
  runEnabled: true,
  saveLabel: '保存',
  runLabel: '生成',
  busyLabel: '生成中',
  references: () => [],
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'close': []
  'save': []
  'run': []
  'focusReference': [nodeKey: string]
  'removeReference': [key: string]
}>()

const panel = ref<HTMLElement | null>(null)
const editor = ref<HTMLTextAreaElement | null>(null)
const panelStyle = ref<CSSProperties>({ visibility: 'hidden' })
const expanded = ref(false)
const textLength = computed(() => Array.from(props.modelValue.trim()).length)
let animationFrame = 0

function anchorElement() {
  return [...document.querySelectorAll<HTMLElement>('.vue-flow__node')]
    .find(element => element.dataset.id === props.nodeKey) ?? null
}

function updatePosition() {
  if (!props.open || !panel.value) return
  const padding = expanded.value ? 24 : 12
  if (expanded.value) {
    panelStyle.value = {
      top: '8vh',
      left: '50%',
      width: `${Math.min(1180, window.innerWidth - padding * 2)}px`,
      height: '84vh',
      maxHeight: '84vh',
      transform: 'translateX(-50%)',
      visibility: 'visible',
    }
    return
  }
  const anchor = anchorElement()
  if (!anchor) {
    panelStyle.value = {
      left: '50%',
      bottom: '18px',
      width: `${Math.min(900, window.innerWidth - padding * 2)}px`,
      transform: 'translateX(-50%)',
      visibility: 'visible',
    }
    return
  }
  const rect = anchor.getBoundingClientRect()
  const width = Math.min(900, Math.max(360, window.innerWidth - padding * 2))
  const left = Math.min(
    window.innerWidth - width - padding,
    Math.max(padding, rect.left + rect.width / 2 - width / 2),
  )
  const preferredTop = rect.bottom + 12
  const maxHeight = Math.max(220, window.innerHeight - preferredTop - padding)
  panelStyle.value = {
    top: `${preferredTop}px`,
    left: `${left}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
    visibility: 'visible',
  }
}

function stopPositioning() {
  if (!animationFrame) return
  cancelAnimationFrame(animationFrame)
  animationFrame = 0
}

function startPositioning() {
  stopPositioning()
  const position = () => {
    updatePosition()
    animationFrame = requestAnimationFrame(position)
  }
  position()
}

watch(() => props.open, async (open) => {
  if (!open) {
    stopPositioning()
    expanded.value = false
    return
  }
  panelStyle.value = { visibility: 'hidden' }
  await nextTick()
  startPositioning()
  editor.value?.focus()
}, { immediate: true })

watch(expanded, async () => {
  await nextTick()
  updatePosition()
  editor.value?.focus()
})

onMounted(() => window.addEventListener('resize', updatePosition))
onBeforeUnmount(() => {
  stopPositioning()
  window.removeEventListener('resize', updatePosition)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open && expanded"
      class="workbench-prompt-focus-backdrop"
      aria-hidden="true"
      @pointerdown="expanded = false"
    />
    <section
      v-if="open"
      ref="panel"
      class="viral-workbench-surface-theme workbench-prompt-panel nodrag nowheel"
      :class="{ 'is-expanded': expanded }"
      :style="panelStyle"
      role="dialog"
      :aria-modal="expanded"
      :aria-label="`${label}编辑器`"
      @keydown.esc.stop="emit('close')"
      @pointerdown.stop
      @click.stop
      @wheel.stop
    >
      <header class="workbench-prompt-panel__header">
        <div>
          <strong>{{ label }}</strong>
          <small v-if="hint">{{ hint }}</small>
        </div>
        <div class="workbench-prompt-panel__actions">
          <button
            type="button"
            :aria-label="expanded ? '退出 Prompt 专注模式' : '进入 Prompt 专注模式'"
            :title="expanded ? '退出专注模式' : '进入专注模式'"
            :aria-pressed="expanded"
            @click="expanded = !expanded"
          >
            <Minimize2 v-if="expanded" :size="18" aria-hidden="true" />
            <Maximize2 v-else :size="18" aria-hidden="true" />
          </button>
          <button type="button" aria-label="关闭 Prompt 编辑器" title="关闭" @click="emit('close')">
            <X :size="18" aria-hidden="true" />
          </button>
        </div>
      </header>

      <ol v-if="references.length" class="workbench-prompt-references" aria-label="Prompt 参考图片">
        <li v-for="(reference, index) in references" :key="reference.key" class="workbench-prompt-reference">
          <button
            type="button"
            class="workbench-prompt-reference__thumbnail"
            :aria-label="reference.nodeKey ? `参考图片 ${index + 1}：${reference.name}，选择来源节点` : `参考图片 ${index + 1}：${reference.name}`"
            @click="reference.nodeKey && emit('focusReference', reference.nodeKey)"
          >
            <img :src="reference.url" :alt="reference.name" loading="lazy" decoding="async">
            <span>{{ index + 1 }}</span>
          </button>
          <button
            v-if="reference.removable"
            type="button"
            class="workbench-prompt-reference__remove"
            :aria-label="`移除参考图片：${reference.name}`"
            @click="emit('removeReference', reference.key)"
          >
            <X :size="13" aria-hidden="true" />
          </button>
        </li>
      </ol>

      <textarea
        ref="editor"
        class="workbench-prompt-panel__editor"
        :value="modelValue"
        :placeholder="placeholder"
        :aria-label="label"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      />

      <footer class="workbench-prompt-panel__footer">
        <span>{{ textLength }} 字</span>
        <div class="workbench-prompt-panel__footer-actions">
          <button type="button" class="workbench-prompt-panel__secondary-action" :disabled="busy" @click="emit('save')">
            <Save :size="14" aria-hidden="true" />
            <span>{{ saveLabel }}</span>
          </button>
          <button
            type="button"
            class="workbench-prompt-panel__primary-action"
            :disabled="busy || !runEnabled"
            :aria-busy="busy"
            @click="emit('run')"
          >
            <LoaderCircle v-if="busy" class="workbench-prompt-panel__action-spinner" :size="15" aria-hidden="true" />
            <Play v-else :size="14" aria-hidden="true" />
            <span>{{ busy ? busyLabel : runLabel }}</span>
          </button>
        </div>
      </footer>
    </section>
  </Teleport>
</template>
