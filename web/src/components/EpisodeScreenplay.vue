<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ text: string }>()
const lines = computed(() => props.text.split(/\r?\n/).map(raw => {
  const line = raw.trim()
  const title = /^#{1,6}\s+/.test(line)
  const text = line.replace(/^#{1,6}\s+/, '').replace(/^\*\*(.+)\*\*$/, '$1')
  if (/^\d+\s*[-–－]\s*\d+(?:\s|[、.．])/.test(text)) return {kind: 'scene', text}
  if (title) return {kind: 'title', text}
  if (/^(出场|仅声音|关键道具)[：:]/.test(text)) return {kind: 'cast', text}
  if (text.startsWith('△')) return {kind: 'action', text}
  return {kind: 'line', text}
}).filter(line => line.text))
</script>

<template>
  <section class="screenplay-reading">
    <template v-for="(line, index) in lines" :key="index">
      <h4 v-if="line.kind === 'scene'" class="scene-heading">{{ line.text }}</h4>
      <p v-else :class="line.kind">{{ line.text }}</p>
    </template>
  </section>
</template>

<style scoped>
.screenplay-reading { color: var(--app-text); font-size: 14px; line-height: 1.85; overflow-wrap: anywhere; }
.screenplay-reading p { margin: .65em 0; }
.screenplay-reading .title { font-weight: 650; }
.scene-heading { margin: 1.6em 0 .45em; padding-inline-start: 10px; border-inline-start: 3px solid var(--app-accent); font-size: 15px; }
.screenplay-reading .cast { margin: 0; font-size: 12px; color: var(--app-text-secondary); }
.screenplay-reading .action { color: var(--app-text-secondary); }
</style>
