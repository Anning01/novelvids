<script setup lang="ts">
import type { MaterialMention } from './materialMentionTypes';
import { X } from 'lucide-vue-next';
import { computed, ref } from 'vue';

const props = defineProps<{
  mentions: MaterialMention[];
}>();
const emit = defineEmits<{
  focus: [nodeKey: string];
  remove: [edgeKey: string];
}>();

const hoveredKey = ref('');
const images = computed(() => props.mentions.filter(mention => (
  mention.mode === 'reference_image' && Boolean(mention.previewUrl)
)));

function removeReference(mention: MaterialMention) {
  const connectionKey = mention.connectionKey;
  if (connectionKey)
    emit('remove', connectionKey);
}
</script>

<template>
  <ol v-if="images.length" class="workbench-prompt-references" aria-label="Prompt 参考图片">
    <li
      v-for="(mention, index) in images"
      :key="mention.edgeKey"
      class="workbench-prompt-reference"
      @mouseenter="hoveredKey = mention.edgeKey"
      @mouseleave="hoveredKey = ''"
    >
      <button
        type="button"
        class="workbench-prompt-reference__thumbnail"
        :aria-label="`参考图片 ${index + 1}：${mention.name}，双击聚焦来源节点`"
        @dblclick.stop="emit('focus', mention.nodeKey)"
      >
        <img :src="mention.previewUrl" :alt="mention.name" loading="lazy">
        <span>{{ index + 1 }}</span>
      </button>

      <button
        v-if="hoveredKey === mention.edgeKey && mention.connectionKey"
        type="button"
        class="workbench-prompt-reference__remove"
        :aria-label="`移除参考图片 ${index + 1}：${mention.name}`"
        title="移除参考图片"
        @click.stop="removeReference(mention)"
      >
        <X :size="14" aria-hidden="true" />
      </button>

      <div
        v-if="hoveredKey === mention.edgeKey"
        class="workbench-prompt-reference__preview"
        role="img"
        :aria-label="`${mention.name}大图预览`"
        @dblclick.stop="emit('focus', mention.nodeKey)"
      >
        <img :src="mention.previewUrl" :alt="mention.name">
      </div>
      <span v-if="hoveredKey === mention.edgeKey" class="workbench-prompt-reference__tip">
        双击可聚焦至节点
      </span>
    </li>
  </ol>
</template>
