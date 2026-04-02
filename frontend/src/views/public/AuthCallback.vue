<template>
  <div class="min-h-screen flex items-center justify-center px-6">
    <Card class="w-full max-w-md p-6 space-y-2">
      <h1 class="text-lg font-semibold text-foreground">
        正在处理认证...
      </h1>
      <p class="text-sm text-muted-foreground">
        {{ hint }}
      </p>
    </Card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Card from '@/components/ui/card.vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import {
  clearPendingOAuthBindRequestId,
  clearPendingOAuthBindProviderType,
  getOAuthErrorMessage,
  getPendingOAuthBindRequestId,
  getPendingOAuthBindProviderType,
  OAUTH_BIND_RESULT_MESSAGE_TYPE,
  type OAuthBindResultMessage,
} from '@/utils/oauthFlow'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { success, error: showError } = useToast()

const hint = ref('请稍候...')

function clearPendingBindState() {
  sessionStorage.removeItem('redirectPath')
  clearPendingOAuthBindRequestId()
  clearPendingOAuthBindProviderType()
}

function consumeRedirectPath(): string | null {
  const redirectPath = sessionStorage.getItem('redirectPath')
  if (redirectPath) {
    sessionStorage.removeItem('redirectPath')
    return redirectPath
  }
  return null
}

function clearUrlState() {
  // 清理 fragment，避免刷新时重复处理
  // 同时清理 query（oauth_bound / error_code / error_detail）
  const newUrl = window.location.pathname
  window.history.replaceState({}, document.title, newUrl)
}

function postBindResult(message: OAuthBindResultMessage): boolean {
  if (!window.opener || window.opener === window) {
    return false
  }

  try {
    window.opener.postMessage(message, window.location.origin)
    return true
  } catch {
    return false
  }
}

async function finalizeBindFlow(
  message: OAuthBindResultMessage,
  fallbackPath: string,
  fallbackToast: () => void,
) {
  const redirectPath = consumeRedirectPath()
  clearUrlState()
  clearPendingBindState()

  if (postBindResult(message)) {
    hint.value = message.status === 'success'
      ? '绑定成功，正在返回原页面...'
      : '绑定失败，正在返回原页面...'
    window.close()
    window.setTimeout(() => {
      void router.replace(redirectPath || fallbackPath)
    }, 250)
    return
  }

  fallbackToast()
  await router.replace(redirectPath || fallbackPath)
}

onMounted(async () => {
  // 1) 绑定成功提示
  const oauthBound = route.query.oauth_bound
  const bindProviderType = getPendingOAuthBindProviderType()
  const bindRequestId = getPendingOAuthBindRequestId()
  if (typeof oauthBound === 'string' && oauthBound) {
    if (bindProviderType && bindRequestId) {
      await finalizeBindFlow(
        {
          type: OAUTH_BIND_RESULT_MESSAGE_TYPE,
          status: 'success',
          requestId: bindRequestId,
          providerType: bindProviderType,
          providerDisplayName: oauthBound,
        },
        '/dashboard/settings',
        () => success(`已绑定 ${oauthBound}`),
      )
      return
    }

    success(`已绑定 ${oauthBound}`)
    clearUrlState()
    const redirectPath = consumeRedirectPath()
    clearPendingOAuthBindProviderType()
    await router.replace(redirectPath || '/dashboard/settings')
    return
  }

  // 2) 错误提示
  const errorCode = route.query.error_code
  const errorDetail = typeof route.query.error_detail === 'string' ? route.query.error_detail : undefined
  if (typeof errorCode === 'string' && errorCode) {
    if (bindProviderType && bindRequestId) {
      await finalizeBindFlow(
        {
          type: OAUTH_BIND_RESULT_MESSAGE_TYPE,
          status: 'error',
          requestId: bindRequestId,
          providerType: bindProviderType,
          errorCode,
          errorDetail,
        },
        '/dashboard/settings',
        () => showError(getOAuthErrorMessage(errorCode, errorDetail)),
      )
      return
    }

    showError(getOAuthErrorMessage(errorCode, errorDetail))
    clearUrlState()
    const redirectPath = consumeRedirectPath()
    clearPendingOAuthBindProviderType()
    await router.replace(redirectPath || '/')
    return
  }

  // 3) 登录成功：解析 fragment token
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash
  const params = new URLSearchParams(hash)
  const accessToken = params.get('access_token')

  clearUrlState()
  clearPendingBindState()

  if (!accessToken) {
    showError('未获取到访问令牌')
    await router.replace('/')
    return
  }

  hint.value = '正在写入登录态...'
  apiClient.setToken(accessToken)

  authStore.syncToken()

  hint.value = '正在获取用户信息...'
  await authStore.fetchCurrentUser()

  success('登录成功')

  const redirectPath = consumeRedirectPath()
  const target = redirectPath || (authStore.user?.role === 'admin' ? '/admin/dashboard' : '/dashboard')
  await router.replace(target)
})
</script>
