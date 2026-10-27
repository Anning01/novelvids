<script setup lang="ts">
import ResourceLibraryBrowser from '@/features/resource-library/ResourceLibraryBrowser.vue'
</script>
<template>
  <div class="resource-library-page">
    <ResourceLibraryBrowser />
  </div>
</template>
<style scoped>
.resource-library-page {
  min-height: 100%;
  background: var(--app-canvas);
  color: var(--app-text);
}
</style>
