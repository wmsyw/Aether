import type { useAuthStore } from '@/stores/auth'
import { log } from '@/utils/logger'

/**
 * 判断错误是否为网络错误
 */
function isNetworkError(error: any): boolean {
  return !error.response || error.message?.includes('Network') || error.message?.includes('timeout')
}

/**
 * 确保用户信息已加载。如果有 token 但未加载用户信息，尝试获取。
 * @returns true 如果用户已认证，false 如果认证失败
 */
export async function ensureUserLoaded(
  authStore: ReturnType<typeof useAuthStore>
): Promise<boolean> {
  if (authStore.token && !authStore.user) {
    try {
      await authStore.fetchCurrentUser()
    } catch (error: any) {
      // 区分网络错误和认证错误
      if (isNetworkError(error)) {
        log.warn('Network error while fetching user info, keeping session', {
          error: error?.message
        })
      } else if (error.response?.status === 401) {
        log.info('Authentication failed, clearing session')
        authStore.logout()
      } else {
        log.warn('Failed to fetch user info, but keeping session', { error: error?.message })
      }
    }
  }

  return !!authStore.token
}
