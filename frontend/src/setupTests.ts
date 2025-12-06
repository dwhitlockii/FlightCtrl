import '@testing-library/jest-dom'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// Basic fetch mock to avoid undefined in tests
if (!globalThis.fetch) {
  globalThis.fetch = vi.fn()
}
