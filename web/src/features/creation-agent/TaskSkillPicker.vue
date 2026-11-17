<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import SkillEditorDialog from './SkillEditorDialog.vue'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { skillsApi, type CreativeSkill, type TextTask } from './skillsApi'

const props = defineProps<{ task: TextTask; modelValue?: number; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: number]; 'editing-change': [value: boolean] }>()
const id = useId()
const skills = ref<CreativeSkill[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const status = ref('')
const defaultId = ref(0)
const editor = ref(false)
const copyEditor = ref(false)
const selected = computed(() => skills.value.find(skill => skill.id === props.modelValue))
const title = computed(() => tr({ story: '故事分析技能', screenplay: '剧本改编技能', assets: '资产提取技能', storyboard: '分镜生成技能' }[props.task]))
const options = computed(() => loading.value
  ? [{ value: '', label: tr('正在读取技能…') }]
  : skills.value.filter(skill => skill.is_active).map(skill => ({
    value: String(skill.id),
    label: `${skill.builtin ? tr('内置技能') : skill.name}${skill.id === defaultId.value ? ` · ${tr('默认')}` : ''}`,
  })))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await skillsApi.list(props.task)
    skills.value = data.items
    defaultId.value = data.default_skill_id
    if (props.modelValue === undefined) emit('update:modelValue', data.default_skill_id)
  } catch (caught) { error.value = (caught as Error).message }
  finally { loading.value = false }
}
onMounted(load)
onBeforeUnmount(() => emit('editing-change', false))

function edit(copy = false) {
  copyEditor.value = copy
  editor.value = true
  error.value = ''
  status.value = ''
  emit('editing-change', true)
}
function finishClose() {
  editor.value = false
  emit('editing-change', false)
}
function saved(data: CreativeSkill) {
  skills.value = [...skills.value.filter(skill => skill.id !== data.id), data]
  emit('update:modelValue', data.id)
  status.value = tr('技能已保存，下一次生成时生效')
}

async function setDefault() {
  if (!selected.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    await skillsApi.setDefault(props.task, selected.value.id)
    defaultId.value = selected.value.id
    status.value = tr('已设为我的默认技能')
  } catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}
</script>

<template>
  <div class="task-skill-picker">
    <div class="skill-controls">
      <span :id="`${id}-label`" class="skill-label">{{ title }}</span>
      <AppSelect :model-value="modelValue === undefined ? '' : String(modelValue)" :options="options" :ariaLabel="title" density="compact"
        :disabled="disabled || loading || saving || !!editor || !skills.length"
        @update:model-value="emit('update:modelValue', Number($event))" />
      <AppButton type="button" variant="ghost" size="sm" aria-haspopup="dialog"
        :aria-describedby="`${id}-label`"
        :disabled="disabled || loading || saving || !selected" @click="edit()">
        {{ selected?.builtin ? tr('复制并编辑') : tr('编辑技能') }}
      </AppButton>
      <AppButton v-if="selected && !selected.builtin" type="button" variant="ghost" size="sm" aria-haspopup="dialog"
        :disabled="disabled || saving" @click="edit(true)">{{ tr('另存为新技能') }}</AppButton>
      <AppButton v-if="selected && selected.id !== defaultId" type="button" variant="ghost" size="sm"
        :disabled="disabled || saving || !!editor" @click="setDefault">{{ tr('设为默认') }}</AppButton>
    </div>
    <SkillEditorDialog v-if="editor" :task="task" :source="selected" :copy="copyEditor" :disabled="disabled" @close="finishClose" @saved="saved" />
    <p v-if="error && !editor" class="skill-error" role="alert">{{ error }} <AppButton type="button" variant="ghost" size="sm" :disabled="loading" @click="load">{{ tr('重试') }}</AppButton></p>
    <p v-if="status" role="status">{{ status }}</p>
  </div>
</template>

<style scoped>
.task-skill-picker { box-sizing: border-box; min-width: 0; width: 100%; color: var(--app-text); }
.skill-controls { display: flex; align-items: center; flex-wrap: wrap; gap: .5rem; }
.skill-label { font-size: 11px; color: var(--app-text-secondary); white-space: nowrap; }
.skill-controls > .app-select { min-inline-size: 0; max-inline-size: min(22rem, 100%); }
.skill-error { color: var(--app-danger, #b33645); }
@media (pointer: coarse) { .skill-controls :deep(button) { min-height: 48px; font-size: 1rem; } }
</style>
