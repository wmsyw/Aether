<template>
  <section class="space-y-4" data-provider-user-attribution>
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold">{{ t('用户归因', 'User attribution') }} · {{ providerName }}</h3>
        <p class="mt-1 text-xs text-muted-foreground">{{ t('同一提供商、同一时段；实际成本为上游成本，规则计价与用户计费消耗分别展示，并非已登记支出。', 'Same provider and range. Upstream cost, rated usage and customer billing are distinct from recorded expenses.') }}</p>
      </div>
      <label class="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{{ t('指标', 'Metric') }}</span>
        <select class="h-8 rounded-md border bg-background px-2 text-foreground" :value="metric" @change="setMetric(($event.target as HTMLSelectElement).value)">
          <option value="actual_cost">{{ t('上游实际成本', 'Upstream actual cost') }}</option>
          <option value="total_cost">{{ t('计费消耗', 'Billable consumption') }}</option>
          <option value="tokens">Tokens</option>
          <option value="requests">{{ t('请求量', 'Requests') }}</option>
        </select>
      </label>
    </div>
    <OverviewStatus :loading="loading && !users" :error="error" @retry="refresh" />
    <Card class="min-w-0 overflow-hidden">
      <div class="overflow-x-auto px-4 sm:px-5">
        <table class="w-full min-w-[720px] text-sm">
          <thead class="border-b text-xs text-muted-foreground">
            <tr>
              <th class="w-12 py-3 text-left font-medium">#</th>
              <th class="py-3 text-left font-medium">{{ t('用户', 'User') }}</th>
              <th class="px-3 py-3 text-right font-medium">{{ t('请求量', 'Requests') }}</th>
              <th class="px-3 py-3 text-right font-medium">Tokens</th>
              <th class="px-3 py-3 text-right font-medium">{{ t('上游实际成本', 'Upstream actual cost') }}</th>
              <th class="px-3 py-3 text-right font-medium">{{ t('规则计价', 'Rated usage') }}</th>
              <th class="px-3 py-3 text-right font-medium">{{ t('计费消耗', 'Billable consumption') }}</th>
              <th class="py-3 text-right font-medium">{{ t('占比', 'Share') }}</th>
            </tr>
          </thead>
          <tbody class="divide-y">
            <tr v-for="(row, index) in rows" :key="row.user.user_id">
              <td class="py-3 tabular-nums text-muted-foreground">{{ offset + index + 1 }}</td>
              <td class="max-w-56 break-words py-3 font-medium">
                {{ row.user.username || row.user.email || row.user.user_id }}
                <span v-if="!row.user.is_active" class="ml-1 text-xs font-normal text-muted-foreground">({{ t('已停用', 'Inactive') }})</span>
              </td>
              <td class="px-3 py-3 text-right tabular-nums">{{ count(row.user.request_count) }}</td>
              <td class="px-3 py-3 text-right tabular-nums">{{ count(row.user.total_tokens) }}</td>
              <td class="px-3 py-3 text-right tabular-nums">{{ formatAmount(row.user.provider_cost_amount) }}</td>
              <td class="px-3 py-3 text-right tabular-nums">{{ formatAmount(row.user.rated_amount) }}</td>
              <td class="px-3 py-3 text-right tabular-nums">{{ formatAmount(row.user.billable_amount) }}</td>
              <td class="py-3 text-right tabular-nums">{{ formatShare(row.share) }}</td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="8" class="py-12 text-center text-muted-foreground">
                {{ loading ? t('加载用户归因…', 'Loading user attribution…') : error ? t('无法取得用户归因', 'User attribution unavailable') : t('此提供商在此时段暂无用户调用', 'No user requests for this provider in this range') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="users" class="px-4 pb-3 sm:px-5">
        <OverviewPagination :total="users.data.total" :limit="limit" :offset="offset" :loading="loading" @page="setPage" @size="setSize" />
      </div>
    </Card>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { OverviewAmount, OverviewRange } from '@/api/overview'
import { overviewApi } from '@/api/overview'
import { Card } from '@/components/ui'
import OverviewPagination from '../components/OverviewPagination.vue'
import OverviewStatus from '../components/OverviewStatus.vue'
import { useOverviewI18n } from '../i18n'
import { count, money, percent } from '../format'
import { useOverviewRequest } from '../useOverviewRequest'
import { buildUserAttributionRows, type AttributionMetric } from './attribution'

const props = defineProps<{ providerId: string; providerName: string; range: OverviewRange; revision: number }>()
const { t } = useOverviewI18n()
const metric = ref<AttributionMetric>('actual_cost')
const limit = ref(25)
const offset = ref(0)
watch(() => JSON.stringify([props.range, props.providerId]), () => { offset.value = 0 }, { flush: 'sync' })
const query = computed(() => ({
  ...props.range,
  provider_id: props.providerId,
  sort: metric.value === 'actual_cost' ? 'provider_cost_amount' : metric.value === 'total_cost' ? 'billable_amount' : metric.value === 'tokens' ? 'total_tokens' : 'request_count',
  order: 'desc' as const,
  limit: limit.value,
  offset: offset.value,
}))
const scope = computed(() => JSON.stringify([query.value, props.revision]))
const { data: users, loading: usersLoading, error: usersError, refresh: refreshUsers } = useOverviewRequest(
  scope,
  signal => overviewApi.users(query.value, signal),
  { scopeKey: scope },
)
const summaryQuery = computed(() => ({ ...props.range, provider_id: props.providerId }))
const { data: summary, loading: summaryLoading, error: summaryError, refresh: refreshSummary } = useOverviewRequest(
  () => JSON.stringify([summaryQuery.value, props.revision]),
  signal => overviewApi.summary(summaryQuery.value, signal),
  { scopeKey: () => JSON.stringify([summaryQuery.value, props.revision]) },
)
const loading = computed(() => usersLoading.value || summaryLoading.value)
const error = computed(() => usersError.value || summaryError.value)
const rows = computed(() => buildUserAttributionRows(users.value?.data, metric.value, summary.value?.data))
function refresh() { void refreshUsers(); void refreshSummary() }
function setMetric(value: string) {
  if (value === 'actual_cost' || value === 'total_cost' || value === 'tokens' || value === 'requests') {
    metric.value = value
    offset.value = 0
  }
}
function setPage(value: number) { offset.value = value }
function setSize(value: number) { limit.value = value; offset.value = 0 }
function formatAmount(amount: OverviewAmount | null | undefined): string {
  if (!amount || amount.status === 'unknown') return '-'
  const label = amount.status === 'known_subtotal' ? ` (${t('已知小计', 'Known subtotal')})` : ''
  return `${money(amount)}${label}`
}
function formatShare(value: number | null): string { return percent(value) }
</script>
