import { describe, expect, it } from 'vitest'
import type { OverviewAmount, OverviewEmployee, OverviewMetrics, OverviewUsers } from '@/api/overview'
import { buildUserAttributionRows, metricValue } from '../costs/attribution'

function amount(value: string | null, basis: string, status = 'known'): OverviewAmount {
  return { value, basis, status, currency: 'USD' }
}
const user = {
  user_id: 'user-1', username: 'Ada', email: null, is_active: true,
  request_count: 4, total_tokens: 60,
  provider_cost_amount: amount('2', 'provider_cost'),
  rated_amount: amount('8', 'rated'), billable_amount: amount('12', 'billable'),
} as OverviewEmployee
const summary = {
  request_count: 20, total_tokens: 300,
  provider_cost_amount: amount('10', 'provider_cost'),
  rated_amount: amount('20', 'rated'), billable_amount: amount('60', 'billable'),
} as OverviewMetrics
const page: OverviewUsers = { items: [user], total: 42, offset: 25, limit: 25 }

describe('provider user attribution', () => {
  it('keeps procurement, rated and billable costs distinct', () => {
    expect(metricValue(user, 'actual_cost')).toBe(2)
    expect(metricValue(user, 'total_cost')).toBe(12)
    expect(metricValue(user, 'tokens')).toBe(60)
    expect(metricValue(user, 'requests')).toBe(4)
  })

  it.each(['actual_cost', 'total_cost', 'tokens', 'requests'] as const)('uses the complete filtered provider total for %s, not page totals', metric => {
    expect(buildUserAttributionRows(page, metric, summary)[0]?.share).toBe(0.2)
  })

  it('does not invent zero or a share when an upstream cost is missing or partial', () => {
    const unknown = { ...user, provider_cost_amount: amount(null, 'provider_cost', 'unknown') }
    expect(buildUserAttributionRows({ ...page, items: [unknown] }, 'actual_cost', summary)[0]).toMatchObject({ value: null, share: null })
    const partial = { ...summary, provider_cost_amount: amount('10', 'provider_cost', 'known_subtotal') }
    expect(buildUserAttributionRows(page, 'actual_cost', partial)[0]?.share).toBeNull()
    expect(buildUserAttributionRows(page, 'actual_cost', null)[0]?.share).toBeNull()
    expect(buildUserAttributionRows(page, 'requests', { ...summary, request_count: 0 })[0]?.share).toBeNull()
  })
})
