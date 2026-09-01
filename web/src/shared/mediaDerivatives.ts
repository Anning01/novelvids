import type { Video } from '@/types'

type ImageDerivativeKind = 'thumbnail' | 'preview'

function managedDerivativeUrl(
  source: string | null | undefined,
  directory: 'derivatives' | 'posters',
  kind: ImageDerivativeKind,
): string {
  if (!source || source.startsWith('data:') || source.startsWith('blob:')) return source || ''
  const absolute = /^https?:\/\//i.test(source)
  if (absolute) return source
  let parsed: URL
  try {
    parsed = new URL(source, 'https://novelvids.local')
  } catch {
    return source
  }
  const path = parsed.pathname
  if (!path.startsWith('/media/')) return source
  if (path.includes(`/${directory}/`)) return source
  const slash = path.lastIndexOf('/')
  const dot = path.lastIndexOf('.')
  if (slash < 0 || dot <= slash) return source
  parsed.pathname = `${path.slice(0, slash)}/${directory}/${path.slice(slash + 1, dot)}-${kind}.webp`
  parsed.search = ''
  parsed.hash = ''
  return parsed.pathname
}

export function imageDerivativeUrl(
  source: string | null | undefined,
  kind: ImageDerivativeKind = 'thumbnail',
): string {
  return managedDerivativeUrl(source, 'derivatives', kind)
}

export function videoPosterUrl(
  video: Video | null | undefined,
  kind: ImageDerivativeKind = 'preview',
): string {
  const metadata = video?.metadata || {}
  const key = kind === 'thumbnail' ? 'poster_thumbnail_url' : 'poster_url'
  const value = metadata[key]
  return typeof value === 'string' ? value : ''
}
