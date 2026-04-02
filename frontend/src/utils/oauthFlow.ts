export const OAUTH_BIND_PROVIDER_STORAGE_KEY = 'oauthBindProviderType'
export const OAUTH_BIND_REQUEST_ID_STORAGE_KEY = 'oauthBindRequestId'
export const OAUTH_BIND_RESULT_MESSAGE_TYPE = 'aether:oauth-bind-result' as const

export type OAuthBindResultStatus = 'success' | 'error'

export type OAuthBindResultMessage = {
  type: typeof OAUTH_BIND_RESULT_MESSAGE_TYPE
  status: OAuthBindResultStatus
  requestId: string
  providerType?: string
  providerDisplayName?: string
  errorCode?: string
  errorDetail?: string
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string'
}

export function isOAuthBindResultMessage(value: unknown): value is OAuthBindResultMessage {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const message = value as Record<string, unknown>
  return (
    message.type === OAUTH_BIND_RESULT_MESSAGE_TYPE &&
    (message.status === 'success' || message.status === 'error') &&
    typeof message.requestId === 'string' &&
    message.requestId.length > 0 &&
    isOptionalString(message.providerType) &&
    isOptionalString(message.providerDisplayName) &&
    isOptionalString(message.errorCode) &&
    isOptionalString(message.errorDetail)
  )
}

export function setPendingOAuthBindProviderType(providerType: string): void {
  sessionStorage.setItem(OAUTH_BIND_PROVIDER_STORAGE_KEY, providerType)
}

export function getPendingOAuthBindProviderType(): string | null {
  const providerType = sessionStorage.getItem(OAUTH_BIND_PROVIDER_STORAGE_KEY)?.trim()
  return providerType || null
}

export function clearPendingOAuthBindProviderType(): void {
  sessionStorage.removeItem(OAUTH_BIND_PROVIDER_STORAGE_KEY)
}

export function createOAuthBindRequestId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function setPendingOAuthBindRequestId(requestId: string): void {
  sessionStorage.setItem(OAUTH_BIND_REQUEST_ID_STORAGE_KEY, requestId)
}

export function getPendingOAuthBindRequestId(): string | null {
  const requestId = sessionStorage.getItem(OAUTH_BIND_REQUEST_ID_STORAGE_KEY)?.trim()
  return requestId || null
}

export function clearPendingOAuthBindRequestId(): void {
  sessionStorage.removeItem(OAUTH_BIND_REQUEST_ID_STORAGE_KEY)
}

export function getOAuthErrorMessage(code: string, _detail?: string): string {
  const map: Record<string, string> = {
    authorization_denied: '你已取消授权',
    provider_disabled: '该 OAuth Provider 已被禁用',
    provider_unavailable: 'OAuth Provider 不可用',
    invalid_callback: '回调参数无效',
    invalid_state: '登录状态已失效，请重试',
    invalid_bind_state: '绑定状态已失效，请重新发起绑定',
    token_exchange_failed: '令牌兑换失败',
    userinfo_fetch_failed: '获取用户信息失败',
    email_exists_local: '该邮箱已存在，请先登录后再绑定 OAuth',
    email_is_ldap: '该邮箱属于 LDAP 账号，请使用 LDAP 登录',
    email_is_oauth: '该邮箱已关联其他 OAuth 账号，请使用原账号登录',
    email_suffix_denied: '该邮箱后缀不符合系统限制，无法完成绑定或注册',
    registration_disabled: '系统未开放注册，无法创建新账号',
    oauth_already_bound: '该第三方账号已被其他用户绑定',
    already_bound_provider: '你已绑定该 Provider',
    last_oauth_binding: '解绑失败：至少需要保留一个 OAuth 绑定',
    last_login_method: '解绑失败：解绑后将无法登录',
    ldap_no_oauth: 'LDAP 用户不支持 OAuth 绑定',
    account_disabled: '当前账号不可用，请联系管理员',
    user_not_found: '当前用户不存在或已失效，请重新登录后再试',
    provider_error: 'OAuth 服务异常，请稍后重试',
  }

  return map[code] || '认证失败，请重试'
}
