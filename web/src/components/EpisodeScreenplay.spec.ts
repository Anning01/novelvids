import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import EpisodeScreenplay from './EpisodeScreenplay.vue'

it('presents scene navigation, metadata, action and verbatim dialogue', async () => {
  const scroll = vi.fn()
  const wrapper = mount(EpisodeScreenplay, { attachTo: document.body, props: {
    episodeName: '救人', episodeNumber: 1,
    text: '# 书名\n## 第1集　救人\n**1-1　村路　外　黄昏**\n出场：长寿\n△ 他停下。\n长寿（OS）：是他吗？\n**1-2　牛棚　内　薄暮**\n仅声音：王许氏\n王许氏（画外）：开饭了！',
  } })
  try {
    expect(wrapper.findAll('.scene-heading')).toHaveLength(2)
    expect(wrapper.findAll('.title').map(p => p.text())).toEqual(['书名'])
    expect(wrapper.get('.note').text()).toBe('出场：长寿')
    expect(wrapper.get('.action').text()).toBe('△他停下。')
    expect(wrapper.findAll('.dialogue').map(p => p.text())).toEqual(['长寿（OS）：是他吗？', '王许氏（画外）：开饭了！'])
    const target = wrapper.findAll<HTMLElement>('.scene-heading')[1]!
    Object.defineProperty(target.element, 'scrollIntoView', {value: scroll})
    await wrapper.findAll('.scene-index button')[1]!.trigger('click')
    expect(document.activeElement).toBe(target.element)
    expect(scroll).toHaveBeenCalledOnce()
  } finally { wrapper.unmount() }
})

it('retains prose and a distinct title when a script has no numbered scenes', () => {
  const wrapper = mount(EpisodeScreenplay, {props: {text: '## 未命名旅途\n他从窗边起身。'}})
  expect(wrapper.text()).toContain('未命名旅途')
  expect(wrapper.text()).toContain('他从窗边起身。')
  expect(wrapper.find('nav').exists()).toBe(false)
  wrapper.unmount()
})
