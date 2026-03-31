import { ref } from 'vue'
import { startRegistration, startAuthentication } from '@simplewebauthn/browser'
import { passkeyApi, type PasskeyCredential } from '@/api/passkey'
import { useToast } from '@/composables/useToast'

export function usePasskey() {
  const { success, error } = useToast()
  const loading = ref(false)
  const credentials = ref<PasskeyCredential[]>([])

  const isSupported = () => {
    return window.PublicKeyCredential !== undefined &&
           typeof window.PublicKeyCredential === 'function'
  }

  const fetchCredentials = async () => {
    try {
      loading.value = true
      credentials.value = await passkeyApi.getCredentials()
    } catch (err: unknown) {
      const errorMsg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '获取通行密钥失败'
      error(errorMsg)
    } finally {
      loading.value = false
    }
  }

  const register = async () => {
    if (!isSupported()) {
      error('您的浏览器不支持通行密钥')
      return false
    }

    try {
      loading.value = true
      
      // 1. 获取注册选项
      const beginResult = await passkeyApi.beginRegister()
      
      // 2. 调用浏览器 API 创建凭证
      const credential = await startRegistration({
        optionsJSON: beginResult.public_key_credential_creation_options as any
      })

      // 3. 发送到服务器完成注册
      await passkeyApi.completeRegister({
        challenge_id: beginResult.challenge_id,
        credential
      })
      
      success('通行密钥注册成功')
      await fetchCredentials()
      return true
    } catch (err: unknown) {
      console.error('Passkey registration error:', err)
      const errorObj = err as { name?: string, message?: string, response?: { data?: { detail?: string } } }
      if (errorObj.name === 'NotAllowedError') {
        error('已取消注册或被拒绝')
      } else {
        error(errorObj.response?.data?.detail || errorObj.message || '注册通行密钥失败')
      }
      return false
    } finally {
      loading.value = false
    }
  }

  const login = async (email?: string) => {
    if (!isSupported()) {
      error('您的浏览器不支持通行密钥')
      return null
    }

    try {
      loading.value = true
      
      // 1. 获取登录选项
      const beginResult = await passkeyApi.beginLogin(email)
      
      // 2. 调用浏览器 API 获取凭证
      const credential = await startAuthentication({
        optionsJSON: beginResult.public_key_credential_request_options as any
      })

      // 3. 发送到服务器完成登录
      const result = await passkeyApi.completeLogin({
        challenge_id: beginResult.challenge_id,
        credential
      })
      return result
    } catch (err: unknown) {
      console.error('Passkey login error:', err)
      const errorObj = err as { name?: string, message?: string, response?: { data?: { detail?: string } } }
      if (errorObj.name === 'NotAllowedError') {
        error('已取消登录或被拒绝')
      } else {
        error(errorObj.response?.data?.detail || errorObj.message || '通行密钥登录失败')
      }
      return null
    } finally {
      loading.value = false
    }
  }

  const updateCredential = async (id: string, name: string) => {
    try {
      loading.value = true
      await passkeyApi.updateCredential(id, name)
      success('凭证名称已更新')
      await fetchCredentials()
      return true
    } catch (err: unknown) {
      const errorMsg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '更新凭证失败'
      error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  const deleteCredential = async (id: string) => {
    try {
      loading.value = true
      await passkeyApi.deleteCredential(id)
      success('凭证已删除')
      await fetchCredentials()
      return true
    } catch (err: unknown) {
      const errorMsg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '删除凭证失败'
      error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    credentials,
    isSupported,
    fetchCredentials,
    register,
    login,
    updateCredential,
    deleteCredential
  }
}
