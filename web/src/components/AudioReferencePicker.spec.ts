import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import AudioReferencePicker from './AudioReferencePicker.vue'
import type { AudioReference } from '@/types'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      audioReferences: vi.fn(),
      uploadAudioReference: vi.fn(),
      trimAudioReference: vi.fn(),
    },
  }
})

const voice: AudioReference = {
  id: 9,
  nickname: '羽宁参考音色',
  gender: '女',
  audio_url: '/media/audio-references/yuning.wav',
  avatar_url: '',
  asset_id: 'upload-yuning',
  source: 'upload',
  duration: 4.5,
  is_active: true,
  created_at: '',
  updated_at: '',
}

function mountPicker(startInUpload = false, novelId?: number) {
  return mount(AudioReferencePicker, {
    props: { open: true, startInUpload, novelId },
    global: {
      components: { AppButton },
      stubs: { Teleport: true },
    },
  })
}

describe('AudioReferencePicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.audioReferences).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        items: [voice],
        pagination: { total: 1, page: 1, page_size: 24, pages: 1 },
      },
    })
  })

  it('加载音频库并返回选中的音色', async () => {
    const wrapper = mountPicker(false, 17)
    await flushPromises()

    expect(api.audioReferences).toHaveBeenCalledWith(1, '', {}, 17)
    expect(wrapper.text()).toContain('羽宁参考音色')
    expect(wrapper.text()).toContain('0:04.5')
    expect(wrapper.get('.audio-picker__list').attributes()).toMatchObject({
      tabindex: '0',
      'aria-label': '音色列表，可滚动浏览',
      'aria-busy': 'false',
    })
    await wrapper.get('.audio-picker__item-main').trigger('click')
    expect(wrapper.emitted('choose')?.[0]).toEqual([voice])
  })

  it('从音频库入口直接打开上传表单并选择上传结果', async () => {
    vi.mocked(api.uploadAudioReference).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: voice,
    })
    const wrapper = mountPicker(true, 17)
    await flushPromises()
    const file = new File([new Uint8Array([1, 2, 3])], 'yuning.WAV', { type: 'audio/wav' })
    const input = wrapper.get<HTMLInputElement>('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.uploadAudioReference).toHaveBeenCalledWith(file, 'yuning', '未设置', 17)
    expect(wrapper.emitted('choose')?.[0]).toEqual([voice])
  })

  it('用户上传音色可裁剪为新副本并保留原音色', async () => {
    const clipped = { ...voice, id: 10, nickname: '羽宁参考音色 · 裁剪', duration: 2.5 }
    vi.mocked(api.trimAudioReference).mockResolvedValue({ code: 0, message: 'ok', data: clipped })
    const wrapper = mountPicker(false, 17)
    await flushPromises()

    await wrapper.get('button[aria-label="裁剪羽宁参考音色"]').trigger('click')
    expect(wrapper.text()).toContain('裁剪音色副本')
    expect(wrapper.find('.audio-picker__existing-trim input[type="number"]').exists()).toBe(false)
    const inputs = wrapper.findAll<HTMLInputElement>('.audio-picker__existing-trim input[type="range"]')
    expect(inputs).toHaveLength(2)
    expect(inputs[0]!.attributes('aria-label')).toBe('裁剪开始时间')
    expect(inputs[1]!.attributes('aria-label')).toBe('裁剪结束时间')
    await inputs[0]!.setValue('1')
    await wrapper.findAll<HTMLInputElement>('.audio-picker__existing-trim input[type="range"]')[1]!.setValue('3.5')
    expect(wrapper.text()).toContain('已选 2.5s')
    await wrapper.get('.audio-picker__existing-trim footer button').trigger('click')
    await flushPromises()

    expect(api.trimAudioReference).toHaveBeenCalledWith(9, 1, 3.5, 17)
    expect(wrapper.emitted('choose')?.at(-1)).toEqual([clipped])
  })
})
