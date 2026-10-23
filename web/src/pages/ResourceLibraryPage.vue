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
  min-height: calc(100vh - var(--short-drama-header-height, 72px));
  background: #151412;
  color: #eee9e2;
}
</style>
