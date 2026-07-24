<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed, inject, ref, watch } from 'vue'
import { Pencil } from 'lucide-vue-next'
import type { Asset } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import { workbenchPromptEditorKey } from '../prompt/promptEditor'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const asset = computed(() => props.data.asset as Asset)
const description = ref('')
const saving = ref(false)

watch(asset, value => {
  description.value = value.description || ''
}, { immediate: true })

const busy = computed(() => store.busyAssetIds.includes(asset.value.id))
const promptEditorOpen = computed(() => promptEditor?.activeNodeKey.value === props.id)
const references = computed(() => [
  { key: 'main', name: `${asset.value.canonical_name}主图`, url: asset.value.main_image },
  { key: 'angle-1', name: `${asset.value.canonical_name}参考图 1`, url: asset.value.angle_image_1 },
  { key: 'angle-2', name: `${asset.value.canonical_name}参考图 2`, url: asset.value.angle_image_2 },
].filter((item): item is { key: string; name: string; url: string } => Boolean(item.url)))

async function save() {
  saving.value = true
  try {
    await store.saveAsset(asset.value.id, { description: description.value })
  } finally {
    saving.value = false
  }
}

async function generate() {
  await save()
  await store.generateAsset(asset.value.id)
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'asset', title: asset.canonical_name, status: busy ? 'running' : 'ready' }">
    <div class="workbench-node-summary">
      <img v-if="asset.main_image" class="workbench-node-summary__media" :src="asset.main_image" :alt="asset.canonical_name" loading="lazy" decoding="async">
      <div v-else class="workbench-media-placeholder">尚未生成主图</div>
      <p class="workbench-node-summary__prompt">{{ description || asset.base_traits || '暂无视觉描述' }}</p>
      <div class="workbench-node-summary__meta">
        <span>{{ data.asset_type }}</span>
        <span v-if="asset.aliases?.length">@{{ asset.aliases[0] }}</span>
        <button class="workbench-asset-edit-button" type="button" @click.stop="promptEditor?.open(props.id)">
          <Pencil :size="13" aria-hidden="true" />编辑与生成
        </button>
      </div>
    </div>
  </WorkbenchNodeFrame>

  <WorkbenchPromptEditorPanel
    :open="promptEditorOpen"
    :node-key="props.id"
    label="资产视觉描述"
    v-model="description"
    placeholder="描述人物、场景或道具的稳定视觉特征…"
    hint="保存后可直接使用当前描述重新生成资产主图"
    :busy="busy || saving"
    :references="references"
    save-label="保存描述"
    run-label="保存并生成主图"
    busy-label="处理中"
    @close="promptEditor?.close(props.id)"
    @save="save"
    @run="generate"
  />
</template>
