<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed, ref } from 'vue'
import { Library, Volume2 } from 'lucide-vue-next'
import type { AudioReference, DigitalHuman } from '@/types'
import MediaLibraryPicker from '../components/MediaLibraryPicker.vue'
import WorkbenchAudioMedia from '../components/WorkbenchAudioMedia.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const pickerOpen = ref(false)
const resource = computed(() => props.data.resource as AudioReference | undefined)
function choose(item: AudioReference | DigitalHuman) { store.setMediaResource(props.id, item); pickerOpen.value = false }
</script>
<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'audio_reference', title: resource?.nickname || '参考音频', status: resource ? 'ready' : '未选择' }">
    <div class="workbench-node-content media-resource-node">
      <WorkbenchAudioMedia v-if="resource" :src="resource.audio_url" :title="resource.nickname" :preview-url="resource.avatar_url" :source-label="`${resource.gender} · ${resource.asset_id}`" />
      <div v-else class="media-resource-placeholder"><Volume2 :size="24" aria-hidden="true" /><span>选择一段库内参考音频</span></div>
      <AppButton type="button" class="media-resource-select" @click="pickerOpen = true"><Library :size="15" aria-hidden="true" />{{ resource ? '更换音频' : '从音频库选择' }}</AppButton>
    </div>
    <MediaLibraryPicker :open="pickerOpen" kind="audio" :selected-asset-id="resource?.asset_id" @close="pickerOpen = false" @choose="choose" />
  </WorkbenchNodeFrame>
</template>
