<template>
  <button
    v-if="isSupported()"
    type="button"
    class="passkey-btn"
    :disabled="loading || authStore.loading"
    @click="handlePasskeyLogin"
  >
    <Fingerprint class="w-5 h-5" />
    <span>{{ loading ? '验证中...' : '使用通行密钥登录' }}</span>
  </button>
</template>

<script setup lang="ts">
import { Fingerprint } from 'lucide-vue-next'
import { usePasskey } from '@/composables/usePasskey'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import apiClient from '@/api/client'

const props = defineProps<{
  email?: string
}>()

const emit = defineEmits<{
  success: []
}>()

const { login, isSupported, loading } = usePasskey()
const authStore = useAuthStore()
const router = useRouter()
const { success } = useToast()

async function handlePasskeyLogin() {
  const result = await login(props.email)
  if (result && result.access_token) {
    // 登录成功，设置 token 到 apiClient 和 authStore
    apiClient.setToken(result.access_token)
    authStore.token = result.access_token
    await authStore.fetchCurrentUser()
    
    success('登录成功，正在跳转...')
    emit('success')
    
    setTimeout(() => {
      const targetPath = authStore.user?.role === 'admin' ? '/admin/dashboard' : '/dashboard'
      router.push(targetPath)
    }, 1000)
  }
}
</script>

<style scoped>
.passkey-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.625rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: hsl(var(--foreground));
  background: hsl(var(--muted) / 0.5);
  border: 1px solid hsl(var(--border) / 0.6);
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.passkey-btn:hover:not(:disabled) {
  background: hsl(var(--muted));
  border-color: hsl(var(--primary) / 0.5);
}

.passkey-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
