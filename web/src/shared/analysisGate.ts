import { TaskStatusEnum } from '@/types'

export type AnalysisGateAction = 'generate' | 'wait' | 'failed'

/**
 * 项目分析状态 → 分镜页行为：
 * - 已保存的故事分析（即使封面失败）/ 分析完成 / 从未发起过分析 → 直接生成分镜（generate）
 * - 分析进行中 → 等待，完成后自动生成（wait）
 * - 分析失败/取消 → 报错，提示回到剧本页重试（failed）
 */
export function analysisGate(status: number | undefined, analysisCompleted = false): AnalysisGateAction {
  if (analysisCompleted) return 'generate'
  if (status === undefined) return 'generate'
  if (status === TaskStatusEnum.COMPLETED) return 'generate'
  if (status === TaskStatusEnum.FAILED || status === TaskStatusEnum.CANCELLED) return 'failed'
  return 'wait'
}
