<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed, ref } from 'vue'
import { Library, ScanFace } from 'lucide-vue-next'
import type { AudioReference, DigitalHuman } from '@/types'
import MediaLibraryPicker from '../components/MediaLibraryPicker.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const pickerOpen = ref(false)
const resource = computed(() => props.data.resource as DigitalHuman | undefined)
function choose(item: AudioReference | DigitalHuman) { store.setMediaResource(props.id, item); pickerOpen.value = false }
</script>
<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'digital_human', title: resource ? `${resource.country} · ${resource.occupation}` : '数字人', status: resource ? 'ready' : '未选择' }">
    <div class="workbench-node-content media-resource-node">
      <div v-if="resource" class="media-resource-preview is-digital-human"><img :src="resource.image_url" :alt="`${resource.country}${resource.occupation}数字人`" loading="lazy" decoding="async"><div><strong>{{ resource.country }} · {{ resource.occupation }}</strong><span>{{ resource.age }} 岁 · {{ resource.gender }}</span><code>{{ resource.asset_id }}</code></div></div>
      <div v-else class="media-resource-placeholder"><ScanFace :size="25" aria-hidden="true" /><span>选择一位纯数字人</span></div>
      <AppButton type="button" class="media-resource-select" @click="pickerOpen = true"><Library :size="15" aria-hidden="true" />{{ resource ? '更换数字人' : '从数字人库选择' }}</AppButton>
    </div>
    <MediaLibraryPicker :open="pickerOpen" kind="digital-human" :selected-asset-id="resource?.asset_id" @close="pickerOpen = false" @choose="choose" />
  </WorkbenchNodeFrame>
</template>
