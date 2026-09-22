import { describe, expect, it } from 'vitest'
import { fallbackImage } from './mediaFallback'

describe('fallbackImage', () => {
  it('falls back once when a derived cover is unavailable', () => {
    const image = document.createElement('img')
    Object.defineProperty(image, 'src', { value: '/derived.webp', writable: true })
    fallbackImage({ currentTarget: image } as unknown as Event, '/original.png')
    expect(image.src).toBe('/original.png')

    fallbackImage({ currentTarget: image } as unknown as Event, '/other.png')
    expect(image.src).toBe('/original.png')
    expect(image.hidden).toBe(true)
    expect(image.dataset.fallbackExhausted).toBe('true')
  })

  it('hides an unavailable image when no fallback exists', () => {
    const image = document.createElement('img')
    fallbackImage({ currentTarget: image } as unknown as Event)
    expect(image.hidden).toBe(true)
  })
})
