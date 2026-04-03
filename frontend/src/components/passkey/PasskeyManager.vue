<template>
  <div class="space-y-6">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h3 class="text-lg font-medium text-foreground">
          通行密钥 (Passkey)
        </h3>
        <p class="text-sm text-muted-foreground mt-1">
          使用指纹、面容或设备密码安全地登录您的账户，无需输入密码。
        </p>
      </div>
      <Button
        v-if="isSupported()"
        class="w-full sm:w-auto"
        :disabled="loading"
        @click="handleRegister"
      >
        <Plus class="w-4 h-4 mr-2" />
        添加通行密钥
      </Button>
    </div>

    <div
      v-if="!isSupported()"
      class="p-4 rounded-lg bg-warning/10 border border-warning/20 text-warning text-sm"
    >
      您的浏览器或设备不支持通行密钥功能。
    </div>

    <div
      v-else-if="loading && credentials.length === 0"
      class="flex justify-center py-8"
    >
      <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
    </div>

    <div
      v-else-if="credentials.length === 0"
      class="text-center py-8 border border-dashed rounded-lg"
    >
      <Fingerprint class="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
      <p class="text-sm text-muted-foreground">
        暂无通行密钥
      </p>
      <p class="text-xs text-muted-foreground/70 mt-1">
        添加通行密钥以享受更安全、便捷的登录体验
      </p>
    </div>

    <div
      v-else
      class="space-y-3"
    >
      <div
        v-for="cred in credentials"
        :key="cred.id"
        class="flex flex-col gap-4 rounded-lg border bg-card p-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex min-w-0 items-start gap-4">
          <div class="p-2 rounded-full bg-primary/10 text-primary">
            <Fingerprint class="w-5 h-5" />
          </div>
          <div class="min-w-0">
            <div class="flex items-center gap-2 min-w-0">
              <span class="min-w-0 break-all font-medium text-sm text-foreground sm:truncate">{{ cred.device_name || '未命名设备' }}</span>
              <button
                class="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                @click="startEdit(cred)"
              >
                <Edit2 class="w-3.5 h-3.5" />
              </button>
            </div>
            <div class="mt-1 flex flex-col gap-1 text-xs text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
              <span>添加于: {{ formatDate(cred.created_at) }}</span>
              <span v-if="cred.last_used_at">最后使用: {{ formatDate(cred.last_used_at) }}</span>
            </div>
          </div>
        </div>
        
        <Button
          variant="ghost"
          size="icon"
          class="self-end text-destructive hover:text-destructive hover:bg-destructive/10 sm:self-auto"
          :disabled="loading"
          @click="handleDelete(cred)"
        >
          <Trash2 class="w-4 h-4" />
        </Button>
      </div>
    </div>

    <!-- 编辑名称对话框 -->
    <Dialog
      v-model="showEditDialog"
      title="重命名通行密钥"
    >
      <div class="space-y-4 py-4">
        <div class="space-y-2">
          <Label for="cred-name">名称</Label>
          <Input
            id="cred-name"
            v-model="editName"
            placeholder="例如：我的 iPhone"
            @keyup.enter="handleUpdate"
          />
        </div>
      </div>
      <template #footer>
        <Button
          :disabled="loading || !editName.trim()"
          @click="handleUpdate"
        >
          保存
        </Button>
        <Button
          variant="outline"
          @click="showEditDialog = false"
        >
          取消
        </Button>
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, Fingerprint, Trash2, Edit2, Loader2 } from 'lucide-vue-next'
import { Button, Input, Label, Dialog } from '@/components/ui'
import { usePasskey } from '@/composables/usePasskey'
import { useConfirm } from '@/composables/useConfirm'
import type { PasskeyCredential } from '@/api/passkey'

const {
  loading,
  credentials,
  isSupported,
  fetchCredentials,
  register,
  updateCredential,
  deleteCredential
} = usePasskey()

const { confirm } = useConfirm()

// 编辑状态
const showEditDialog = ref(false)
const editingCred = ref<PasskeyCredential | null>(null)
const editName = ref('')

onMounted(() => {
  if (isSupported()) {
    fetchCredentials()
  }
})

async function handleRegister() {
  await register()
}

function startEdit(cred: PasskeyCredential) {
  editingCred.value = cred
  editName.value = cred.device_name || ''
  showEditDialog.value = true
}

async function handleUpdate() {
  if (!editingCred.value || !editName.value.trim()) return
  
  const success = await updateCredential(editingCred.value.id, editName.value.trim())
  if (success) {
    showEditDialog.value = false
  }
}

async function handleDelete(cred: PasskeyCredential) {
  const confirmed = await confirm({
    title: '删除通行密钥',
    message: `确定要删除通行密钥 "${cred.device_name || '未命名设备'}" 吗？删除后将无法使用该设备登录。`,
    confirmText: '删除',
    variant: 'destructive'
  })

  if (confirmed) {
    await deleteCredential(cred.id)
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}
</script>
