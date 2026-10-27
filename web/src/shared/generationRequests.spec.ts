import { beforeEach, expect, it, vi } from 'vitest'
import { generationRequest } from './generationRequests'

beforeEach(() => localStorage.clear())

it('keeps an unresolved request across a page/module reload without storing credentials or content', async () => {
  const first = await generationRequest('private-token:team-1', '/video/generate/', 'private-prompt')
  expect(JSON.stringify(localStorage)).not.toContain('private-token')
  expect(JSON.stringify(localStorage)).not.toContain('private-prompt')
  vi.resetModules()
  const fresh = await import('./generationRequests')
  const retry = await fresh.generationRequest('private-token:team-1', '/video/generate/', 'private-prompt')
  expect(retry.id).toBe(first.id)
  expect((await fresh.generationRequest('other-account', '/video/generate/', 'private-prompt')).id).not.toBe(first.id)
  fresh.finishGenerationRequest(retry.key)
  expect((await fresh.generationRequest('private-token:team-1', '/video/generate/', 'private-prompt')).id).not.toBe(first.id)
})

it('fails before a new request if persistence is unavailable', async () => {
  const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Full', 'QuotaExceededError') })
  try { await expect(generationRequest('identity', '/video/generate/', '{}')).rejects.toThrow('Full') }
  finally { write.mockRestore() }
})
