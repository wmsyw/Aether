<script setup lang="ts">
import type { ProxyNode } from '@/api/proxy-nodes'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui'
import { Cpu } from 'lucide-vue-next'

defineProps<{ node: ProxyNode }>()

function formatMemory(mb: number | null) {
  if (mb == null) return '-'
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

function formatNumber(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
</script>

<template>
  <Popover v-if="!node.is_manual && node.hardware_info">
    <PopoverTrigger as-child>
      <button
        type="button"
        class="inline-flex items-center justify-center rounded-sm p-0.5 hover:bg-muted/60 transition-colors"
      >
        <Cpu class="h-3.5 w-3.5 text-muted-foreground" />
      </button>
    </PopoverTrigger>
    <PopoverContent
      side="right"
      :side-offset="8"
      class="w-auto p-3 text-xs space-y-1"
    >
      <div v-if="node.hardware_info.cpu_cores">
        CPU: {{ node.hardware_info.cpu_cores }} cores
      </div>
      <div v-if="node.hardware_info.total_memory_mb">
        RAM: {{ formatMemory(node.hardware_info.total_memory_mb) }}
      </div>
      <div v-if="node.hardware_info.os_info">
        OS: {{ node.hardware_info.os_info }}
      </div>
      <div v-if="node.estimated_max_concurrency">
        Max Concurrency: ~{{ formatNumber(node.estimated_max_concurrency) }}
      </div>
      <div v-if="node.hardware_info.fd_limit">
        FD Limit: {{ formatNumber(node.hardware_info.fd_limit) }}
      </div>
    </PopoverContent>
  </Popover>
</template>
