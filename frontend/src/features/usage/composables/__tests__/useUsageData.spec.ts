import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const mockedUsageApi = vi.hoisted(() => ({
  getUsageStats: vi.fn(),
  getUsageByModel: vi.fn(),
  getUsageByProvider: vi.fn(),
  getUsageByApiFormat: vi.fn(),
}))

vi.mock('@/api/usage', () => ({
  usageApi: {
    getUsageStats: mockedUsageApi.getUsageStats,
    getUsageByModel: mockedUsageApi.getUsageByModel,
    getUsageByProvider: mockedUsageApi.getUsageByProvider,
    getUsageByApiFormat: mockedUsageApi.getUsageByApiFormat,
  },
}))

vi.mock('@/api/me', () => ({
  meApi: {
    getUsage: vi.fn(),
  },
}))

vi.mock('@/utils/logger', () => ({
  log: {
    error: vi.fn(),
  },
}))

vi.mock('@/types/api-error', () => ({
  getErrorStatus: vi.fn(() => undefined),
}))

import { useUsageData } from '../useUsageData'

describe('useUsageData', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    mockedUsageApi.getUsageStats.mockResolvedValue({
      total_requests: 0,
      total_tokens: 0,
      total_cost: 0,
      avg_response_time: 0,
    })
    mockedUsageApi.getUsageByModel.mockResolvedValue([])
    mockedUsageApi.getUsageByProvider.mockResolvedValue([])
    mockedUsageApi.getUsageByApiFormat.mockResolvedValue([])
  })

  it('passes bypassCache option to all admin aggregation requests', async () => {
    const isAdminPage = ref(true)
    const { loadStats } = useUsageData({ isAdminPage })

    const dateRange = { preset: 'today' }
    const requestOptions = { bypassCache: true }

    await loadStats(dateRange, requestOptions)

    expect(mockedUsageApi.getUsageStats).toHaveBeenCalledWith(dateRange, requestOptions)
    expect(mockedUsageApi.getUsageByModel).toHaveBeenCalledWith(dateRange, requestOptions)
    expect(mockedUsageApi.getUsageByProvider).toHaveBeenCalledWith(dateRange, requestOptions)
    expect(mockedUsageApi.getUsageByApiFormat).toHaveBeenCalledWith(dateRange, requestOptions)
  })
})
