<template>
  <CardSection
    title="配置管理"
    description="导出或导入提供商和模型配置，便于备份或迁移"
  >
    <div class="flex flex-wrap gap-4">
      <div class="flex-1 min-w-[200px]">
        <p class="text-sm text-muted-foreground mb-3">
          导出当前所有提供商、端点、API Key 和模型配置到 JSON 文件
        </p>
        <Button
          variant="outline"
          :disabled="exportLoading"
          @click="$emit('export')"
        >
          <Download class="w-4 h-4 mr-2" />
          {{ exportLoading ? '导出中...' : '导出配置' }}
        </Button>
      </div>
      <div class="flex-1 min-w-[200px]">
        <p class="text-sm text-muted-foreground mb-3">
          从 JSON 文件导入配置，支持跳过、覆盖或报错三种冲突处理模式
        </p>
        <div class="flex items-center gap-2">
          <input
            ref="configFileInput"
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
            {{ importLoading ? '导入中...' : '导入配置' }}
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

const configFileInput = ref<HTMLInputElement | null>(null)

function triggerFileSelect() {
  configFileInput.value?.click()
}
</script>
