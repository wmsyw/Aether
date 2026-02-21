import client from '../client'

export interface ProviderOAuthStartResponse {
  authorization_url: string
  redirect_uri: string
  provider_type: string
  instructions: string
}

export interface ProviderOAuthCompleteRequest {
  callback_url: string
  name?: string
  proxy_node_id?: string
}

export interface ProviderOAuthCompleteResponse {
  provider_type: string
  expires_at?: number | null
  has_refresh_token: boolean
  email?: string | null
}

export interface ProviderOAuthCompleteResponseWithKey {
  key_id: string
  provider_type: string
  expires_at?: number | null
  has_refresh_token: boolean
  email?: string | null
}

export async function refreshProviderOAuth(keyId: string): Promise<ProviderOAuthCompleteResponse> {
  const resp = await client.post(`/api/admin/provider-oauth/keys/${keyId}/refresh`)
  return resp.data
}

// Provider-level OAuth (不需要预先创建 key)

export async function startProviderLevelOAuth(providerId: string): Promise<ProviderOAuthStartResponse> {
  const resp = await client.post(`/api/admin/provider-oauth/providers/${providerId}/start`)
  return resp.data
}

export async function completeProviderLevelOAuth(
  providerId: string,
  data: ProviderOAuthCompleteRequest
): Promise<ProviderOAuthCompleteResponseWithKey> {
  const resp = await client.post(`/api/admin/provider-oauth/providers/${providerId}/complete`, data)
  return resp.data
}

export async function importProviderRefreshToken(
  providerId: string,
  data: { refresh_token: string; name?: string; proxy_node_id?: string }
): Promise<ProviderOAuthCompleteResponseWithKey> {
  const resp = await client.post(`/api/admin/provider-oauth/providers/${providerId}/import-refresh-token`, data)
  return resp.data
}

// Device Authorization (AWS SSO OIDC)

export interface DeviceAuthorizeRequest {
  start_url?: string
  region?: string
  proxy_node_id?: string
}

export interface DeviceAuthorizeResponse {
  session_id: string
  user_code: string
  verification_uri: string
  verification_uri_complete: string
  expires_in: number
  interval: number
}

export interface DevicePollRequest {
  session_id: string
}

export interface DevicePollResponse {
  status: 'pending' | 'authorized' | 'slow_down' | 'expired' | 'error'
  key_id?: string
  email?: string
  error?: string
  replaced?: boolean
}

export async function startDeviceAuthorize(
  providerId: string,
  data: DeviceAuthorizeRequest
): Promise<DeviceAuthorizeResponse> {
  const resp = await client.post(`/api/admin/provider-oauth/providers/${providerId}/device-authorize`, data)
  return resp.data
}

export async function pollDeviceAuthorize(
  providerId: string,
  data: DevicePollRequest
): Promise<DevicePollResponse> {
  const resp = await client.post(`/api/admin/provider-oauth/providers/${providerId}/device-poll`, data)
  return resp.data
}
