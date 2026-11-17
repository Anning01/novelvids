import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AgentRecoveryDetails from './AgentRecoveryDetails.vue'

vi.mock('@/i18n', () => ({ tr: (value: string) => value }))

const recovery = {
  failure_step: null, error_code: null, reusable_count: 0,
  pending_count: 0, responses_saved: 0, can_resume: false,
}

describe('failure step display', () => {
  it.each([null, 'unrecognized'])('does not invent a content check for %s', (failure_step) => {
    const wrapper = mount(AgentRecoveryDetails, {
      props: { recovery: { ...recovery, failure_step }, failed: true, disabled: false },
    })
    expect(wrapper.find('.agent-recovery').exists()).toBe(false)
  })

  it('keeps a recorded failure step', () => {
    const wrapper = mount(AgentRecoveryDetails, {
      props: { recovery: { ...recovery, failure_step: 'assets' }, failed: true, disabled: false },
    })
    expect(wrapper.text()).toContain('未完成步骤：资产提取')
  })
})
