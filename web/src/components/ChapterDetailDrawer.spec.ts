import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ChapterDetailDrawer from './ChapterDetailDrawer.vue'

afterEach(() => {
  document.body.innerHTML = ''
  document.body.style.overflow = ''
})

describe('ChapterDetailDrawer', () => {
  it('shows editable chapter details and emits the saved values', async () => {
    const wrapper = mount(ChapterDetailDrawer, {
      props: {
        open: true,
        chapterNumber: 3,
        title: '风雪夜归人',
        content: '原始章节内容',
      },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('[role="dialog"]').text()).toContain('第 3 集 · 章节详情')
    await wrapper.get('input').setValue('新的章节标题')
    await wrapper.get('textarea').setValue('新的章节内容')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('save')).toEqual([[{
      name: '新的章节标题',
      content: '新的章节内容',
    }]])
  })

  it('closes with Escape and locks background scrolling while open', async () => {
    const wrapper = mount(ChapterDetailDrawer, {
      props: { open: true, chapterNumber: 1, title: '章节', content: '' },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    })

    expect(document.body.style.overflow).toBe('hidden')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
