import { tr } from '@/i18n'

/** Persist only unresolved request IDs, never credentials or prompt bodies. */
const STORAGE_KEY = 'novelvids_pending_generation_requests_v1'
const MAX_REQUESTS = 100

async function fingerprint(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('')
}

function load(): Record<string, string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}
    return Object.fromEntries(Object.entries(value).filter(([key, id]) => /^[a-f0-9]{64}$/.test(key)
      && typeof id === 'string' && /^[a-f0-9-]{36}$/.test(id)))
  } catch { return {} }
}

export async function generationRequest(identity: string, url: string, body: BodyInit | null | undefined) {
  const key = await fingerprint(JSON.stringify([identity, url, body ?? '']))
  const requests = load()
  const id = requests[key] ?? crypto.randomUUID()
  // Retain unresolved keys. Eviction would turn an uncertain old request into
  // a new paid operation; a full list requires resolving earlier requests.
  if (!requests[key] && Object.keys(requests).length >= MAX_REQUESTS) throw new Error(tr('未核对的生成请求过多，请先核对已有任务'))
  requests[key] = id
  localStorage.setItem(STORAGE_KEY, JSON.stringify(requests))
  return { key, id }
}

export function finishGenerationRequest(key: string) {
  const requests = load()
  delete requests[key]
  localStorage.setItem(STORAGE_KEY, JSON.stringify(requests))
}
