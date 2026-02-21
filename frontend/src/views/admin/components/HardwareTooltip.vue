<script setup lang="ts">
import type { ProxyNode } from '@/api/proxy-nodes'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Cpu } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{ node: ProxyNode }>()

const hardwareInfo = computed<Record<string, unknown> | null>(() => {
  const info = props.node.hardware_info
  if (info == null) return null
  if (typeof info === 'string') {
    try {
      const parsed = JSON.parse(info)
      if (parsed && typeof parsed === 'object') return parsed as Record<string, unknown>
    } catch {
      return {}
    }
    return {}
  }
  if (typeof info === 'object') return info as Record<string, unknown>
  return {}
})

const hardwareRows = computed(() => {
  const info = hardwareInfo.value ?? {}
  const rows: Array<{ label: string; value: string }> = []

  const cpuObj = info.cpu as Record<string, unknown> | undefined
  const cpuCores = pickNumber(info.cpu_cores, info.cpu_count, cpuObj?.cores)
  if (cpuCores != null) {
    rows.push({ label: 'CPU', value: `${cpuCores} cores` })
  }

  const memObj = info.memory as Record<string, unknown> | undefined
  const memoryMb = pickNumber(
    info.total_memory_mb,
    info.memory_total_mb,
    info.memory_mb,
    memObj?.total_mb
  )
  if (memoryMb != null) {
    rows.push({ label: 'RAM', value: formatMemory(memoryMb) })
  }

  const osInfo = pickString(info.os_info, info.os, info.platform)
  if (osInfo) {
    rows.push({ label: 'OS', value: osInfo })
  }

  if (props.node.estimated_max_concurrency != null) {
    rows.push({
      label: 'Max Concurrency',
      value: `~${formatNumber(props.node.estimated_max_concurrency)}`,
    })
  }

  const fdLimit = pickNumber(info.fd_limit, info.file_descriptor_limit, info.ulimit_nofile)
  if (fdLimit != null) {
    rows.push({ label: 'FD Limit', value: formatNumber(fdLimit) })
  }

  return rows
})

const showHardwareInfo = computed(
  () =>
    !props.node.is_manual
    && (hardwareInfo.value !== null || props.node.estimated_max_concurrency != null)
)

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

function pickNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (value == null) continue
    const parsed = typeof value === 'number' ? value : Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function pickString(...values: unknown[]): string {
  for (const value of values) {
    if (value == null) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}


</script>

<template>
  <TooltipProvider
    v-if="showHardwareInfo"
    :delay-duration="0"
  >
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          aria-label="硬件信息"
          class="inline-flex items-center justify-center rounded-sm p-0.5 hover:bg-muted/60 transition-colors cursor-help"
        >
          <Cpu class="h-3.5 w-3.5 text-muted-foreground" />
        </span>
      </TooltipTrigger>
      <TooltipContent
        side="right"
        :side-offset="8"
        class="w-auto px-3 py-2 text-xs space-y-1"
      >
        <div
          v-if="hardwareRows.length === 0"
          class="text-muted-foreground"
        >
          暂无硬件信息上报
        </div>
        <template v-else>
          <div
            v-for="row in hardwareRows"
            :key="row.label"
          >
            {{ row.label }}: {{ row.value }}
          </div>
        </template>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
