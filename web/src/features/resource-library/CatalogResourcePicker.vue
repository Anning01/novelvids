<script setup lang="ts">
import { ElDialog } from 'element-plus'
import { tr } from '@/i18n'
import ResourceCatalogBrowser from './ResourceCatalogBrowser.vue'
import type { CatalogKind, CatalogResource } from './catalog'
import './dialog.css'
defineProps<{open:boolean;kind?:CatalogKind;maxSelection?:number}>()
const emit=defineEmits<{close:[];choose:[items:CatalogResource[]]}>()
</script>
<template><ElDialog class="resource-library-dialog" :model-value="open" :title="tr('从资源库选择')" width="min(1120px, 96vw)" append-to-body destroy-on-close @close="emit('close')"><ResourceCatalogBrowser v-if="open" pick :kind="kind" :max-selection="maxSelection" @choose="items=>emit('choose',items)"/></ElDialog></template>
