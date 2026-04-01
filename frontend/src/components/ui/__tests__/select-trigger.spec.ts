import { describe, expect, it } from 'vitest'

import source from '../select-trigger.vue?raw'

describe('select-trigger wrapper', () => {
  it('keeps trigger and label text left-aligned', () => {
    expect(source).toContain('text-left text-sm')
    expect(source).toContain('flex-1 truncate text-left')
  })
})
