import { ref, computed, watch, nextTick, type Ref, type ComputedRef } from 'vue'

/**
 * 智能分页 composable
 *
 * 根据列表容器的实际渲染高度自动决定是否分页以及每页条数。
 * 当列表总高度超过阈值时自动启用分页，低于阈值时恢复全量显示。
 *
 * @param items        响应式数据源（全量列表）
 * @param listRef      列表容器 DOM 引用
 * @param maxHeight    触发分页的高度阈值（px），默认 500
 */
export function useSmartPagination<T>(
  items: ComputedRef<T[]> | Ref<T[]>,
  listRef: Ref<HTMLElement | null>,
  maxHeight = 500,
) {
  const currentPage = ref(1)
  const itemsPerPage = ref(0) // 0 = 不分页
  const cachedAvgItemHeight = ref(0)

  const shouldPaginate = computed(() => {
    return itemsPerPage.value > 0 && items.value.length > itemsPerPage.value
  })

  const paginatedItems = computed(() => {
    if (!shouldPaginate.value) return items.value
    const start = (currentPage.value - 1) * itemsPerPage.value
    return items.value.slice(start, start + itemsPerPage.value)
  })

  const totalPages = computed(() => {
    if (!shouldPaginate.value) return 1
    return Math.ceil(items.value.length / itemsPerPage.value)
  })

  /** 将当前页内的局部索引转换为全局索引 */
  function getGlobalIndex(localIdx: number): number {
    if (!shouldPaginate.value) return localIdx
    return (currentPage.value - 1) * itemsPerPage.value + localIdx
  }

  /** 检测是否需要分页并计算每页条数 */
  function detect() {
    const el = listRef.value
    if (!el || items.value.length <= 2) {
      itemsPerPage.value = 0
      return
    }

    const scrollHeight = el.scrollHeight
    const renderedCount = paginatedItems.value.length

    if (renderedCount > 0 && scrollHeight > 0) {
      cachedAvgItemHeight.value = scrollHeight / renderedCount
    }

    const estimatedTotalHeight = cachedAvgItemHeight.value * items.value.length
    if (estimatedTotalHeight > maxHeight && cachedAvgItemHeight.value > 0) {
      itemsPerPage.value = Math.max(Math.floor(maxHeight / cachedAvgItemHeight.value), 3)
      const maxPage = Math.ceil(items.value.length / itemsPerPage.value)
      if (currentPage.value > maxPage) {
        currentPage.value = maxPage
      }
    } else {
      itemsPerPage.value = 0
    }
  }

  /** 重置分页状态（数据源切换时调用） */
  function reset() {
    currentPage.value = 1
    itemsPerPage.value = 0
    cachedAvgItemHeight.value = 0
  }

  // 数据源变化时自动重新检测（immediate 确保首次挂载时也检测）
  watch(items, () => {
    currentPage.value = 1
    nextTick(detect)
  }, { immediate: true, flush: 'post' })

  return {
    currentPage,
    totalPages,
    shouldPaginate,
    paginatedItems,
    getGlobalIndex,
    detect,
    reset,
  }
}
