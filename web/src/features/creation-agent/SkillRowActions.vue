<script setup lang="ts">
import AppButton from '@/components/AppButton.vue'
import { tr } from '@/i18n'
import type { CreativeSkill } from './skillsApi'
defineProps<{ skill: CreativeSkill; defaultId: number; busy: boolean }>()
defineEmits<{ edit: []; default: []; toggle: [] }>()
</script>
<template>
  <div class="skill-row-actions">
    <AppButton type="button" variant="ghost" size="sm" :disabled="busy" aria-haspopup="dialog" @click="$emit('edit')">{{ skill.builtin ? tr('复制并编辑') : tr('编辑与调试') }}</AppButton>
    <AppButton v-if="skill.is_active && skill.id !== defaultId" type="button" variant="ghost" size="sm" :disabled="busy" @click="$emit('default')">{{ tr('设为默认') }}</AppButton>
    <AppButton v-if="!skill.builtin" type="button" variant="ghost" size="sm" :disabled="busy" @click="$emit('toggle')">{{ skill.is_active ? tr('停用') : tr('启用') }}</AppButton>
  </div>
</template>
<style scoped>
.skill-row-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
</style>
