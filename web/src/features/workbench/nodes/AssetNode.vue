<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
import type { Asset } from '@/types'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
const props = defineProps<NodeProps>()
const asset = computed(() => props.data.asset as Asset)
</script>
<template><WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'asset', title: asset.canonical_name }"><div class="workbench-node-summary"><img v-if="asset.main_image" class="workbench-node-summary__media" :src="asset.main_image" :alt="asset.canonical_name"><div v-else class="workbench-media-empty">尚未生成主图</div><p class="workbench-node-summary__prompt">{{ asset.description || asset.base_traits || '暂无视觉描述' }}</p><div class="workbench-node-summary__meta"><span>{{ data.asset_type }}</span><span v-if="asset.aliases?.length">@{{ asset.aliases[0] }}</span></div></div></WorkbenchNodeFrame></template>
