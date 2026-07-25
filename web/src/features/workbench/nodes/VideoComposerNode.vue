<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { ChevronDown, ChevronUp, Film, Play } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import {
  COMPOSER_ASPECT_RATIOS,
  COMPOSER_RESOLUTIONS,
  normalizeComposerConfig,
  orderedComposerInputs,
  type ComposerConfig,
} from '../config/composerConfig'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const storedConfig = computed(() => normalizeComposerConfig(
  (store.nodeByKey(props.id)?.data.config || props.data.config) as Partial<ComposerConfig>,
))
const draft = ref(storedConfig.value)
watch(storedConfig, value => { draft.value = value }, { deep: true })
const inputs = computed(() => orderedComposerInputs(props.id, store.nodes, store.edges))
const disabledReason = computed(() => {
  if (!props.data.compose_capability) return '当前服务未启用视频合成'
  if (!inputs.value.length) return '请连接至少一个镜头或视频'
  return '视频合成接口尚未接入'
})

function saveConfig() {
  draft.value = normalizeComposerConfig(draft.value)
  store.saveVideoComposerConfig(props.id, draft.value)
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_composer', title: '视频合成器', status: 'ready' }">
    <div class="workbench-composer-node">
      <div class="workbench-composer-node__ports" aria-label="合成器输入类型">
        <span><i class="is-shot" />镜头输入<small>可选</small></span>
        <span><i class="is-video" />视频输入<small>可选</small></span>
      </div>
      <label class="workbench-field">
        <span>成片名称</span>
        <input v-model="draft.name" aria-label="成片名称" @change="saveConfig">
      </label>

      <section class="workbench-composer-node__inputs">
        <header><strong>成片输入</strong><span v-if="inputs.length">视频 {{ inputs.length }} 个</span></header>
        <ol v-if="inputs.length" aria-label="成片输入顺序">
          <li v-for="(input, index) in inputs" :key="input.key">
            <span>{{ String(index + 1).padStart(2, '0') }}</span>
            <div><strong>{{ input.title }}</strong><small>{{ input.sourceKind === 'shot' ? '镜头输入' : '视频输入' }}</small></div>
            <div>
              <button v-if="index > 0" type="button" :aria-label="`将 ${input.title} 上移`" @click="store.moveComposerInput(props.id, input.key, 'up')"><ChevronUp :size="14" aria-hidden="true" /></button>
              <button v-if="index < inputs.length - 1" type="button" :aria-label="`将 ${input.title} 下移`" @click="store.moveComposerInput(props.id, input.key, 'down')"><ChevronDown :size="14" aria-hidden="true" /></button>
            </div>
          </li>
        </ol>
        <p v-else>从蓝色镜头端口或绿色视频端口连接</p>
      </section>

      <p class="workbench-composer-node__watermark">可将水印资产通过输出线连接到此成片</p>

      <fieldset class="workbench-composer-node__params">
        <legend>生成参数</legend>
        <label class="workbench-field">分辨率
          <select v-model="draft.resolution" aria-label="分辨率" @change="saveConfig">
            <option v-for="resolution in COMPOSER_RESOLUTIONS" :key="resolution" :value="resolution">{{ resolution }}</option>
          </select>
        </label>
        <label class="workbench-field">画面比例
          <select v-model="draft.aspectRatio" aria-label="画面比例" @change="saveConfig">
            <option v-for="ratio in COMPOSER_ASPECT_RATIOS" :key="ratio" :value="ratio">{{ ratio }}</option>
          </select>
        </label>
      </fieldset>

      <p class="workbench-composer-node__alert" role="alert">{{ disabledReason }}</p>
      <button type="button" class="workbench-composer-node__run" :aria-label="disabledReason" :title="disabledReason" disabled>
        <Play :size="15" aria-hidden="true" /><span>合成并预览</span>
      </button>
      <span class="workbench-composer-node__output"><Film :size="13" aria-hidden="true" />结果输出端口</span>
    </div>
  </WorkbenchNodeFrame>
</template>
