<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from './components/layout/AppLayout.vue'
import ToastContainer from './components/common/ToastContainer.vue'

const route = useRoute()

// Editor routes use their own layout, skip AppLayout
const isEditorRoute = computed(() => route.path.startsWith('/editor/'))
</script>

<template>
  <!-- Editor has its own layout -->
  <template v-if="isEditorRoute">
    <router-view />
  </template>
  <!-- Other routes use AppLayout -->
  <template v-else>
    <AppLayout>
      <router-view />
    </AppLayout>
  </template>
  <ToastContainer />
</template>
