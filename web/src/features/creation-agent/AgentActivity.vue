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
/* Beautiful UI ThinkingState shimmer; driven by actual run state, never a demo timer. */
.agent-activity { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: var(--app-text-secondary); font-size: 11px; }
.agent-activity__text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.is-active .agent-activity__text { color: transparent; background-image: linear-gradient(90deg, var(--app-text-muted) 35%, var(--app-text) 50%, var(--app-text-muted) 65%); background-size: 200% 100%; background-clip: text; animation: agent-shimmer 1.4s linear infinite; }
@keyframes agent-shimmer { from { background-position: 150% center; } to { background-position: -50% center; } }
@media (prefers-reduced-motion: reduce) { .is-active .agent-activity__text { animation: none; background: none; color: var(--app-text-secondary); } }
</style>
