import apiClient from './client'
import type { LoginResponse } from './auth'

export interface PasskeyCredential {
  id: string
  device_name: string | null
  device_type: string | null
  backed_up: boolean
  is_active: boolean
  created_at: string
  last_used_at: string | null
  aaguid: string | null
  transports: string[] | null
}

export interface PasskeySettings {
  enabled: boolean
  rp_id: string
  rp_name: string
}

export interface PasskeyRegisterBeginResponse {
  challenge_id: string
  public_key_credential_creation_options: Record<string, unknown>
}

export interface PasskeyRegisterCompleteRequest {
  challenge_id: string
  credential: unknown
  device_name?: string
}

export interface PasskeyLoginBeginResponse {
  challenge_id: string
  public_key_credential_request_options: Record<string, unknown>
}

export interface PasskeyLoginCompleteRequest {
  challenge_id: string
  credential: unknown
}

export const passkeyApi = {
  // 登录
  async beginLogin(email?: string): Promise<PasskeyLoginBeginResponse> {
    const response = await apiClient.post<PasskeyLoginBeginResponse>(
      '/api/auth/passkey/login/begin',
      email ? { email } : {}
    )
    return response.data
  },

  async completeLogin(data: PasskeyLoginCompleteRequest): Promise<LoginResponse> {
    const response = await apiClient.post<LoginResponse>('/api/auth/passkey/login/complete', data)
    apiClient.setToken(response.data.access_token)
    return response.data
  },

  // 注册
  async beginRegister(deviceName?: string): Promise<PasskeyRegisterBeginResponse> {
    const response = await apiClient.post<PasskeyRegisterBeginResponse>(
      '/api/auth/passkey/register/begin',
      deviceName ? { device_name: deviceName } : {}
    )
    return response.data
  },

  async completeRegister(data: PasskeyRegisterCompleteRequest) {
    const response = await apiClient.post('/api/auth/passkey/register/complete', data)
    return response.data
  },

  // 凭证管理
  async getCredentials(): Promise<PasskeyCredential[]> {
    const response = await apiClient.get<PasskeyCredential[]>('/api/auth/passkey/credentials')
    return response.data
  },

  async updateCredential(id: string, deviceName: string): Promise<PasskeyCredential> {
    const response = await apiClient.patch<PasskeyCredential>(
      `/api/auth/passkey/credentials/${id}`,
      { device_name: deviceName }
    )
    return response.data
  },

  async deleteCredential(id: string): Promise<void> {
    await apiClient.delete(`/api/auth/passkey/credentials/${id}`)
  },

  // 设置
  async getSettings(): Promise<PasskeySettings> {
    const response = await apiClient.get<PasskeySettings>('/api/auth/passkey/settings')
    return response.data
  }
}
