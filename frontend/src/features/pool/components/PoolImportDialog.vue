<template>
  <Dialog
    :model-value="modelValue"
    title="批量导入账号"
    description="以 JSON 格式批量导入 API Key 到号池"
    size="lg"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="space-y-4">
      <div class="space-y-1.5">
        <Label>JSON 数据</Label>
        <textarea
          v-model="jsonText"
          class="w-full h-48 p-3 text-sm font-mono border rounded-lg bg-background resize-none focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="[{&quot;name&quot;: &quot;key-01&quot;, &quot;api_key&quot;: &quot;sk-xxx&quot;}, ...]"
        />
        <p class="text-xs text-muted-foreground">
          格式: [{"name": "名称", "api_key": "密钥", "auth_type": "api_key"}]，auth_type 可选
        </p>
      </div>

      <div
        v-if="parseError"
        class="text-sm text-destructive"
      >
        {{ parseError }}
      </div>

      <div
        v-if="parsedCount > 0"
        class="text-sm text-muted-foreground"
      >
        已解析 {{ parsedCount }} 个账号
      </div>

      <div
        v-if="importResult"
        class="space-y-1 text-sm"
      >
        <p class="text-green-600">
          成功导入: {{ importResult.imported }}
        </p>
        <p
          v-if="importResult.errors.length > 0"
          class="text-destructive"
        >
          失败: {{ importResult.errors.length }}
        </p>
        <div
          v-for="err in importResult.errors.slice(0, 5)"
          :key="err.index"
          class="text-xs text-destructive"
        >
          #{{ err.index }}: {{ err.reason }}
        </div>
      </div>
    </div>

    <template #footer>
      <Button
        variant="outline"
        :disabled="loading"
        @click="emit('update:modelValue', false)"
      >
        {{ importResult ? '关闭' : '取消' }}
      </Button>
      <Button
        v-if="!importResult"
        :disabled="loading || parsedCount === 0"
        @click="handleImport"
      >
        {{ loading ? '导入中...' : `导入 ${parsedCount} 个账号` }}
      </Button>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Dialog, Button, Label } from '@/components/ui'
import { useToast } from '@/composables/useToast'
import { parseApiError } from '@/utils/errorParser'
import { batchImportPoolKeys } from '@/api/endpoints/pool'
import type { BatchImportResponse, PoolKeyImportItem } from '@/api/endpoints/pool'

const props = defineProps<{
  modelValue: boolean
  providerId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  imported: []
}>()

const { error: showError } = useToast()
const jsonText = ref('')
const loading = ref(false)
const parseError = ref('')
const importResult = ref<BatchImportResponse | null>(null)

const parsedKeys = computed<PoolKeyImportItem[]>(() => {
  if (!jsonText.value.trim()) return []
  try {
    const data = JSON.parse(jsonText.value)
    if (!Array.isArray(data)) {
      return []
    }
    return data.map((item: Record<string, unknown>) => ({
      name: String(item.name || ''),
      api_key: String(item.api_key || ''),
      auth_type: String(item.auth_type || 'api_key'),
    }))
  } catch {
    return []
  }
})

watch(jsonText, (val) => {
  if (!val.trim()) {
    parseError.value = ''
    return
  }
  try {
    const data = JSON.parse(val)
    parseError.value = Array.isArray(data) ? '' : 'JSON 必须是数组格式'
  } catch {
    parseError.value = 'JSON 格式无效'
  }
})

const parsedCount = computed(() => parsedKeys.value.length)

watch(() => props.modelValue, (v) => {
  if (v) {
    jsonText.value = ''
    importResult.value = null
    parseError.value = ''
  }
})

async function handleImport() {
  if (!parsedKeys.value.length) return
  loading.value = true
  try {
    importResult.value = await batchImportPoolKeys(props.providerId, parsedKeys.value)
    if (importResult.value.imported > 0) {
      emit('imported')
    }
  } catch (err) {
    showError(parseApiError(err))
  } finally {
    loading.value = false
  }
}
</script>
