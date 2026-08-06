import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import type { AudioReference, DigitalHuman, PaginationResponse } from '@/types'
import MediaLibraryPicker from './MediaLibraryPicker.vue'

vi.mock('@/api', () => ({
  api: {
    audioReferences: vi.fn(),
    digitalHumans: vi.fn(),
  },
}))

const audioReferencesMock = vi.mocked(api.audioReferences)
const digitalHumansMock = vi.mocked(api.digitalHumans)
const audioItem = (assetId: string): AudioReference => ({
  id: assetId === 'one' ? 1 : 2,
  nickname: assetId,
  gender: '女',
  audio_url: `/media/${assetId}.mp3`,
  avatar_url: `/media/${assetId}.png`,
  asset_id: assetId,
  is_active: true,
  created_at: '2026-07-25T00:00:00.000Z',
  updated_at: '2026-07-25T00:00:00.000Z',
})
const pageOf = (assetIds: string[]): PaginationResponse<AudioReference> => ({
  code: 0,
  message: 'ok',
  data: {
    items: assetIds.map(audioItem),
    pagination: { total: assetIds.length, page: 1, page_size: 24, pages: 1 },
  },
})

const digitalHumanPage: PaginationResponse<DigitalHuman> = {
  code: 0,
  message: 'ok',
  data: {
    items: [{
      id: 1,
      country: '中国',
      age: 24,
      gender: '女',
      occupation: '模特',
      asset_id: 'human-one',
      image_url: '/media/human-one.png',
      is_active: true,
      created_at: '2026-07-25T00:00:00.000Z',
      updated_at: '2026-07-25T00:00:00.000Z',
    }],
    pagination: { total: 1, page: 1, page_size: 24, pages: 1 },
  },
}

it('renders the picker close control as a full-size icon button', async () => {
  digitalHumansMock.mockResolvedValueOnce(digitalHumanPage)
  const wrapper = mount(MediaLibraryPicker, {
    attachTo: document.body,
    props: { open: true, kind: 'digital-human' },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  const close = wrapper.get('[aria-label="关闭"]')
  expect(close.classes()).toContain('is-icon-only')
  expect(close.classes()).toContain('app-button--sm')
  expect(close.get('svg').attributes()).toMatchObject({ width: '20', height: '20' })
  wrapper.unmount()
})

it('reloads the full first page after clearing a pending search', async () => {
  let resolvePendingSearch!: (value: PaginationResponse<AudioReference>) => void
  audioReferencesMock
    .mockResolvedValueOnce(pageOf(['one']))
    .mockImplementationOnce(() => new Promise(resolve => { resolvePendingSearch = resolve }))
    .mockResolvedValueOnce(pageOf(['one', 'two']))
  const wrapper = mount(MediaLibraryPicker, {
    attachTo: document.body,
    props: { open: true, kind: 'audio' },
    global: { stubs: { Teleport: true, AppButton: { template: '<button><slot /></button>' } } },
  })
  await flushPromises()

  await wrapper.get('input').setValue('one')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(audioReferencesMock).toHaveBeenCalledTimes(2)

  await wrapper.get('input').setValue('')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  resolvePendingSearch(pageOf(['one']))
  await flushPromises()

  expect(audioReferencesMock).toHaveBeenCalledTimes(3)
  expect(wrapper.findAll('.media-picker-grid > button')).toHaveLength(2)
  wrapper.unmount()
})
