import { api, retryableStatusError } from '@/api'
import { tr } from '@/i18n'
import { TaskStatusEnum, type Scene, type VideoGenerationModel } from '@/types'
import { pollUntilTerminal } from '@/features/workbench/execution/workbenchAsync'
import { bindBlocking, unbindBlocking } from './sceneBlockingReference'
import { bindSheet, sheetReference, unbindSheet } from './storyboardSheetReference'

export type ModelPromptVersions = Record<string, {prompt: string; input: string}>
export type OptimizationFacts = Omit<Parameters<typeof api.optimizeScenePrompt>[1], 'model_config_id'>
const terminalTaskStatuses = new Set([TaskStatusEnum.COMPLETED, TaskStatusEnum.CANCELLED, TaskStatusEnum.FAILED])

export function boundPrompt(prompt: string, scene: Scene, model: string, sheetExcluded: boolean) {
  const text = !sheetExcluded && sheetReference(scene) ? bindSheet(prompt, scene, model) : prompt
  return bindBlocking(text, scene, model)
}

export function plainPrompt(prompt: string, scene: Scene) {
  return unbindBlocking(unbindSheet(prompt, scene), scene)
}

function importedDrafts(scene: Scene): Record<string, unknown> {
  const work = scene.metadata?.work_package as { drafts?: Record<string, unknown> } | undefined
  return work?.drafts || {}
}

export function genericPrompt(scene: Scene): string {
  const work = scene.metadata?.work_package as {prompt?: string} | undefined
  const value = scene.metadata?.generic_video_prompt ?? scene.prompt_params?.generic_prompt ?? importedDrafts(scene).general ?? work?.prompt
  return typeof value === 'string' ? value : ''
}

export function modelPromptTexts(scene: Scene) {
  const drafts = new Map<string, string>()
  for (const [model, text] of Object.entries(importedDrafts(scene))) {
    if (model !== 'general' && model !== 'eight_columns' && typeof text === 'string' && text.trim()) drafts.set(model, text)
  }
  const generated = scene.prompt_params?.model_optimized_prompt as {model_type?: string; prompt?: string} | undefined
  if (generated?.model_type && generated.prompt) {
    drafts.set(generated.model_type, generated.prompt)
  }
  return drafts
}

export async function resolveModelPrompt(scene: Scene, model: VideoGenerationModel, facts: OptimizationFacts,
  versions: ModelPromptVersions, signal: AbortSignal): Promise<string> {
  const input = JSON.stringify(facts)
  const cached = versions[model.model_type]
  const importedBase = scene.prompt_params?.generic_prompt ?? importedDrafts(scene).general ??
    (scene.metadata?.work_package as {prompt?: string} | undefined)?.prompt
  let optimized = cached?.input === input ? cached.prompt : undefined
  if (!cached && typeof importedBase === 'string' && plainPrompt(importedBase, scene) === facts.generic_prompt) {
    optimized = modelPromptTexts(scene).get(model.model_type)
  }
  if (optimized) {
    const markers = [...facts.generic_prompt.matchAll(/@\{([^{}]+)\}/g)]
      .filter(match => !match[1]!.includes(':') && !/^(?:参考图|图片|图|视频|音频)\d+$/.test(match[1]!))
    if (markers.some(match => !optimized!.includes(match[0]))) optimized = undefined
  }
  if (!optimized) {
    const {data: task} = await api.optimizeScenePrompt(scene.id, {model_config_id: model.config_id, ...facts})
    const result = terminalTaskStatuses.has(task.status) ? task : await pollUntilTerminal(
      async signal => (await api.task(task.id, signal)).data,
      { signal, intervalMs: 1500, terminalStatuses: terminalTaskStatuses, requestTimeoutMs: 45_000, retryOnError: retryableStatusError })
    if (result.status !== TaskStatusEnum.COMPLETED) throw new Error(result.error_message || tr('提示词优化失败'))
    const text = result.response_data?.prompt
    if (typeof text !== 'string' || !text.trim() || result.response_data?.model_type !== model.model_type ||
        result.response_data?.scene_id !== scene.id) throw new Error(tr('模型未返回本镜头的提示词'))
    optimized = text
  }
  return optimized
}
