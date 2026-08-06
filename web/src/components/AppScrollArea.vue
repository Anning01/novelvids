<script setup lang="ts">
import { ref } from 'vue'

withDefaults(defineProps<{
  direction?: 'vertical' | 'horizontal' | 'both'
  ariaLabel?: string
}>(), {
  direction: 'vertical',
  ariaLabel: undefined,
})

const element = ref<HTMLElement | null>(null)

defineExpose({
  scrollTo: (options: ScrollToOptions) => element.value?.scrollTo(options),
  element,
})
</script>

<template>
  <div
    ref="element"
    class="app-scroll-area"
    :class="`is-${direction}`"
    :aria-label="ariaLabel"
    tabindex="0"
  >
    <slot />
  </div>
</template>

<style scoped>
.app-scroll-area {
  position: relative;
  overscroll-behavior: contain;
  scrollbar-color: transparent transparent;
  scrollbar-width: thin;
  transition: scrollbar-color .18s ease;
}

.app-scroll-area.is-vertical { overflow-x: hidden; overflow-y: auto; }
.app-scroll-area.is-horizontal { overflow-x: auto; overflow-y: hidden; }
.app-scroll-area.is-both { overflow: auto; }

.app-scroll-area:hover,
.app-scroll-area:focus,
.app-scroll-area:focus-within {
  scrollbar-color: #c9cdd9 transparent;
}

.app-scroll-area:focus-visible {
  outline: 3px solid rgb(91 92 246 / 12%);
  outline-offset: -2px;
  border-radius: 10px;
}

.app-scroll-area::-webkit-scrollbar { width: 7px; height: 7px; }
.app-scroll-area::-webkit-scrollbar-track { background: transparent; }
.app-scroll-area::-webkit-scrollbar-thumb {
  min-height: 36px;
  border: 2px solid transparent;
  border-radius: 999px;
  background: transparent;
  background-clip: padding-box;
}
.app-scroll-area:hover::-webkit-scrollbar-thumb,
.app-scroll-area:focus::-webkit-scrollbar-thumb,
.app-scroll-area:focus-within::-webkit-scrollbar-thumb {
  background-color: #c9cdd9;
}
.app-scroll-area::-webkit-scrollbar-thumb:hover { background-color: #aeb3c3; }
</style>
