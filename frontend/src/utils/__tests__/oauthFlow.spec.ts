import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearPendingOAuthBindRequestId,
  createOAuthBindRequestId,
  clearPendingOAuthBindProviderType,
  getOAuthErrorMessage,
  getPendingOAuthBindRequestId,
  getPendingOAuthBindProviderType,
  isOAuthBindResultMessage,
  OAUTH_BIND_RESULT_MESSAGE_TYPE,
  setPendingOAuthBindRequestId,
  setPendingOAuthBindProviderType,
} from '@/utils/oauthFlow'

describe('oauthFlow', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('validates bind result messages by shape', () => {
    expect(isOAuthBindResultMessage({
      type: OAUTH_BIND_RESULT_MESSAGE_TYPE,
      status: 'success',
      requestId: 'bind-req-1',
      providerType: 'github',
      providerDisplayName: 'GitHub',
    })).toBe(true)

    expect(isOAuthBindResultMessage({
      type: OAUTH_BIND_RESULT_MESSAGE_TYPE,
      status: 'pending',
      requestId: 'bind-req-1',
    })).toBe(false)

    expect(isOAuthBindResultMessage({
      type: 'unexpected',
      status: 'success',
      requestId: 'bind-req-1',
    })).toBe(false)
  })

  it('stores and clears the pending bind state', () => {
    expect(getPendingOAuthBindProviderType()).toBeNull()
    expect(getPendingOAuthBindRequestId()).toBeNull()

    setPendingOAuthBindProviderType('github')
    setPendingOAuthBindRequestId('bind-req-1')
    expect(getPendingOAuthBindProviderType()).toBe('github')
    expect(getPendingOAuthBindRequestId()).toBe('bind-req-1')

    clearPendingOAuthBindProviderType()
    clearPendingOAuthBindRequestId()
    expect(getPendingOAuthBindProviderType()).toBeNull()
    expect(getPendingOAuthBindRequestId()).toBeNull()
  })

  it('creates a non-empty bind request id', () => {
    expect(createOAuthBindRequestId()).toMatch(/^\d+-[a-z0-9]+$/)
  })

  it('maps bind-specific errors without exposing provider internals', () => {
    expect(getOAuthErrorMessage('invalid_bind_state')).toBe('绑定状态已失效，请重新发起绑定')
    expect(getOAuthErrorMessage('provider_error', 'token rejected')).toBe('OAuth 服务异常，请稍后重试')
  })
})
