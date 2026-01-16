<template>
  <div class="max-h-[500px] overflow-y-auto scrollbar-gutter-stable">
    <div class="flex flex-col gap-3 p-1">
      <!-- 渲染错误提示 -->
      <div
        v-if="renderResult.error"
        class="flex items-center gap-2 p-3 bg-destructive/10 border border-destructive/30 rounded-lg text-destructive text-[13px]"
      >
        <AlertCircle class="w-4 h-4 shrink-0" />
        <span>{{ renderResult.error }}</span>
      </div>

      <!-- 空内容提示 -->
      <div
        v-else-if="renderResult.blocks.length === 0"
        class="text-sm text-muted-foreground"
      >
        {{ emptyMessage }}
      </div>

      <!-- 渲染内容块 -->
      <template v-else>
        <BlockRenderer :blocks="renderResult.blocks" />

        <!-- 流式响应标记 -->
        <div
          v-if="renderResult.isStream"
          class="flex items-center gap-1 px-2 py-1 text-[11px] text-muted-foreground bg-muted/30 rounded w-fit"
        >
          <Zap class="w-3 h-3" />
          <span>流式响应</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { AlertCircle, Zap } from 'lucide-vue-next'
import BlockRenderer from './BlockRenderer.vue'
import type { RenderResult } from '../../conversation'

defineProps<{
  renderResult: RenderResult
  emptyMessage: string
}>()
</script>
