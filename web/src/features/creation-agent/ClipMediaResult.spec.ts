import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import AppButton from '@/components/AppButton.vue'
import ClipMediaResult from './ClipMediaResult.vue'
import type { BillingRecord } from '@/types'

const props = { kind: 'image' as const, name: '画面参考', aspectRatio: '16:9', resolution: '2K',
  model: 'GPT Image', prompt: '两位剑客在竹林相对而立', createdAt: '2026-11-10T02:00:00Z' }
const record = { id: 1, novel_id: 42, task_type: 2, billing_type: 'image', ai_task_id: 'image-task', model: 'gpt-image-2',
  usage: {}, cost: 0.16, currency: 'CNY', status: 3, created_at: '', updated_at: '', duration_seconds: 32 } as BillingRecord
afterEach(() => { vi.useRealTimers(); delete document.documentElement.dataset.appTheme })

it.each(['light', 'dark'])('shows real queue/generation time, then final metadata and cost (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-11-10T02:00:20Z'))
  const wrapper = mount(ClipMediaResult, { props: { ...props, status: 6, estimatedCost: '0.16' } })
  expect(wrapper.get('.clip-media-result__stage').attributes('aria-busy')).toBe('true')
  expect(wrapper.text()).toContain('排队等待生成')
  expect(wrapper.text()).toContain('20 秒')
  expect(wrapper.text()).toContain('待结算')
  expect(wrapper.text()).not.toContain('%')
  await vi.advanceTimersByTimeAsync(2000)
  expect(wrapper.get('time').text()).toBe('22 秒')
  await wrapper.setProps({ status: 2 })
  expect(wrapper.text()).toContain('图片生成中')
  await wrapper.setProps({ status: 3, src: '/media/generated.png', finishedAt: '2026-11-10T02:00:32Z', records: [record] })
  const image = wrapper.get('img')
  Object.defineProperties(image.element, { naturalWidth: { value: 2816 }, naturalHeight: { value: 1584 } })
  await image.trigger('load')
  expect(wrapper.text()).toContain('2816 × 1584')
  expect(wrapper.text()).toContain('2K · 16:9')
  expect(wrapper.get('time').text()).toBe('32 秒')
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('¥0.1600')
  expect(wrapper.get('details').attributes('open')).toBeDefined()
  expect(wrapper.text()).toContain(props.prompt)
  expect(wrapper.find('.clip-media-result__progress').exists()).toBe(false)
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

it('opens the original image, zooms it, closes with Escape and restores keyboard focus', async () => {
  const wrapper = mount(ClipMediaResult, { attachTo: document.body,
    props: { ...props, src: '/media/original.png', status: 3 }, global: { components: { AppButton }, stubs: { Teleport: true } } })
  const viewer = wrapper.get<HTMLButtonElement>('[aria-label="放大查看当前图片"]')
  viewer.element.focus(); await viewer.trigger('click'); await flushPromises()
  const dialog = wrapper.get('[role="dialog"]')
  expect(dialog.get('img').attributes('src')).toContain('/media/original.png')
  expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭大图')
  await dialog.get('[aria-label="放大图片"]').trigger('click')
  expect(dialog.get('output').text()).toBe('125%')
  await dialog.trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  expect(document.activeElement).toBe(viewer.element)
  wrapper.unmount()
})

it('distinguishes missing, unsettled and explicitly free ledger entries', async () => {
  const wrapper = mount(ClipMediaResult, { props: { ...props, status: 4, error: '供应商拒绝请求', costError: true } })
  expect(wrapper.get('[role="alert"]').text()).toBe('供应商拒绝请求')
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('费用暂未同步')
  await wrapper.setProps({ records: [{ ...record, cost: 0, usage: { missing_usage: true } }] })
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('费用待结算')
  await wrapper.setProps({ records: [{ ...record, cost: 0 }] })
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('¥0')
  await wrapper.setProps({ showCosts: false })
  expect(wrapper.text()).not.toContain('实际费用')
  wrapper.unmount()
})

it('shows video dimensions, runtime and settled generation cost without counting it as an image', async () => {
  const wrapper = mount(ClipMediaResult, { props: { ...props, kind: 'video', src: '/media/result.mp4', status: 3,
    resolution: '1080P', records: [{ ...record, billing_type: 'video', video_id: 81, cost: 2.4 }] } })
  const video = wrapper.get('video')
  Object.defineProperties(video.element, { videoWidth: { value: 1920 }, videoHeight: { value: 1080 }, duration: { value: 5 } })
  await video.trigger('loadedmetadata')
  expect(wrapper.text()).toContain('1920 × 1080')
  expect(wrapper.text()).toContain('5 秒')
  expect(wrapper.text()).toContain('32 秒')
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('¥2.40')
  expect(wrapper.find('[aria-label="放大查看当前图片"]').exists()).toBe(false)
  wrapper.unmount()
})

it('plays the original GIF and identifies an actual PNG fallback honestly', async () => {
  const wrapper = mount(ClipMediaResult, { props:{...props,status:3,src:'/media/animated.gif',requestedFormat:'gif'},
    global:{components:{AppButton},stubs:{Teleport:true}} })
  expect(wrapper.get('img').attributes('src')).toContain('/media/animated.gif')
  expect(wrapper.text()).toContain('文件格式')
  expect(wrapper.findAll('dd').some(item => item.text()==='GIF')).toBe(true)
  expect(wrapper.find('.clip-media-result__format-note').exists()).toBe(false)
  await wrapper.get('[aria-label="放大查看当前图片"]').trigger('click')
  expect(wrapper.get('[role="dialog"] img').attributes('src')).toContain('/media/animated.gif')
  await wrapper.setProps({src:'/media/actually-static.png?signature=test'})
  expect(wrapper.get('.clip-media-result__format-note').text()).toBe('当前文件为 PNG 静态图')
  expect(wrapper.findAll('dd').some(item => item.text()==='PNG')).toBe(true)
  wrapper.unmount()
})
