<template>
  <Dialog
    :model-value="open"
    title="故障转移规则"
    description="配置提供商级别的故障转移规则。默认所有错误都会触发转移，此处可自定义例外。"
    :icon="GitBranch"
    size="lg"
    @update:model-value="handleClose"
  >
    <div class="space-y-5 max-h-[60vh] overflow-y-auto px-0.5 py-0.5 -mx-0.5">
      <!-- 成功转移规则 -->
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-sm font-medium">
              成功转移规则
            </h3>
            <p class="text-xs text-muted-foreground mt-0.5">
              HTTP 200 但响应体匹配正则时，视为失败并触发转移
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            @click="addRule('success')"
          >
            <Plus class="w-4 h-4 mr-1" />
            添加
          </Button>
        </div>

        <div
          v-if="successPatterns.length === 0"
          class="text-xs text-muted-foreground px-3 py-4 border border-dashed rounded-lg text-center"
        >
          暂无规则
        </div>

        <div
          v-for="(rule, index) in successPatterns"
          :key="'s-' + index"
          class="flex items-center gap-1"
        >
          <Input
            v-model="rule.pattern"
            placeholder="例如: relay:.*格式错误"
            class="font-mono text-xs flex-1"
          />
          <Button
            variant="ghost"
            size="sm"
            class="shrink-0 h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
            @click="removeRule('success', index)"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      <!-- 错误终止规则 -->
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-sm font-medium">
              错误终止规则
            </h3>
            <p class="text-xs text-muted-foreground mt-0.5">
              HTTP 非 200 且响应体匹配正则时，停止转移并直接返回错误。可选填状态码缩小匹配范围
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            @click="addRule('error')"
          >
            <Plus class="w-4 h-4 mr-1" />
            添加
          </Button>
        </div>

        <div
          v-if="errorPatterns.length === 0"
          class="text-xs text-muted-foreground px-3 py-4 border border-dashed rounded-lg text-center"
        >
          暂无规则
        </div>

        <div
          v-for="(rule, index) in errorPatterns"
          :key="'e-' + index"
          class="flex items-center gap-1"
        >
          <Input
            :model-value="formatStatusCodes(rule.status_codes)"
            placeholder="状态码"
            size="sm"
            class="font-mono text-xs w-24 shrink-0"
            @update:model-value="(v: string | number) => rule.status_codes = parseStatusCodes(String(v))"
          />
          <Input
            v-model="rule.pattern"
            placeholder="例如: content_policy_violation"
            class="font-mono text-xs flex-1"
          />
          <Button
            variant="ghost"
            size="sm"
            class="shrink-0 h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
            @click="removeRule('error', index)"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
    </div>

    <template #footer>
      <Button
        variant="outline"
        :disabled="saving"
        @click="handleClose"
      >
        取消
      </Button>
      <Button
        :disabled="saving"
        @click="handleSave"
      >
        {{ saving ? '保存中...' : '保存' }}
      </Button>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  Dialog,
  Button,
  Input,
} from '@/components/ui'
import { GitBranch, Plus, Trash2 } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { updateProvider, type ProviderWithEndpointsSummary } from '@/api/endpoints'
import { parseApiError } from '@/utils/errorParser'
import type { FailoverRuleItem } from '@/api/endpoints/types'

const props = defineProps<{
  open: boolean
  provider: ProviderWithEndpointsSummary | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': []
}>()

const { success, error: showError } = useToast()
const saving = ref(false)

const successPatterns = ref<FailoverRuleItem[]>([])
const errorPatterns = ref<FailoverRuleItem[]>([])

watch(() => [props.open, props.provider], () => {
  if (props.open && props.provider) {
    const rules = props.provider.failover_rules
    successPatterns.value = (rules?.success_failover_patterns || []).map(r => ({ ...r }))
    errorPatterns.value = (rules?.error_stop_patterns || []).map(r => ({ ...r }))
  }
}, { immediate: true })

function addRule(type: 'success' | 'error') {
  const rule: FailoverRuleItem = { pattern: '', description: '' }
  if (type === 'success') {
    successPatterns.value.push(rule)
  } else {
    errorPatterns.value.push(rule)
  }
}

function removeRule(type: 'success' | 'error', index: number) {
  if (type === 'success') {
    successPatterns.value.splice(index, 1)
  } else {
    errorPatterns.value.splice(index, 1)
  }
}

function handleClose() {
  emit('update:open', false)
}

function formatStatusCodes(codes: number[] | undefined): string {
  if (!codes || codes.length === 0) return ''
  return codes.join(',')
}

function parseStatusCodes(input: string): number[] | undefined {
  const trimmed = input.trim()
  if (!trimmed) return undefined
  const codes = trimmed
    .split(/[,\s]+/)
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n >= 100 && n <= 599)
  return codes.length > 0 ? codes : undefined
}

async function handleSave() {
  if (!props.provider) return

  // Validate patterns
  const allPatterns = [...successPatterns.value, ...errorPatterns.value]
  for (const rule of allPatterns) {
    if (!rule.pattern.trim()) {
      showError('正则表达式不能为空', '验证失败')
      return
    }
    try {
      new RegExp(rule.pattern)
    } catch {
      showError(`无效的正则表达式: ${rule.pattern}`, '验证失败')
      return
    }
  }

  saving.value = true
  try {
    const filteredSuccess = successPatterns.value.filter(r => r.pattern.trim())
    const filteredError = errorPatterns.value.filter(r => r.pattern.trim())

    const hasRules = filteredSuccess.length > 0 || filteredError.length > 0

    await updateProvider(props.provider.id, {
      failover_rules: hasRules
        ? {
            success_failover_patterns: filteredSuccess,
            error_stop_patterns: filteredError,
          }
        : null,
    })

    success('故障转移规则已保存')
    emit('saved')
    handleClose()
  } catch (err: unknown) {
    showError(parseApiError(err, '保存故障转移规则失败'), '保存失败')
  } finally {
    saving.value = false
  }
}
</script>
