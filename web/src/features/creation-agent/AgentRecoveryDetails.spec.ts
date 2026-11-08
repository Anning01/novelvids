import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { setLocale } from '@/i18n'
import AgentRecoveryDetails from './AgentRecoveryDetails.vue'

describe.each(['light', 'dark'])('recovery details in %s theme', theme => {
  it('shows the actual failed step and retained candidates, and prevents duplicate resume', async () => {
    setLocale('zh')
    document.documentElement.dataset.appTheme = theme
    const wrapper = mount(AgentRecoveryDetails, { props: { failed: true, disabled: false, recovery: {
      failure_step: 'assets', error_code: 'CREATION_JSON_INVALID', reusable_count: 9, pending_count: 1,
      responses_saved: 2, can_resume: true,
    } } })
    expect(wrapper.text()).toContain('资产提取')
    expect(wrapper.text()).toContain('9 项合格候选，待修正 1 项')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('resume')).toHaveLength(1)
    await wrapper.setProps({ disabled: true })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('resume')).toHaveLength(1)
    await wrapper.setProps({ recovery: { ...wrapper.props('recovery'), can_resume: false } })
    expect(wrapper.find('button').exists()).toBe(false)
    await wrapper.setProps({ failed: false, recovery: { ...wrapper.props('recovery'), pending_count: 0 } })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
  })
})
