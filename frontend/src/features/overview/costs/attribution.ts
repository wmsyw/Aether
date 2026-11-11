import type { OverviewAmount, OverviewEmployee, OverviewMetrics, OverviewUsers } from '@/api/overview'

export type AttributionMetric = 'actual_cost' | 'total_cost' | 'tokens' | 'requests'

export interface UserAttributionRow {
  user: OverviewEmployee
  value: number | null
  share: number | null
}

export function amountValue(amount: OverviewAmount | null | undefined): number | null {
  if (!amount || amount.status === 'unknown' || amount.value == null) return null
  const value = Number(amount.value)
  return Number.isFinite(value) ? value : null
}

export function metricValue(metrics: OverviewMetrics, metric: AttributionMetric): number | null {
  switch (metric) {
    case 'actual_cost': return amountValue(metrics.provider_cost_amount)
    case 'total_cost': return amountValue(metrics.billable_amount)
    case 'tokens': return metrics.total_tokens
    case 'requests': return Number.isFinite(metrics.request_count) ? metrics.request_count : null
  }
}

export function buildUserAttributionRows(
  response: OverviewUsers | null | undefined,
  metric: AttributionMetric,
  summary: OverviewMetrics | null | undefined,
): UserAttributionRow[] {
  if (!response) return []
  const denominator = summary ? metricValue(summary, metric) : null
  const amount = metric === 'actual_cost' ? summary?.provider_cost_amount : metric === 'total_cost' ? summary?.billable_amount : null
  const complete = amount ? amount.status === 'known' : metric !== 'tokens' || !summary?.usage_source_counts?.unknown
  return response.items.map(user => {
    const value = metricValue(user, metric)
    const rowAmount = metric === 'actual_cost' ? user.provider_cost_amount : metric === 'total_cost' ? user.billable_amount : null
    const rowComplete = rowAmount ? rowAmount.status === 'known' && rowAmount.currency === amount?.currency : metric !== 'tokens' || !user.usage_source_counts?.unknown
    return {
      user,
      value,
      share: complete && rowComplete && value != null && denominator != null && denominator > 0 ? value / denominator : null,
    }
  })
}

