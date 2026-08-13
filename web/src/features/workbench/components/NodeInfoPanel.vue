<script setup lang="ts">
import type { WorkbenchNode } from '../types/workbenchTypes'
import { FileJson2, Image as ImageIcon, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<{ node: WorkbenchNode; actionError?: string }>()
const emit = defineEmits<{ close: [] }>()
const store = useWorkbenchStore()

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function mediaUrl(node: WorkbenchNode) {
  const asset = record(node.data.asset)
  const resource = record(node.data.resource)
  const video = record(node.data.video)
  return text(asset.main_image) || text(resource.image_url) || text(resource.avatar_url) || text(video.url)
}

const payload = computed(() => {
  const { ui: _ui, modelOptions: _modelOptions, videoModelOptions: _videoModelOptions, ...data } = props.node.data
  return data
})
const prompt = computed(() => {
  const scene = record(props.node.data.scene)
  const asset = record(props.node.data.asset)
  const chapter = record(props.node.data.chapter)
  return text(scene.prompt)
    || text(asset.description)
    || text(props.node.data.description)
    || text(props.node.data.content)
    || text(chapter.content)
})
const incomingReferences = computed(() => store.edges
  .filter(edge => edge.target === props.node.key)
  .sort((left, right) => left.orderIndex - right.orderIndex || left.id - right.id)
  .flatMap((edge) => {
    const source = store.nodeByKey(edge.source)
    return source ? [{ edge, node: source, url: mediaUrl(source) }] : []
  }))
const sizeLabel = computed(() => props.node.size ? `${Math.round(props.node.size.width)} × ${Math.round(props.node.size.height)}` : '自动')
const payloadJson = computed(() => JSON.stringify(payload.value, null, 2))

function closeOnEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', closeOnEscape))
onBeforeUnmount(() => window.removeEventListener('keydown', closeOnEscape))
</script>

<template>
  <Teleport to="body">
    <div class="workbench-node-info-backdrop viral-workbench-surface-theme" @pointerdown.self="emit('close')">
      <aside class="workbench-node-info nodrag nowheel workbench-scroll-region" role="dialog" aria-modal="true" :aria-label="`${node.title}节点信息`">
        <header class="workbench-node-info__header">
          <div><span>节点信息</span><strong>{{ node.title }}</strong></div>
          <button type="button" aria-label="关闭节点信息" title="关闭（Esc）" @click="emit('close')"><X :size="19" aria-hidden="true" /></button>
        </header>

        <section class="workbench-node-info__summary">
          <div><span>节点类型</span><strong>{{ node.kind }}</strong></div>
          <div><span>节点状态</span><strong>{{ node.status }}</strong></div>
          <div><span>节点位置</span><strong>{{ Math.round(node.position.x) }}, {{ Math.round(node.position.y) }}</strong></div>
          <div><span>节点尺寸</span><strong>{{ sizeLabel }}</strong></div>
        </section>

        <p v-if="actionError" class="workbench-node-info__error" role="alert">{{ actionError }}</p>

        <section class="workbench-node-info__section">
          <h3>节点 Prompt</h3>
          <pre v-if="prompt">{{ prompt }}</pre>
          <p v-else class="workbench-node-info__empty">该节点没有文本 Prompt。</p>
        </section>

        <section class="workbench-node-info__section">
          <h3>输入节点 <span>{{ incomingReferences.length }}</span></h3>
          <div v-if="incomingReferences.length" class="workbench-node-info__references">
            <article v-for="reference in incomingReferences" :key="reference.edge.key">
              <img v-if="reference.url && reference.node.kind !== 'video_result'" :src="reference.url" :alt="reference.node.title" loading="lazy" decoding="async">
              <div v-else class="workbench-node-info__reference-icon"><ImageIcon :size="20" aria-hidden="true" /></div>
              <div>
                <strong>{{ reference.node.title }}</strong>
                <span>{{ reference.edge.type }}</span>
                <p>{{ reference.node.kind }}</p>
              </div>
            </article>
          </div>
          <p v-else class="workbench-node-info__empty">暂无输入节点。</p>
        </section>

        <details class="workbench-node-info__raw">
          <summary><FileJson2 :size="15" aria-hidden="true" />查看节点数据</summary>
          <pre>{{ payloadJson }}</pre>
        </details>

        <footer>
          <span>节点 ID：{{ node.key }}</span>
          <span>层级：{{ node.zIndex }}</span>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>
