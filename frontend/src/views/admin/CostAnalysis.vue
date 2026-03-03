<template>
  <div class="space-y-6 px-4 sm:px-6 lg:px-0">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div>
        <h1 class="text-lg font-semibold">
          成本分析
        </h1>
        <p class="text-xs text-muted-foreground">
          成本趋势、预测与节省统计
        </p>
      </div>
      <TimeRangePicker v-model="timeRange" />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card class="p-4 space-y-2">
        <div class="text-xs text-muted-foreground">
          缓存节省
        </div>
        <div class="text-lg font-semibold">
          {{ formatCurrency(costSavings?.cache_savings ?? 0) }}
        </div>
        <div class="text-xs text-muted-foreground">
          读取成本 {{ formatCurrency(costSavings?.cache_read_cost ?? 0) }}
        </div>
      </Card>
      <Card class="p-4 space-y-2">
        <div class="text-xs text-muted-foreground">
          缓存读取 Tokens
        </div>
        <div class="text-lg font-semibold">
          {{ formatTokens(costSavings?.cache_read_tokens ?? 0) }}
        </div>
        <div class="text-xs text-muted-foreground">
          预计全额成本 {{ formatCurrency(costSavings?.estimated_full_cost ?? 0) }}
        </div>
      </Card>
      <Card class="p-4 space-y-2">
        <div class="text-xs text-muted-foreground">
          缓存创建成本
        </div>
        <div class="text-lg font-semibold">
          {{ formatCurrency(costSavings?.cache_creation_cost ?? 0) }}
        </div>
        <div class="text-xs text-muted-foreground">
          基于当前时间范围
        </div>
      </Card>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card class="p-4">
        <CostForecastChart
          title="成本趋势预测"
          :history="forecastHistory"
          :forecast="forecastFuture"
          :loading="forecastLoading"
        />
      </Card>
      <QuotaProgressCard
        title="月卡消耗进度"
        :providers="quotaProviders"
        :loading="quotaLoading"
      />
    </div>

    <UsageProviderTable
      :data="providerStats"
      :is-admin="true"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import Card from '@/components/ui/card.vue'
import { TimeRangePicker } from '@/components/common'
import { CostForecastChart, QuotaProgressCard } from '@/components/stats'
import { UsageProviderTable } from '@/features/usage/components'
import { adminApi, type CostForecastResponse, type CostSavingsResponse, type QuotaUsageProvider } from '@/api/admin'
import { usageApi } from '@/api/usage'
import { formatCurrency, formatTokens } from '@/utils/format'
import { getDateRangeFromPeriod } from '@/features/usage/composables'
import type { DateRangeParams } from '@/features/usage/types'
import type { ProviderStatsItem } from '@/features/usage/types'

const timeRange = ref<DateRangeParams>(getDateRangeFromPeriod('last30days'))

const forecast = ref<CostForecastResponse | null>(null)
const costSavings = ref<CostSavingsResponse | null>(null)
const quotaProviders = ref<QuotaUsageProvider[]>([])
const providerStats = ref<ProviderStatsItem[]>([])

const forecastLoading = ref(false)
const quotaLoading = ref(false)
let forecastRequestId = 0
let savingsRequestId = 0
let quotaRequestId = 0
let providerStatsRequestId = 0
let loadAllPromise: Promise<void> | null = null
let hasPendingLoadAll = false
let loadAllDebounceTimer: ReturnType<typeof setTimeout> | null = null

const forecastHistory = computed(() => forecast.value?.history || [])
const forecastFuture = computed(() => forecast.value?.forecast || [])

function buildTimeRangeParams() {
  return {
    start_date: timeRange.value.start_date,
    end_date: timeRange.value.end_date,
    preset: timeRange.value.preset,
    timezone: timeRange.value.timezone,
    tz_offset_minutes: timeRange.value.tz_offset_minutes
  }
}

async function loadForecast() {
  const requestId = ++forecastRequestId
  forecastLoading.value = true
  try {
    const data = await adminApi.getCostForecast(buildTimeRangeParams())
    if (requestId !== forecastRequestId) return
    forecast.value = data
  } finally {
    if (requestId === forecastRequestId) {
      forecastLoading.value = false
    }
  }
}

async function loadSavings() {
  const requestId = ++savingsRequestId
  const data = await adminApi.getCostSavings(buildTimeRangeParams())
  if (requestId !== savingsRequestId) return
  costSavings.value = data
}

async function loadQuotaUsage() {
  const requestId = ++quotaRequestId
  quotaLoading.value = true
  try {
    const response = await adminApi.getQuotaUsage()
    if (requestId !== quotaRequestId) return
    quotaProviders.value = response.providers
  } finally {
    if (requestId === quotaRequestId) {
      quotaLoading.value = false
    }
  }
}

async function loadProviderStats() {
  const requestId = ++providerStatsRequestId
  const stats = await usageApi.getUsageByProvider({
    ...buildTimeRangeParams(),
    limit: 8
  })
  if (requestId !== providerStatsRequestId) return
  providerStats.value = stats
}

async function loadAll() {
  if (loadAllPromise) {
    hasPendingLoadAll = true
    return loadAllPromise
  }
  loadAllPromise = Promise.all([loadForecast(), loadSavings(), loadQuotaUsage(), loadProviderStats()])
    .then(() => undefined)
    .finally(() => {
      loadAllPromise = null
      if (hasPendingLoadAll) {
        hasPendingLoadAll = false
        void loadAll()
      }
    })
  return loadAllPromise
}

function scheduleLoadAll() {
  if (loadAllDebounceTimer) {
    clearTimeout(loadAllDebounceTimer)
  }
  loadAllDebounceTimer = setTimeout(() => {
    loadAllDebounceTimer = null
    void loadAll()
  }, 120)
}

watch(timeRange, scheduleLoadAll, { deep: true })

onMounted(() => {
  void loadAll()
})

onUnmounted(() => {
  if (loadAllDebounceTimer) {
    clearTimeout(loadAllDebounceTimer)
    loadAllDebounceTimer = null
  }
  hasPendingLoadAll = false
  loadAllPromise = null
  forecastRequestId += 1
  savingsRequestId += 1
  quotaRequestId += 1
  providerStatsRequestId += 1
})
</script>
