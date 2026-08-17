import { describe, expect, it } from 'vitest'
import { TaskStatusEnum } from '@/types'
import { analysisGate } from './analysisGate'

describe('analysisGate', () => {
  it('分析完成或从未分析 → 直接生成', () => {
    expect(analysisGate(undefined)).toBe('generate')
    expect(analysisGate(TaskStatusEnum.COMPLETED)).toBe('generate')
  })
  it('分析进行中 → 等待', () => {
    expect(analysisGate(TaskStatusEnum.PENDING)).toBe('wait')
    expect(analysisGate(TaskStatusEnum.PROCESSING)).toBe('wait')
    expect(analysisGate(TaskStatusEnum.QUEUED)).toBe('wait')
  })
  it('分析失败/取消 → 报错', () => {
    expect(analysisGate(TaskStatusEnum.FAILED)).toBe('failed')
    expect(analysisGate(TaskStatusEnum.CANCELLED)).toBe('failed')
  })
})
