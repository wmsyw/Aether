import { describe, expect, it } from 'vitest'

import {
  formatApiFormat,
  normalizeApiFormatKey,
  normalizeApiFormatRecord,
  normalizeApiFormats,
  sortApiFormats,
} from '@/api/endpoints/types/api-format'

describe('api format normalization', () => {
  it('normalizes uppercase imported signature keys', () => {
    expect(normalizeApiFormatKey('OPENAI:CLI')).toBe('openai:cli')
    expect(normalizeApiFormatKey(' openai:chat ')).toBe('openai:chat')
  })

  it('normalizes legacy underscore tokens', () => {
    expect(normalizeApiFormatKey('OPENAI_CLI')).toBe('openai:cli')
    expect(normalizeApiFormatKey('CLAUDE')).toBe('claude:chat')
  })

  it('deduplicates and sorts normalized formats', () => {
    expect(sortApiFormats(['OPENAI:CLI', 'openai:chat', 'OPENAI:CLI'])).toEqual([
      'openai:chat',
      'openai:cli',
    ])
    expect(normalizeApiFormats(['OPENAI:CLI', ' openai:chat ', 'OPENAI:CLI'])).toEqual([
      'openai:cli',
      'openai:chat',
    ])
  })

  it('normalizes format-keyed records for UI lookups', () => {
    expect(normalizeApiFormatRecord({ 'OPENAI:CLI': { open: true } })).toEqual({
      'openai:cli': { open: true },
    })
  })

  it('formats normalized labels for imported values', () => {
    expect(formatApiFormat('OPENAI:CLI')).toBe('OpenAI CLI')
  })
})
