<template>
  <CardSection
    title="用户数据管理"
    description="导出或导入用户及其 API Keys 数据（不含管理员）"
  >
    <div class="flex flex-wrap gap-4">
      <div class="flex-1 min-w-[200px]">
        <p class="text-sm text-muted-foreground mb-3">
          导出所有普通用户及其 API Keys 到 JSON 文件
        </p>
        <Button
          variant="outline"
          :disabled="exportLoading"
          @click="$emit('export')"
        >
          <Download class="w-4 h-4 mr-2" />
          {{ exportLoading ? '导出中...' : '导出用户数据' }}
        </Button>
      </div>
      <div class="flex-1 min-w-[200px]">
        <p class="text-sm text-muted-foreground mb-3">
          从 JSON 文件导入用户数据（需相同 ENCRYPTION_KEY）
        </p>
        <div class="flex items-center gap-2">
          <input
            ref="usersFileInput"
            type="file"
            accept=".json"
            class="hidden"
            @change="$emit('fileSelect', $event)"
          >
          <Button
            variant="outline"
            :disabled="importLoading"
            @click="triggerFileSelect"
          >
            <Upload class="w-4 h-4 mr-2" />
            {{ importLoading ? '导入中...' : '导入用户数据' }}
          </Button>
        </div>
      </div>
    </div>
  </CardSection>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Download, Upload } from 'lucide-vue-next'
import Button from '@/components/ui/button.vue'
import { CardSection } from '@/components/layout'

defineProps<{
  exportLoading: boolean
  importLoading: boolean
}>()

defineEmits<{
  export: []
  fileSelect: [event: Event]
}>()

const usersFileInput = ref<HTMLInputElement | null>(null)

function triggerFileSelect() {
  usersFileInput.value?.click()
}
</script>
