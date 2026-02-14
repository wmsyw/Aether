import { ref, computed, watch } from 'vue'
import type { ProviderWithEndpointsSummary } from '@/api/endpoints'

export interface FilterOption {
  value: string
  label: string
}

export function useProviderFilters(
  providers: () => ProviderWithEndpointsSummary[],
  globalModels: () => { id: string; name: string }[],
) {
  // 搜索与筛选
  const searchQuery = ref('')
  const filterStatus = ref('all')
  const filterApiFormat = ref('all')
  const filterModel = ref('all')

  const statusFilters: FilterOption[] = [
    { value: 'all', label: '全部状态' },
    { value: 'active', label: '活跃' },
    { value: 'inactive', label: '已停用' },
  ]

  const apiFormatFilters: FilterOption[] = [
    { value: 'all', label: '全部格式' },
    { value: 'claude:chat', label: 'Claude Chat' },
    { value: 'claude:cli', label: 'Claude CLI' },
    { value: 'openai:chat', label: 'OpenAI Chat' },
    { value: 'openai:cli', label: 'OpenAI CLI' },
    { value: 'gemini:chat', label: 'Gemini Chat' },
    { value: 'gemini:cli', label: 'Gemini CLI' },
  ]

  // 动态计算模型筛选选项：只展示当前提供商列表中实际关联的全局模型
  const modelFilters = computed<FilterOption[]>(() => {
    const usedIds = new Set(providers().flatMap(p => p.global_model_ids || []))
    const items = globalModels()
      .filter(m => usedIds.has(m.id))
      .map(m => ({ value: m.id, label: m.name }))
      .sort((a, b) => a.label.localeCompare(b.label))
    return [{ value: 'all', label: '全部模型' }, ...items]
  })

  const hasActiveFilters = computed(() => {
    return (
      searchQuery.value !== '' ||
      filterStatus.value !== 'all' ||
      filterApiFormat.value !== 'all' ||
      filterModel.value !== 'all'
    )
  })

  // 筛选后的提供商列表
  const filteredProviders = computed(() => {
    let result = [...providers()]

    // 搜索筛选（支持空格分隔的多关键词 AND 搜索）
    if (searchQuery.value.trim()) {
      const keywords = searchQuery.value
        .toLowerCase()
        .split(/\s+/)
        .filter(k => k.length > 0)
      result = result.filter(p => {
        const searchableText = `${p.name}`.toLowerCase()
        return keywords.every(keyword => searchableText.includes(keyword))
      })
    }

    // 状态筛选
    if (filterStatus.value !== 'all') {
      const isActive = filterStatus.value === 'active'
      result = result.filter(p => p.is_active === isActive)
    }

    // API 格式筛选
    if (filterApiFormat.value !== 'all') {
      result = result.filter(
        p => p.api_formats && p.api_formats.includes(filterApiFormat.value),
      )
    }

    // 模型筛选
    if (filterModel.value !== 'all') {
      result = result.filter(
        p => p.global_model_ids && p.global_model_ids.includes(filterModel.value),
      )
    }

    // 排序
    return result.sort((a, b) => {
      // 1. 优先显示活跃的提供商
      if (a.is_active !== b.is_active) {
        return a.is_active ? -1 : 1
      }
      // 2. 按优先级排序
      if (a.provider_priority !== b.provider_priority) {
        return a.provider_priority - b.provider_priority
      }
      // 3. 按名称排序
      return a.name.localeCompare(b.name)
    })
  })

  // 分页
  const currentPage = ref(1)
  const pageSize = ref(20)

  const paginatedProviders = computed(() => {
    const start = (currentPage.value - 1) * pageSize.value
    const end = start + pageSize.value
    return filteredProviders.value.slice(start, end)
  })

  // 搜索/筛选时重置分页
  watch([searchQuery, filterStatus, filterApiFormat, filterModel], () => {
    currentPage.value = 1
  })

  function resetFilters() {
    searchQuery.value = ''
    filterStatus.value = 'all'
    filterApiFormat.value = 'all'
    filterModel.value = 'all'
  }

  return {
    searchQuery,
    filterStatus,
    filterApiFormat,
    filterModel,
    statusFilters,
    apiFormatFilters,
    modelFilters,
    hasActiveFilters,
    filteredProviders,
    currentPage,
    pageSize,
    paginatedProviders,
    resetFilters,
  }
}
