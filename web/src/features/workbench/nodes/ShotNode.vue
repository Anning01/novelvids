<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed, inject, ref, watch } from 'vue'
import { LoaderCircle, Pencil, Play, Save } from 'lucide-vue-next'
import type { EnumItem, Scene } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import { workbenchPromptEditorKey } from '../prompt/promptEditor'
import { sceneAssetIds, sceneAssets } from '../graph/sceneAssets'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const scene = computed(() => props.data.scene as Scene)
const options = computed(() => (props.data.modelOptions || []) as EnumItem[])
const description = ref('')
const prompt = ref('')
const duration = ref(6)
const model = ref('')
const saving = ref(false)

watch(scene, value => {
  description.value = value.description || ''
  prompt.value = value.prompt || ''
  duration.value = value.duration || 6
}, { immediate: true })
watch(options, value => {
  if (!model.value && value.length) model.value = String(value[0].value)
}, { immediate: true })

const busy = computed(() => store.busySceneIds.includes(scene.value.id))
const promptEditorOpen = computed(() => promptEditor?.activeNodeKey.value === props.id)
const references = computed(() => sceneAssets(scene.value, store.assets).flatMap((asset) => {
  if (!asset.main_image) return []
  return [{
    key: String(asset.id),
    name: asset.canonical_name,
    url: asset.main_image,
    nodeKey: `asset-${asset.id}`,
    removable: true,
  }]
}))

async function save() {
  saving.value = true
  try {
    await store.saveScene(scene.value.id, {
      description: description.value,
      prompt: prompt.value,
      duration: duration.value,
    })
  } finally {
    saving.value = false
  }
}

async function generate() {
  await save()
  if (model.value) await store.generateVideo(scene.value.id, Number(model.value))
}

function focusReference(nodeKey: string) {
  promptEditor?.close(props.id)
  store.selectNode(nodeKey)
}

async function removeReference(key: string) {
  const assetId = Number(key)
  if (!Number.isFinite(assetId)) return
  await store.saveScene(scene.value.id, {
    asset_ids: sceneAssetIds(scene.value).filter(id => id !== assetId),
  })
}
</script>

<template>
  <WorkbenchNodeFrame
    v-bind="props"
    :data="{ ...data, kind: 'shot', title: `镜头 ${String(scene.sequence).padStart(2, '0')}`, status: busy ? 'running' : 'ready' }"
  >
    <div class="workbench-node-content">
      <label class="workbench-field">
        <span>画面描述</span>
        <textarea v-model="description" rows="2" />
      </label>
      <section class="workbench-prompt-summary">
        <div>
          <span>生成提示词</span>
          <button type="button" aria-label="打开生成提示词编辑器" @click.stop="promptEditor?.open(props.id)">
            <Pencil :size="13" aria-hidden="true" />
            编辑
          </button>
        </div>
        <p>{{ prompt || '暂未填写生成提示词' }}</p>
      </section>
      <div class="workbench-form-row">
        <label class="workbench-field">
          <span>时长（秒）</span>
          <input v-model.number="duration" type="number" min="1" max="30">
        </label>
        <label class="workbench-field">
          <span>视频模型</span>
          <select v-model="model">
            <option v-for="option in options" :key="option.value" :value="String(option.value)">
              {{ option.label }}
            </option>
          </select>
        </label>
      </div>
      <div class="workbench-node-actions">
        <AppButton type="button" :disabled="saving" @click="save">
          <Save :size="14" aria-hidden="true" />{{ saving ? '保存中' : '保存' }}
        </AppButton>
        <AppButton type="button" class="is-primary" :disabled="busy || saving || !model" @click="generate">
          <LoaderCircle v-if="busy" class="workbench-node-context__loading-icon" :size="14" aria-hidden="true" />
          <Play v-else :size="14" aria-hidden="true" />{{ busy ? '生成中' : '生成视频' }}
        </AppButton>
      </div>
    </div>
  </WorkbenchNodeFrame>

  <WorkbenchPromptEditorPanel
    :open="promptEditorOpen"
    :node-key="props.id"
    label="镜头生成提示词"
    v-model="prompt"
    placeholder="描述镜头主体、动作、镜头运动、光线和风格…"
    hint="编辑区会跟随当前镜头，也可以进入专注模式"
    :busy="busy || saving"
    :run-enabled="Boolean(model)"
    :references="references"
    run-label="保存并生成视频"
    busy-label="处理中"
    @close="promptEditor?.close(props.id)"
    @save="save"
    @run="generate"
    @focus-reference="focusReference"
    @remove-reference="removeReference"
  />
</template>
