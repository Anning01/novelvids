<script setup lang="ts">
import { tr } from '@/i18n'

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
const hoveredReference = computed(() => images.value.find(mention => mention.edgeKey === hoveredKey.value));

function removeReference(mention: MaterialMention) {
  const connectionKey = mention.connectionKey;
  if (connectionKey)
    emit('remove', connectionKey);
}

function assetNickname(mention: MaterialMention) {
  return mention.sourceName?.trim() || mention.name;
}
</script>

<template>
  <div
    v-if="images.length"
    class="workbench-prompt-reference-strip"
    @mouseleave="hoveredKey = ''"
  >
    <div class="workbench-prompt-references-viewport nowheel" role="region" :aria-label="tr('Prompt 参考图片')">
      <ol class="workbench-prompt-references">
        <li
          v-for="(mention, index) in images"
          :key="mention.edgeKey"
          class="workbench-prompt-reference"
          @mouseenter="hoveredKey = mention.edgeKey"
          @focusin="hoveredKey = mention.edgeKey"
          @focusout="hoveredKey = ''"
        >
          <button
            type="button"
            class="workbench-prompt-reference__thumbnail"
            :aria-label="tr('参考图片 {p0}：{p1}，双击聚焦来源节点', { p0: index + 1, p1: mention.name })"
            @dblclick.stop="emit('focus', mention.nodeKey)"
            @keydown.enter.prevent="emit('focus', mention.nodeKey)"
          >
            <img :src="mention.previewUrl" :alt="mention.name" loading="lazy">
            <span>{{ index + 1 }}</span>
          </button>

          <button
            v-if="hoveredKey === mention.edgeKey && mention.connectionKey"
            type="button"
            class="workbench-prompt-reference__remove"
            :aria-label="tr('移除参考图片 {p0}：{p1}', { p0: index + 1, p1: mention.name })"
            :title="tr('移除参考图片')"
            @click.stop="removeReference(mention)"
          >
            <X :size="14" aria-hidden="true" />
          </button>
        </li>
      </ol>
    </div>

    <div
      v-if="hoveredReference?.previewUrl"
      class="workbench-prompt-reference__preview"
      role="img"
      :aria-label="tr('{p0}大图预览', { p0: assetNickname(hoveredReference) })"
      @dblclick.stop="emit('focus', hoveredReference.nodeKey)"
    >
      <img :src="hoveredReference.previewUrl" :alt="assetNickname(hoveredReference)">
    </div>
    <span v-if="hoveredReference" class="workbench-prompt-reference__tip">
      <strong>{{ assetNickname(hoveredReference) }}</strong>
      <span>{{ tr('双击可聚焦至节点') }}</span>
    </span>
  </div>
</template>
