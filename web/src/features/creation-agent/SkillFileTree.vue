<script setup lang="ts">
import { ChevronRight, File, FolderOpen } from 'lucide-vue-next'
import type { SkillFileNode } from './skillFiles'
defineProps<{ nodes: SkillFileNode[]; selected: string; disabled?: boolean }>()
defineEmits<{ select: [path: string] }>()
</script>
<template>
  <ul class="skill-file-tree">
    <li v-for="node in nodes" :key="node.path">
      <details v-if="node.directory" open>
        <summary :title="node.path" :aria-current="selected === node.path ? 'true' : undefined" @click="$emit('select', node.path)"><ChevronRight class="folder-chevron" :size="12" aria-hidden="true" /><FolderOpen :size="14" aria-hidden="true" /><span>{{ node.name }}</span></summary>
        <SkillFileTree :nodes="node.children" :selected="selected" :disabled="disabled" @select="$emit('select', $event)" />
      </details>
      <button v-else type="button" :aria-current="selected === node.path ? 'true' : undefined" :disabled="disabled" :title="node.path" @click="$emit('select', node.path)"><File :size="14" aria-hidden="true" /><span>{{ node.name }}</span></button>
    </li>
  </ul>
</template>
<style scoped>
.skill-file-tree { list-style: none; margin: 0; padding: 0; min-inline-size: 0; }
.skill-file-tree .skill-file-tree { padding-inline-start: 12px; }
button, summary { display: flex; gap: 7px; align-items: center; box-sizing: border-box; inline-size: 100%; padding: 8px; color: var(--app-text-secondary); font: inherit; font-size: 12px; background: transparent; border: 0; border-radius: 6px; text-align: start; cursor: pointer; }
span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } svg { flex: none; }
details[open] > summary .folder-chevron { transform: rotate(90deg); }
summary { list-style: none; } summary::-webkit-details-marker { display: none; }
button:hover, summary:hover { background: var(--app-surface-hover); color: var(--app-text); }
button[aria-current='true'], summary[aria-current='true'] { color: var(--app-accent); background: var(--app-accent-soft); }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; }
button:disabled { opacity: .6; cursor: not-allowed; }
@media (pointer: coarse) { button, summary { min-block-size: 44px; } }
</style>
