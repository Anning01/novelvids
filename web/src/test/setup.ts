import { enableAutoUnmount } from '@vue/test-utils'
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

enableAutoUnmount(afterEach)

function createMemoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() { return values.size },
    clear() { values.clear() },
    getItem(key) { return values.get(key) ?? null },
    key(index) { return [...values.keys()][index] ?? null },
    removeItem(key) { values.delete(key) },
    setItem(key, value) { values.set(key, String(value)) },
  }
}

if (typeof window.localStorage?.getItem !== 'function') {
  const storage = createMemoryStorage()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: storage })
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage })
}

Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
  configurable: true,
  value() {},
})

class IntersectionObserverStub implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly scrollMargin = ''
  readonly thresholds: ReadonlyArray<number> = []
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

if (typeof globalThis.IntersectionObserver === 'undefined') {
  globalThis.IntersectionObserver = IntersectionObserverStub
}
