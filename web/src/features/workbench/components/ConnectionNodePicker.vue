<script setup lang="ts">
import type { CompatibleNodeCreation } from '../graph/nodeCreationRules';
import { Box, Clapperboard, ImageUp, Sparkles, Stamp } from 'lucide-vue-next';
import { computed } from 'vue';

const props = defineProps<{
  options: CompatibleNodeCreation[];
  x: number;
  y: number;
  accentClass?: string;
}>();

defineEmits<{
  select: [option: CompatibleNodeCreation];
  close: [];
}>();

const style = computed(() => ({
  left: `${Math.max(12, Math.min(props.x + 8, window.innerWidth - 304))}px`,
  top: `${Math.max(12, Math.min(props.y + 8, window.innerHeight - 390))}px`,
}));

function optionIcon(id: string) {
  if (id === 'image')
    return ImageUp;
  if (id === 'watermark')
    return Stamp;
  if (id === 'shot')
    return Clapperboard;
  if (id.startsWith('operation:'))
    return Sparkles;
  return Box;
}
</script>

<template>
  <Teleport to="body">
    <div class="workbench-connection-picker" :class="accentClass" :style="style" role="dialog" aria-label="选择兼容节点" @pointerdown.stop @click.stop>
      <header>
        <strong>添加兼容节点</strong>
        <button type="button" aria-label="关闭节点选择" @click="$emit('close')">
          ×
        </button>
      </header>
      <div class="workbench-connection-picker__options workbench-scroll-region" role="listbox" aria-label="兼容节点列表">
        <button v-for="option in options" :key="option.candidate.id" type="button" role="option" @click="$emit('select', option)">
          <component :is="optionIcon(option.candidate.id)" :size="17" aria-hidden="true" />
          <span><strong>{{ option.candidate.label }}</strong><small>{{ option.candidate.description }}</small></span>
        </button>
      </div>
    </div>
  </Teleport>
</template>
