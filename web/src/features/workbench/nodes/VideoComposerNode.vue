<script setup lang="ts">
import { tr } from '@/i18n'

import type { NodeProps } from '@vue-flow/core'
import { ChevronDown, ChevronUp, Download, Film } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { mediaUrl } from '@/api'
import DeferredVideoPlayer from '@/components/DeferredVideoPlayer.vue'
import type { VideoMergeResult } from '@/types'
import {
  chapterComposerDisabledReason,
  COMPOSER_ASPECT_RATIOS,
  COMPOSER_RESOLUTIONS,
  normalizeComposerConfig,
  orderedComposerInputs,
  type ComposerConfig,
} from '../config/composerConfig'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchRunButton from '../components/WorkbenchRunButton.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'
import { useWorkbenchStore } from '../store/workbenchStore'
import { registerWorkbenchNodeRun } from '../run/nodeRunRegistry'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const storedConfig = computed(() => normalizeComposerConfig(
  (store.nodeByKey(props.id)?.data.config || props.data.config) as Partial<ComposerConfig>,
))
const draft = ref(storedConfig.value)
watch(storedConfig, value => { draft.value = value }, { deep: true })
const inputs = computed(() => orderedComposerInputs(props.id, store.nodes, store.edges))
const busy = computed(() => store.busyComposerKeys.includes(props.id))
const result = computed(() => (store.nodeByKey(props.id)?.data.result || props.data.result) as VideoMergeResult | undefined)
const resolutionOptions = COMPOSER_RESOLUTIONS.map(value => ({ value, label: value }))
const aspectRatioOptions = COMPOSER_ASPECT_RATIOS.map(value => ({ value, label: value }))
const disabledReason = computed(() => {
  if (!props.data.compose_capability) return tr('当前服务未启用视频合成')
  return chapterComposerDisabledReason(props.id, store.nodes, store.edges)
})
const canCompose = computed(() => !disabledReason.value && !busy.value)

function saveConfig() {
  draft.value = normalizeComposerConfig(draft.value)
  store.saveVideoComposerConfig(props.id, draft.value)
}

async function compose() {
  if (!canCompose.value) return
  await store.composeChapter(props.id)
}

registerWorkbenchNodeRun(props.id, { enabled: canCompose, run: compose })
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_composer', title: tr('视频合成器'), status: 'ready' }">
    <div class="workbench-composer-node">
      <div class="workbench-composer-node__ports" :aria-label="tr('合成器输入类型')">
        <span><i class="is-shot" />{{ tr('生成视频') }}<small>{{ tr('可选') }}</small></span>
        <span><i class="is-video" />{{ tr('视频素材') }}<small>{{ tr('可选') }}</small></span>
      </div>
      <label class="workbench-field">
        <span>{{ tr('成片名称') }}</span>
        <input v-model="draft.name" :aria-label="tr('成片名称')" @change="saveConfig">
      </label>

      <section class="workbench-composer-node__inputs">
        <header><strong>{{ tr('成片输入') }}</strong><span v-if="inputs.length">{{ tr('视频') }} {{ inputs.length }} {{ tr('个') }}</span></header>
        <ol v-if="inputs.length" :aria-label="tr('成片输入顺序')">
          <li v-for="(input, index) in inputs" :key="input.key">
            <span>{{ String(index + 1).padStart(2, '0') }}</span>
            <div><strong>{{ input.title }}</strong><small>{{ input.sourceKind === 'shot' ? tr('生成视频') : tr('视频素材') }}</small></div>
            <div>
              <button v-if="index > 0" type="button" :aria-label="tr('将 {p0} 上移', { p0: input.title })" @click="store.moveComposerInput(props.id, input.key, 'up')"><ChevronUp :size="14" aria-hidden="true" /></button>
              <button v-if="index < inputs.length - 1" type="button" :aria-label="tr('将 {p0} 下移', { p0: input.title })" @click="store.moveComposerInput(props.id, input.key, 'down')"><ChevronDown :size="14" aria-hidden="true" /></button>
            </div>
          </li>
        </ol>
        <p v-else>{{ tr('从蓝色生成视频端口或绿色视频素材端口连接') }}</p>
      </section>

      <p class="workbench-composer-node__watermark">{{ tr('可将水印资产通过输出线连接到此成片') }}</p>

      <fieldset class="workbench-composer-node__params">
        <legend>{{ tr('生成参数') }}</legend>
        <label class="workbench-field">{{ tr('分辨率') }} <WorkbenchSelect v-model="draft.resolution" :options="resolutionOptions" :label="tr('分辨率')" @update:model-value="saveConfig" />
        </label>
        <label class="workbench-field">{{ tr('画面比例') }} <WorkbenchSelect v-model="draft.aspectRatio" :options="aspectRatioOptions" :label="tr('画面比例')" @update:model-value="saveConfig" />
        </label>
      </fieldset>

      <p v-if="disabledReason" class="workbench-composer-node__alert" role="alert">{{ disabledReason }}</p>
      <WorkbenchRunButton :label="tr('合成并预览')" :busy-label="tr('正在合成…')" :busy="busy" :disabled="Boolean(disabledReason)" @click="compose" />
      <section v-if="result?.merged_url" class="workbench-composer-node__result">
        <DeferredVideoPlayer :src="mediaUrl(result.merged_url)" :poster="mediaUrl(result.poster_url || '')" :title="tr('成片预览')" />
        <a :href="mediaUrl(result.merged_url)" :download="tr('{p0}.mp4', { p0: draft.name || '章节成片' })"><Download :size="14" aria-hidden="true" />{{ tr('下载成片') }}</a>
      </section>
      <span class="workbench-composer-node__output"><Film :size="13" aria-hidden="true" />{{ tr('结果输出端口') }}</span>
    </div>
  </WorkbenchNodeFrame>
</template>
