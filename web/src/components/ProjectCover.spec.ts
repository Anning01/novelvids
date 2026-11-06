import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProjectCover, { formatCoverTitle, getCoverPalette, COVER_PALETTES } from './ProjectCover.vue'

describe('ProjectCover', () => {
  it.each(['16:9', '9:16', '1:1', '4:3'])('keeps the full %s cover within its display bounds', aspectRatio => {
    const wrapper = mount(ProjectCover, { props: { source: '/media/test.png', aspectRatio, alt: '项目封面' } })
    const element = wrapper.element as HTMLElement
    const [width, height] = aspectRatio.split(':').map(Number) as [number, number]
    expect(parseFloat(element.style.width) / parseFloat(element.style.height)).toBeCloseTo(width / height)
    expect(parseFloat(element.style.width)).toBeLessThanOrEqual(160)
    expect(parseFloat(element.style.height)).toBeLessThanOrEqual(120)
    expect(wrapper.get('img').attributes('alt')).toBe('项目封面')
  })

  it('generates a code-based cover using project name/nickname when source is missing', () => {
    const wrapper = mount(ProjectCover, {
      props: {
        title: '酱板鸭',
        aspectRatio: '16:9',
        seed: 11,
      },
    })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.project-cover__generated').exists()).toBe(true)
    const generated = wrapper.get('.project-cover__generated')
    expect(generated.get('.project-cover__title').text()).toBe('酱板鸭')
    expect(generated.get('.project-cover__watermark').text()).toBe('酱')
    expect(generated.attributes('style')).toContain('linear-gradient')
  })

  it('correctly cleans up brackets and formats long titles into lead & subtitle', () => {
    const res1 = formatCoverTitle('【镜头内容】两位剑客在竹林中相对而立，风吹动衣摆。')
    expect(res1.leadChar).toBe('两')
    expect(res1.displayTitle).toBe('两位剑客在竹林…')
    expect(res1.subText).toBe('风吹动衣摆')

    const res2 = formatCoverTitle('新项目')
    expect(res2.leadChar).toBe('新')
    expect(res2.displayTitle).toBe('新项目')
    expect(res2.subText).toBe('')

    const res3 = formatCoverTitle('《全球高武》1-74')
    expect(res3.leadChar).toBe('全')
    expect(res3.displayTitle).toBe('全球高武')
  })

  it('deterministically selects palettes based on seed', () => {
    const palette1 = getCoverPalette(11)
    const palette2 = getCoverPalette(12)
    const palette1Again = getCoverPalette(11)
    expect(COVER_PALETTES).toContain(palette1)
    expect(COVER_PALETTES).toContain(palette2)
    expect(palette1).toBe(palette1Again)
  })

  it('renders a placeholder icon when defaultCover is explicitly disabled and source is missing', () => {
    const wrapper = mount(ProjectCover, { props: { aspectRatio: '0:0', defaultCover: false } })
    expect(parseFloat((wrapper.element as HTMLElement).style.aspectRatio)).toBeCloseTo(2 / 3)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.project-cover__generated').exists()).toBe(false)
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('falls back to code-generated cover when image fails to load', async () => {
    const wrapper = mount(ProjectCover, {
      props: {
        source: '/broken.png',
        title: '两位剑客',
        seed: 'fail-test',
      },
    })
    expect(wrapper.get('img').attributes('src')).toContain('/broken.png')
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    const generated = wrapper.get('.project-cover__generated')
    expect(generated.get('.project-cover__title').text()).toBe('两位剑客')
  })
})
