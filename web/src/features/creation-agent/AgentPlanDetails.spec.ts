import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentPlanDetails from './AgentPlanDetails.vue'
import type { PendingProduction } from './types'

const plan: PendingProduction = {
  confirmation_request_id: 'confirm', message: '确认执行创作方案',
  plan_confirmation: { task_id: 'source', revision: 'a'.repeat(64) },
  summary: '以第八章城门崩塌开场，再切回收到来信。',
  read_chapters: ['1 · 来信', '8 · 城门'],
  labels: [
    { operation: 'storyboard', target_label: '第一章', mode: 'revise', instructions: '救援前切回收到来信，保留悬念。' },
    { operation: 'image', target_label: '城门', mode: 'fill_missing', instructions: '保留已有参考图。' },
  ], intents: [], chapter_id: 1, targets: [], write_scope: 'chapter', model_config_id: 1,
}

describe.each(['light', 'dark'])('creation plan in %s theme', theme => {
  it('separates reading, changes and preservation with keyboard-accessible disclosures', () => {
    document.documentElement.dataset.appTheme = theme
    const wrapper = mount(AgentPlanDetails, { props: { plan }, attachTo: document.body })
    expect(wrapper.get('[aria-label="创作方案"]').text()).toContain('第八章城门崩塌')
    expect(wrapper.text()).toContain('调整已有内容')
    expect(wrapper.text()).toContain('保留已有，补齐缺失')
    const disclosure = wrapper.get('summary')
    ;(disclosure.element as HTMLElement).focus()
    expect(document.activeElement).toBe(disclosure.element)
    expect(wrapper.findAll('summary')).toHaveLength(3)
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
  })

  it('handles a simple plan without empty reading or instructions placeholders', () => {
    const wrapper = mount(AgentPlanDetails, { props: { plan: { ...plan, read_chapters: [], labels: [] } } })
    expect(wrapper.find('details').exists()).toBe(false)
    expect(wrapper.text()).toBe(plan.summary)
  })
})
