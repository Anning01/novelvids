import { beforeEach, expect, it, vi } from 'vitest'
import { authHeaders, request, uploadWithProgress } from '@/api'
import { libraryApi } from './api'

vi.mock('@/api', () => ({
  API_BASE: '/api', authHeaders: vi.fn(), request: vi.fn(), uploadWithProgress: vi.fn(),
}))
beforeEach(() => { vi.resetAllMocks(); vi.mocked(authHeaders).mockReturnValue({ 'X-Team-Id': '1' }) })

it('keeps the original team and folder through direct upload and finalization', async () => {
  vi.mocked(request).mockResolvedValueOnce({ data: { direct: true, resource_id: 4, upload_url: 'https://storage.invalid', fields: { key: 'uploads/1/key.mp4' } } })
    .mockResolvedValueOnce({ data: { id: 4, name: 'clip' } })
  vi.mocked(uploadWithProgress).mockImplementation(async () => {
    vi.mocked(authHeaders).mockReturnValue({ 'X-Team-Id': '2' })
    return { status: 204, text: '' }
  })
  await libraryApi.upload(new File(['clip'], 'clip.mp4'), 12)
  expect(request).toHaveBeenNthCalledWith(1, '/resource-library/upload-policy?source=false', expect.objectContaining({
    headers: { 'X-Team-Id': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: 'clip.mp4', folder_id: 12 }),
  }))
  expect(request).toHaveBeenNthCalledWith(2, '/resource-library/resources/4/finalize', expect.objectContaining({ headers: { 'X-Team-Id': '1', 'Content-Type': 'application/json' } }))
})

it('cancels the reserved ticket if storage upload fails', async () => {
  vi.mocked(request).mockResolvedValueOnce({ data: { direct: true, resource_id: 9, upload_url: 'https://storage.invalid' } }).mockResolvedValueOnce({ data: null })
  vi.mocked(uploadWithProgress).mockRejectedValueOnce(new Error('network'))
  await expect(libraryApi.upload(new File(['clip'], 'clip.mp4'), 0)).rejects.toThrow('network')
  expect(request).toHaveBeenLastCalledWith('/resource-library/resources/9/cancel-upload', expect.objectContaining({ method: 'POST' }))
})

it('uploads locally with the captured destination and reports API errors', async () => {
  vi.mocked(request).mockResolvedValueOnce({ data: { direct: false } })
  vi.mocked(uploadWithProgress).mockResolvedValueOnce({ status: 200, text: JSON.stringify({ code: 400, message: '文件过大' }) })
  await expect(libraryApi.upload(new File(['clip'], 'clip.mp4'), 6)).rejects.toThrow('文件过大')
  const form = vi.mocked(uploadWithProgress).mock.calls[0]![1]
  expect(form.get('folder_id')).toBe('6')
  expect(form.get('source')).toBe('false')
})
