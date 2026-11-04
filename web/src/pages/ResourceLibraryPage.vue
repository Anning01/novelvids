<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { CatalogKind } from '@/features/resource-library/catalog'
import ResourceCatalogBrowser from '@/features/resource-library/ResourceCatalogBrowser.vue'
const route=useRoute(),router=useRouter()
const initialKind=computed(()=>typeof route.query.kind==='string'&&['all','video','image','bgm','sound','sticker','voice','character'].includes(route.query.kind)?route.query.kind as CatalogKind|'all':'all')
const initialSearch=computed(()=>typeof route.query.search==='string'?route.query.search.slice(0,255):'')
function changed(kind:CatalogKind|'all'){void router.replace({query:{...route.query,kind,search:undefined}})}
</script>
<template>
  <div class="resource-library-page">
    <ResourceCatalogBrowser :initial-kind="initialKind" :initial-search="initialSearch" @change-kind="changed" />
  </div>
</template>
<style scoped>
.resource-library-page {
  min-height: 100%;
  background: var(--app-canvas);
  color: var(--app-text);
}
</style>
