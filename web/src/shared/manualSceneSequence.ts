import type { Scene } from '@/types'

/** 人工模式下一个分镜的序号：现有最大序号 + 1；无分镜时为 1。 */
export function nextManualSceneSequence(scenes: Scene[]): number {
  const max = scenes.reduce((acc, scene) => Math.max(acc, scene.sequence || 0), 0)
  return max + 1
}
