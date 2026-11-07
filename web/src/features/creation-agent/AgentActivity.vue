<script setup lang="ts">
import { Sparkles } from 'lucide-vue-next'
defineProps<{ text: string; active: boolean }>()
</script>

<template>
  <span class="agent-activity" :class="{ 'is-active': active }" role="status">
    <Sparkles v-if="active" :size="13" aria-hidden="true" />
    <span class="agent-activity__text">{{ text }}</span>
  </span>
</template>

<style scoped>
/* Keep the status readable in both themes; animate only the activity icon. */
.agent-activity { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: var(--app-text-secondary); font-size: 11px; }
.agent-activity__text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.is-active { color: var(--app-text); }
.is-active svg { animation: agent-pulse 1.4s ease-in-out infinite; }
@keyframes agent-pulse { 50% { opacity: .45; } }
@media (prefers-reduced-motion: reduce) { .is-active svg { animation: none; } }
</style>
