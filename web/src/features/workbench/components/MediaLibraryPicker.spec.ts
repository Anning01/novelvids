import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { AudioReference, PaginationResponse } from '@/types'
import MediaLibraryPicker from './MediaLibraryPicker.vue'

vi.mock('@/api', () => ({
  api: {
    audioReferences: vi.fn(),
    digitalHumans: vi.fn(),
  },
}))

const audioReferencesMock = vi.mocked(api.audioReferences)
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
