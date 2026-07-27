import { enableAutoUnmount } from '@vue/test-utils'
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

enableAutoUnmount(afterEach)

Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
  configurable: true,
  value() {},
})
