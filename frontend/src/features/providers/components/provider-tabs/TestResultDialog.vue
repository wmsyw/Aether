<template>
  <Dialog
    :open="!!result"
    size="2xl"
    title="模型测试结果"
    @update:open="(val: boolean) => { if (!val) $emit('close') }"
  >
    <div
      v-if="result"
      class="space-y-4"
    >
      <!-- 总体状态 -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Badge :variant="result.success ? 'success' : 'destructive'">
            {{ result.success ? '成功' : '失败' }}
          </Badge>
          <span class="text-sm text-muted-foreground">
            {{ modeLabel }}
          </span>
        </div>
        <div class="text-xs text-muted-foreground">
          候选 {{ result.total_candidates }} / 尝试 {{ result.total_attempts }}
        </div>
      </div>

      <!-- 模型信息 -->
      <div class="text-sm space-y-1">
        <div>
          <span class="text-muted-foreground">请求模型: </span>
          <span class="font-medium">{{ result.model }}</span>
        </div>
        <div v-if="successEffectiveModel">
          <span class="text-muted-foreground">发送模型: </span>
          <span class="font-medium text-primary">{{ successEffectiveModel }}</span>
          <span
            v-if="successEffectiveModel !== result.model"
            class="text-xs text-muted-foreground ml-1"
          >(已映射)</span>
        </div>
      </div>

      <!-- 错误信息 -->
      <div
        v-if="result.error && !result.success"
        class="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-xs text-destructive"
      >
        {{ result.error }}
      </div>

      <!-- Attempt 详情表 -->
      <div
        v-if="result.attempts.length > 0"
        class="border rounded-md overflow-hidden"
      >
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b bg-muted/30">
              <th class="px-3 py-2 text-left font-medium">
                #
              </th>
              <th class="px-3 py-2 text-left font-medium">
                Key
              </th>
              <th class="px-3 py-2 text-left font-medium">
                格式
              </th>
              <th
                v-if="hasEffectiveModel"
                class="px-3 py-2 text-left font-medium"
              >
                发送模型
              </th>
              <th class="px-3 py-2 text-left font-medium">
                状态
              </th>
              <th class="px-3 py-2 text-right font-medium">
                延迟
              </th>
              <th class="px-3 py-2 text-left font-medium">
                详情
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(attempt, idx) in result.attempts"
              :key="idx"
              class="border-b last:border-b-0"
              :class="attemptRowClass(attempt.status)"
            >
              <td class="px-3 py-2 text-muted-foreground">
                {{ attempt.candidate_index }}
              </td>
              <td
                class="px-3 py-2 max-w-[160px] truncate"
                :title="attempt.key_name || attempt.key_id"
              >
                {{ attempt.key_name || (attempt.key_id.length > 8 ? attempt.key_id.slice(0, 8) + '...' : attempt.key_id) }}
                <span class="text-muted-foreground ml-1">({{ attempt.auth_type }})</span>
              </td>
              <td class="px-3 py-2">
                <code class="text-[11px] bg-muted px-1 py-0.5 rounded">
                  {{ attempt.endpoint_api_format }}
                </code>
              </td>
              <td
                v-if="hasEffectiveModel"
                class="px-3 py-2 max-w-[180px] truncate"
                :title="attempt.effective_model || '-'"
              >
                {{ attempt.effective_model || '-' }}
              </td>
              <td class="px-3 py-2">
                <Badge
                  :variant="statusVariant(attempt.status)"
                  class="text-[10px] px-1.5 py-0"
                >
                  {{ statusLabel(attempt.status) }}
                </Badge>
                <span
                  v-if="attempt.status_code"
                  class="text-muted-foreground ml-1"
                >
                  {{ attempt.status_code }}
                </span>
              </td>
              <td class="px-3 py-2 text-right text-muted-foreground">
                {{ attempt.latency_ms != null ? attempt.latency_ms + 'ms' : '-' }}
              </td>
              <td
                class="px-3 py-2 max-w-[200px] truncate text-muted-foreground"
                :title="attemptDetail(attempt)"
              >
                {{ attemptDetail(attempt) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 无 attempt -->
      <div
        v-else
        class="text-center text-sm text-muted-foreground py-4"
      >
        没有可用的候选进行测试
      </div>
    </div>

    <template #footer>
      <Button
        variant="outline"
        size="sm"
        @click="$emit('close')"
      >
        关闭
      </Button>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Dialog, Badge } from '@/components/ui'
import Button from '@/components/ui/button.vue'
import type { TestModelFailoverResponse, TestAttemptDetail } from '@/api/endpoints/providers'

const props = defineProps<{
  result: TestModelFailoverResponse | null
  mode?: 'global' | 'direct'
}>()

defineEmits<{
  close: []
}>()

const modeLabel = computed(() => {
  if (props.mode === 'global') return '模拟外部请求'
  if (props.mode === 'direct') return '直接测试'
  return ''
})

const successEffectiveModel = computed(() => {
  if (!props.result) return null
  const successAttempt = props.result.attempts.find(a => a.status === 'success')
  return successAttempt?.effective_model || null
})

const hasEffectiveModel = computed(() => {
  if (!props.result) return false
  return props.result.attempts.some(a => a.effective_model && a.effective_model !== props.result?.model)
})

function statusVariant(status: string) {
  if (status === 'success') return 'success' as const
  if (status === 'failed') return 'destructive' as const
  return 'secondary' as const
}

function statusLabel(status: string) {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '跳过'
  return status
}

function attemptRowClass(status: string) {
  if (status === 'success') return 'bg-green-500/5'
  if (status === 'failed') return 'bg-red-500/5'
  if (status === 'skipped') return 'bg-muted/20'
  return ''
}

function attemptDetail(attempt: TestAttemptDetail): string {
  if (attempt.skip_reason) return attempt.skip_reason
  if (attempt.error_message) return attempt.error_message
  if (attempt.status === 'success') return attempt.endpoint_base_url
  return '-'
}
</script>
