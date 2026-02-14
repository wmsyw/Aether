<template>
  <CardSection
    title="请求记录"
    description="控制请求/响应详情的入库方式和内容"
  >
    <template #actions>
      <Button
        size="sm"
        :disabled="loading || !hasChanges"
        @click="$emit('save')"
      >
        {{ loading ? '保存中...' : '保存' }}
      </Button>
    </template>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div>
        <Label
          for="request-log-level"
          class="block text-sm font-medium mb-2"
        >
          记录详细程度
        </Label>
        <Select
          :model-value="requestRecordLevel"
          @update:model-value="$emit('update:requestRecordLevel', $event)"
        >
          <SelectTrigger
            id="request-log-level"
            class="mt-1"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="basic">
              BASIC - 基本信息 (~1KB/条)
            </SelectItem>
            <SelectItem value="headers">
              HEADERS - 含请求头 (~2-3KB/条)
            </SelectItem>
            <SelectItem value="full">
              FULL - 完整请求响应 (~50KB/条)
            </SelectItem>
          </SelectContent>
        </Select>
        <p class="mt-1 text-xs text-muted-foreground">
          敏感信息会自动脱敏
        </p>
      </div>

      <div>
        <Label
          for="max-request-body-size"
          class="block text-sm font-medium"
        >
          最大请求体大小 (KB)
        </Label>
        <Input
          id="max-request-body-size"
          :model-value="maxRequestBodySizeKB"
          type="number"
          placeholder="512"
          class="mt-1"
          @update:model-value="$emit('update:maxRequestBodySizeKB', Number($event))"
        />
        <p class="mt-1 text-xs text-muted-foreground">
          超过此大小的请求体将被截断记录
        </p>
      </div>

      <div>
        <Label
          for="max-response-body-size"
          class="block text-sm font-medium"
        >
          最大响应体大小 (KB)
        </Label>
        <Input
          id="max-response-body-size"
          :model-value="maxResponseBodySizeKB"
          type="number"
          placeholder="512"
          class="mt-1"
          @update:model-value="$emit('update:maxResponseBodySizeKB', Number($event))"
        />
        <p class="mt-1 text-xs text-muted-foreground">
          超过此大小的响应体将被截断记录
        </p>
      </div>

      <div>
        <Label
          for="sensitive-headers"
          class="block text-sm font-medium"
        >
          敏感请求头
        </Label>
        <Input
          id="sensitive-headers"
          :model-value="sensitiveHeadersStr"
          placeholder="authorization, x-api-key, cookie"
          class="mt-1"
          @update:model-value="$emit('update:sensitiveHeadersStr', $event)"
        />
        <p class="mt-1 text-xs text-muted-foreground">
          逗号分隔，这些请求头会被脱敏处理
        </p>
      </div>
    </div>
  </CardSection>
</template>

<script setup lang="ts">
import Button from '@/components/ui/button.vue'
import Input from '@/components/ui/input.vue'
import Label from '@/components/ui/label.vue'
import Select from '@/components/ui/select.vue'
import SelectTrigger from '@/components/ui/select-trigger.vue'
import SelectValue from '@/components/ui/select-value.vue'
import SelectContent from '@/components/ui/select-content.vue'
import SelectItem from '@/components/ui/select-item.vue'
import { CardSection } from '@/components/layout'

defineProps<{
  requestRecordLevel: string
  maxRequestBodySizeKB: number
  maxResponseBodySizeKB: number
  sensitiveHeadersStr: string
  loading: boolean
  hasChanges: boolean
}>()

defineEmits<{
  save: []
  'update:requestRecordLevel': [value: string]
  'update:maxRequestBodySizeKB': [value: number]
  'update:maxResponseBodySizeKB': [value: number]
  'update:sensitiveHeadersStr': [value: string]
}>()
</script>
