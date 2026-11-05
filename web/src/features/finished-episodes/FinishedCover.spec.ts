import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { fetchFileBlob } from '@/shared/downloadFile'
import FinishedCover from './FinishedCover.vue'

vi.mock('@/shared/downloadFile',()=>({fetchFileBlob:vi.fn()}))
afterEach(()=>vi.unstubAllGlobals())
it('loads the saved cover with credentials and releases the image when it unmounts',async()=>{
  const create=vi.fn().mockReturnValue('blob:cover'),revoke=vi.fn()
  vi.stubGlobal('URL',class extends URL {static createObjectURL=create;static revokeObjectURL=revoke})
  vi.mocked(fetchFileBlob).mockResolvedValue(new Blob(['cover'],{type:'image/jpeg'}))
  const wrapper=mount(FinishedCover,{props:{versionId:7}});await flushPromises()
  expect(fetchFileBlob).toHaveBeenCalledWith(expect.stringContaining('/versions/7/cover'),expect.any(Object))
  expect(wrapper.get('img').attributes('src')).toBe('blob:cover')
  wrapper.unmount()
  expect(revoke).toHaveBeenCalledWith('blob:cover')
})
