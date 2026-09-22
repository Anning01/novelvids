<script setup lang="ts">
import { useId } from 'vue'
import { ChevronRight } from 'lucide-vue-next'

defineProps<{ title: string; summary?: string }>()
const open = defineModel<boolean>('open', { default: false })
const contentId = useId()
</script>

<template>
  <section class="agent-disclosure" :class="{ 'is-open': open }">
    <div class="agent-disclosure__heading">
      <button type="button" class="agent-disclosure__toggle" :aria-label="[title, !open && summary].filter(Boolean).join(' ')" :aria-expanded="open" :aria-controls="contentId" @click="open = !open">
        <ChevronRight :size="12" class="agent-disclosure__chevron" aria-hidden="true" />
        <slot name="icon" /><span class="agent-disclosure__title"><slot name="title">{{ title }}</slot></span>
        <span v-if="!open && summary" class="agent-disclosure__summary">{{ summary }}</span>
      </button>
      <slot name="actions" />
    </div>
    <div :id="contentId" class="agent-disclosure__collapse" :inert="open ? undefined : true" :aria-hidden="!open">
      <div class="agent-disclosure__clip"><div class="agent-disclosure__body"><slot /></div></div>
    </div>
  </section>
</template>

<style scoped>
/* Beautiful UI ThinkingState grid disclosure, adapted for Vue. See beautiful-ui.NOTICE.md. */
.agent-disclosure { min-width: 0; width: 100%; }
.agent-disclosure__heading { display: flex; align-items: center; gap: 4px; min-width: 0; }
.agent-disclosure__toggle { display: flex; align-items: center; gap: 5px; flex: 1; min-width: 0; min-height: 26px; padding: 3px 2px; border: 0; border-radius: 6px; color: var(--app-text-secondary); background: transparent; font: inherit; font-size: 11px; text-align: left; cursor: pointer; transition: background .1s, color .1s; }
.agent-disclosure__toggle:hover { background: var(--app-surface-hover); color: var(--app-text); }
.agent-disclosure__toggle:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; }
.agent-disclosure__title { flex-shrink: 0; font-weight: 500; }
.agent-disclosure__summary { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--app-text-muted); }
.agent-disclosure__chevron { flex-shrink: 0; transition: transform .3s cubic-bezier(.23,1,.32,1); }
.is-open > .agent-disclosure__heading .agent-disclosure__chevron { transform: rotate(90deg); }
.agent-disclosure__collapse { display: grid; grid-template-rows: 0fr; opacity: 0; visibility: hidden; transition: grid-template-rows .3s cubic-bezier(.23,1,.32,1), opacity .2s, visibility .3s; }
.is-open > .agent-disclosure__collapse { grid-template-rows: 1fr; opacity: 1; visibility: visible; }
.agent-disclosure__clip { min-height: 0; overflow: hidden; }
.agent-disclosure__body { padding: 3px 0 5px; }
@media (prefers-reduced-motion: reduce) { .agent-disclosure__collapse, .agent-disclosure__chevron { transition: none; } }
</style>
