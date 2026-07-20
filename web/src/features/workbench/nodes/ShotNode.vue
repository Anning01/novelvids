<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed, ref, watch } from 'vue'
import { LoaderCircle, Play, Save } from 'lucide-vue-next'
import type { EnumItem, Scene } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const scene = computed(() => props.data.scene as Scene)
const options = computed(() => (props.data.modelOptions || []) as EnumItem[])
const description = ref(''); const prompt = ref(''); const duration = ref(6); const model = ref('')
watch(scene, value => { description.value = value.description || ''; prompt.value = value.prompt || ''; duration.value = value.duration || 6 }, { immediate: true })
watch(options, value => { if (!model.value && value.length) model.value = String(value[0].value) }, { immediate: true })
const busy = computed(() => store.busySceneIds.includes(scene.value.id))
</script>
<template><WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'shot', title: `镜头 ${String(scene.sequence).padStart(2, '0')}`, status: busy ? 'running' : 'ready' }"><div class="workbench-node-content"><label class="workbench-field"><span>画面描述</span><textarea v-model="description" rows="2" /></label><label class="workbench-field"><span>生成提示词</span><textarea v-model="prompt" rows="5" /></label><div class="workbench-form-row"><label class="workbench-field"><span>时长（秒）</span><input v-model.number="duration" type="number" min="1" max="30"></label><label class="workbench-field"><span>视频模型</span><select v-model="model"><option v-for="option in options" :key="option.value" :value="String(option.value)">{{ option.label }}</option></select></label></div><div class="workbench-node-actions"><button type="button" @click="store.saveScene(scene.id, { description, prompt, duration })"><Save :size="14" />保存</button><button type="button" class="is-primary" :disabled="busy || !model" @click="store.generateVideo(scene.id, Number(model))"><LoaderCircle v-if="busy" class="workbench-node-context__loading-icon" :size="14" /><Play v-else :size="14" />{{ busy ? '生成中' : '生成视频' }}</button></div></div></WorkbenchNodeFrame></template>
