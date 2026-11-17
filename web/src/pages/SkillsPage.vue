<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { LayoutGrid, List, Plus, Search, SlidersHorizontal } from 'lucide-vue-next'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import SkillEditorDialog from '@/features/creation-agent/SkillEditorDialog.vue'
import SkillRowActions from '@/features/creation-agent/SkillRowActions.vue'
import { skillsApi, type CreativeSkill, type TextTask } from '@/features/creation-agent/skillsApi'

const id = useId()
const tasks: { value: TextTask; label: string }[] = [{ value: 'story', label: '故事分析' }, { value: 'screenplay', label: '剧本改编' }, { value: 'assets', label: '资产提取' }, { value: 'storyboard', label: '分镜生成' }]
const task = ref<TextTask>('story')
const skills = ref<CreativeSkill[]>([])
const defaultId = ref(0)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const status = ref('')
const search = ref('')
const source = ref('all')
const view = ref<'table' | 'cards'>('table')
const editing = ref(false)
const selected = ref<CreativeSkill>()
let loadVersion = 0
const filters = computed(() => [{ value: 'all', label: tr('全部来源') }, { value: 'builtin', label: tr('内置技能') }, { value: 'mine', label: tr('我的技能') }])
const visible = computed(() => skills.value.filter(skill =>
  (source.value === 'all' || (source.value === 'builtin' ? skill.builtin : !skill.builtin)) &&
  `${skill.name} ${skill.description}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))

async function load() {
  const version = ++loadVersion
  loading.value = true; error.value = ''; skills.value = []
  try {
    const { data } = await skillsApi.list(task.value)
    if (version !== loadVersion) return
    skills.value = data.items; defaultId.value = data.default_skill_id
  } catch (caught) { if (version === loadVersion) error.value = (caught as Error).message }
  finally { if (version === loadVersion) loading.value = false }
}
watch(task, () => { status.value = ''; search.value = ''; void load() }, { immediate: true })
function edit(skill?: CreativeSkill) { selected.value = skill; editing.value = true; status.value = '' }
function saved(skill: CreativeSkill) {
  skills.value = [...skills.value.filter(item => item.id !== skill.id), skill]
  status.value = tr('技能已保存，下一次生成时生效')
}
async function setDefault(skill: CreativeSkill) {
  busy.value = true; error.value = ''
  try { await skillsApi.setDefault(task.value, skill.id); defaultId.value = skill.id; status.value = tr('已设为我的默认技能') }
  catch (caught) { error.value = (caught as Error).message }
  finally { busy.value = false }
}
async function toggle(skill: CreativeSkill) {
  busy.value = true; error.value = ''
  const { id: skillId, builtin: _builtin, version, ...body } = skill
  try {
    const { data } = await skillsApi.update(skillId, { ...body, is_active: !skill.is_active }, version ?? 1)
    skills.value = skills.value.map(item => item.id === data.id ? data : item)
    if (!data.is_active && defaultId.value === data.id) defaultId.value = 0
    status.value = data.is_active ? tr('技能已启用') : tr('技能已停用')
  } catch (caught) { error.value = (caught as Error).message }
  finally { busy.value = false }
}
</script>

<template>
  <main class="skills-page">
    <header class="skills-page-header">
      <div><h1>{{ tr('技能管理') }}</h1><p>{{ tr('整理你的创作方法，调试后用于每一次生成。') }}</p></div>
      <AppButton type="button" variant="primary" aria-haspopup="dialog" @click="edit()"><Plus :size="17" />{{ tr('新建技能') }}</AppButton>
    </header>
    <div class="task-tabs" role="group" :aria-label="tr('技能分类')">
      <button v-for="item in tasks" :key="item.value" type="button" :aria-pressed="task === item.value" :disabled="busy" @click="task = item.value">{{ tr(item.label) }}</button>
    </div>
    <section class="skills-library" :aria-labelledby="`${id}-list`">
      <div class="library-toolbar">
        <h2 :id="`${id}-list`">{{ tr(tasks.find(item => item.value === task)!.label) }}<span>{{ skills.length }}</span></h2>
        <div class="library-filters">
          <label class="skill-search"><Search :size="16" aria-hidden="true" /><input v-model="search" type="search" :aria-label="tr('搜索技能')" :placeholder="tr('搜索技能名称或说明')" /></label>
          <AppSelect v-model="source" :options="filters" :ariaLabel="tr('技能来源')" />
          <div class="view-switch" role="group" :aria-label="tr('显示方式')">
            <AppButton type="button" variant="ghost" icon-only :aria-label="tr('表格视图')" :aria-pressed="view === 'table'" @click="view = 'table'"><List :size="17" /></AppButton>
            <AppButton type="button" variant="ghost" icon-only :aria-label="tr('卡片视图')" :aria-pressed="view === 'cards'" @click="view = 'cards'"><LayoutGrid :size="17" /></AppButton>
          </div>
        </div>
      </div>
      <p v-if="error" class="library-error" role="alert">{{ error }} <AppButton type="button" variant="ghost" size="sm" @click="load">{{ tr('重新加载') }}</AppButton></p>
      <p v-if="status" class="library-status" role="status">{{ status }}</p>
      <div v-if="loading" class="library-empty" role="status">{{ tr('正在读取技能…') }}</div>
      <div v-else-if="!visible.length" class="library-empty"><SlidersHorizontal :size="28" aria-hidden="true" /><h3>{{ tr('没有匹配的技能') }}</h3><p>{{ tr('换个关键词或来源筛选，也可以新建技能。') }}</p></div>
      <div v-else-if="view === 'table'" class="skills-table" tabindex="0" role="region" :aria-labelledby="`${id}-list`">
        <table>
          <thead><tr><th scope="col">{{ tr('技能名称') }}</th><th scope="col">{{ tr('来源') }}</th><th scope="col">{{ tr('状态') }}</th><th scope="col">{{ tr('操作') }}</th></tr></thead>
          <tbody><tr v-for="skill in visible" :key="skill.id">
            <th scope="row"><div class="skill-name">{{ skill.name }}<span v-if="skill.id === defaultId" class="default-tag">{{ tr('默认') }}</span></div><p>{{ skill.description || tr('暂无说明') }}</p></th>
            <td>{{ skill.builtin ? tr('内置') : tr('我的技能') }}</td>
            <td><span class="skill-state" :class="{ inactive: !skill.is_active }">{{ skill.is_active ? tr('已启用') : tr('已停用') }}</span></td>
            <td><SkillRowActions :skill="skill" :default-id="defaultId" :busy="busy" @edit="edit(skill)" @default="setDefault(skill)" @toggle="toggle(skill)" /></td>
          </tr></tbody>
        </table>
      </div>
      <ul v-else class="skills-cards">
        <li v-for="skill in visible" :key="skill.id">
          <div class="card-meta"><span>{{ skill.builtin ? tr('内置') : tr('我的技能') }}</span><span v-if="skill.id === defaultId" class="default-tag">{{ tr('默认') }}</span><span v-else class="skill-state" :class="{ inactive: !skill.is_active }">{{ skill.is_active ? tr('已启用') : tr('已停用') }}</span></div>
          <h3>{{ skill.name }}</h3><p>{{ skill.description || tr('暂无说明') }}</p>
          <SkillRowActions :skill="skill" :default-id="defaultId" :busy="busy" @edit="edit(skill)" @default="setDefault(skill)" @toggle="toggle(skill)" />
        </li>
      </ul>
    </section>
    <SkillEditorDialog v-if="editing" :task="task" :source="selected" @close="editing = false" @saved="saved" />
  </main>
</template>

<style scoped>
.skills-page { box-sizing: border-box; max-inline-size: 1480px; margin-inline: auto; padding: 40px clamp(20px, 4vw, 56px); color: var(--app-text); }
.skills-page-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-block-end: 32px; }
h1 { margin: 0; color: var(--app-text); font-size: 28px; line-height: 1.4; } p { margin: 8px 0 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.6; }
.task-tabs { display: flex; gap: 28px; border-block-end: 1px solid var(--app-border); overflow-x: auto; margin-block-end: 28px; }
.task-tabs button { flex: none; border: 0; border-block-end: 2px solid transparent; padding: 12px 2px 14px; color: var(--app-text-secondary); background: transparent; cursor: pointer; font: inherit; font-size: 14px; }
.task-tabs button[aria-pressed="true"] { color: var(--app-accent); border-block-end-color: var(--app-accent); font-weight: 600; }
.task-tabs button:hover { color: var(--app-text); }
button:focus-visible, input:focus-visible, .skills-table:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
.library-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; margin-block-end: 18px; }
h2 { display: flex; align-items: center; gap: 10px; font-size: 17px; margin: 0; }
h2 > span { font-size: 12px; font-weight: 400; color: var(--app-text-secondary); font-variant-numeric: tabular-nums; }
.library-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.skill-search { display: flex; align-items: center; gap: 8px; color: var(--app-text-secondary); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 8px; padding: 0 12px; }
.skill-search input { inline-size: 200px; min-inline-size: 0; block-size: 36px; color: var(--app-text); background: transparent; border: 0; font: inherit; font-size: 13px; caret-color: var(--app-accent); }
.skill-search:focus-within { outline: 2px solid var(--app-accent); outline-offset: 2px; } .skill-search input:focus-visible { outline: none; }
.view-switch { display: flex; gap: 2px; padding: 2px; border: 1px solid var(--app-border); border-radius: 8px; }
.view-switch [aria-pressed="true"] { color: var(--app-accent); background: var(--app-accent-soft); }
.skills-table { overflow: auto; border: 1px solid var(--app-border); border-radius: 12px; max-block-size: 70dvh; scrollbar-width: thin; scrollbar-color: var(--app-border-strong) transparent; }
table { inline-size: 100%; min-inline-size: 720px; border-collapse: separate; border-spacing: 0; text-align: start; font-size: 13px; }
thead { position: sticky; inset-block-start: 0; z-index: 2; } thead th { color: var(--app-text-secondary); font-size: 12px; font-weight: 500; background: var(--app-surface-muted); }
th, td { text-align: start; padding: 18px 20px; border-block-end: 1px solid var(--app-border); } tbody tr:last-child > * { border-block-end: 0; }
tbody th { inline-size: 40%; position: sticky; inset-inline-start: 0; background: var(--app-surface); z-index: 1; font-weight: 500; }
tbody td { background: var(--app-surface); } tbody tr:hover > * { background: var(--app-surface-hover); }
tbody th p { margin-block-start: 6px; font-weight: 400; max-inline-size: 56ch; overflow-wrap: anywhere; }
.skill-name { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
.default-tag { display: inline-block; color: var(--app-accent); background: var(--app-accent-soft); font-size: 11px; border-radius: 4px; padding: 2px 7px; font-weight: 500; white-space: nowrap; }
.skill-state { font-size: 12px; color: var(--app-text-secondary); white-space: nowrap; } .skill-state.inactive { color: var(--app-text-muted); }
.skills-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr)); gap: 16px; padding: 0; margin: 0; list-style: none; }
.skills-cards > li { display: flex; flex-direction: column; min-inline-size: 0; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface); padding: 20px; }
.card-meta { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--app-text-secondary); } .card-meta > :last-child { margin-inline-start: auto; }
.skills-cards h3 { font-size: 16px; margin: 18px 0 0; overflow-wrap: anywhere; } .skills-cards p { flex: 1; margin-block-end: 24px; overflow-wrap: anywhere; }
.skills-cards :deep(.skill-row-actions) { margin-inline-start: -10px; }
.library-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; min-block-size: 320px; color: var(--app-text-secondary); border: 1px dashed var(--app-border); border-radius: 12px; }
.library-empty h3 { font-size: 16px; color: var(--app-text); margin-block-end: 0; }
.library-error { color: var(--app-danger, #b33645); margin-block: 12px; } .library-status { margin-block: 12px; }
@media (max-width: 650px) { .skills-page { padding: 24px 16px; } h1 { font-size: 24px; } .skills-page-header { align-items: flex-start; } .skills-page-header p { max-inline-size: 22ch; } .task-tabs { gap: 22px; } .library-filters { inline-size: 100%; } .skill-search { flex: 1; } .skill-search input { inline-size: 100%; } }
@media (pointer: coarse) { .skills-page :deep(button), .skill-search { min-block-size: 44px; } .skill-search input { font-size: 16px; } }
</style>
