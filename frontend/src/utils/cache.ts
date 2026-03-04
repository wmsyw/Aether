/**
 * 简单的内存缓存实现
 * 用于缓存API响应，减少重复请求
 */

interface CacheItem<T> {
  data: T
  timestamp: number
  ttl: number // 生存时间（毫秒）
}

class MemoryCache {
  private cache: Map<string, CacheItem<unknown>> = new Map()
  private inFlight: Map<string, Promise<unknown>> = new Map()
  private defaultTTL = 60000 // 默认缓存60秒

  /**
   * 设置缓存
   * @param key 缓存键
   * @param data 缓存数据
   * @param ttl 生存时间（毫秒）
   */
  set<T>(key: string, data: T, ttl: number = this.defaultTTL): void {
    this.cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl
    })
  }

  /**
   * 获取缓存
   * @param key 缓存键
   * @returns 缓存数据或null
   */
  get<T>(key: string): T | null {
    const item = this.cache.get(key)

    if (!item) {
      return null
    }

    // 检查是否过期
    if (Date.now() - item.timestamp > item.ttl) {
      this.cache.delete(key)
      return null
    }

    return item.data as T
  }

  /**
   * 删除缓存
   * @param key 缓存键
   */
  delete(key: string): void {
    this.cache.delete(key)
  }

  /**
   * 清空所有缓存
   */
  clear(): void {
    this.cache.clear()
    this.inFlight.clear()
  }

  /**
   * 清理过期缓存
   */
  cleanup(): void {
    const now = Date.now()
    for (const [key, item] of this.cache.entries()) {
      if (now - item.timestamp > item.ttl) {
        this.cache.delete(key)
      }
    }
  }

  /**
   * 获取缓存大小
   */
  size(): number {
    return this.cache.size
  }

  /**
   * 获取进行中的请求
   */
  getInFlight<T>(key: string): Promise<T> | null {
    return (this.inFlight.get(key) as Promise<T> | undefined) ?? null
  }

  /**
   * 标记进行中的请求
   */
  setInFlight<T>(key: string, promise: Promise<T>): void {
    this.inFlight.set(key, promise as Promise<unknown>)
  }

  /**
   * 清除进行中的请求
   */
  deleteInFlight(key: string): void {
    this.inFlight.delete(key)
  }
}

// 创建全局缓存实例
export const cache = new MemoryCache()

// 每5分钟清理一次过期缓存
setInterval(() => {
  cache.cleanup()
}, 5 * 60 * 1000)

/**
 * 带缓存的请求包装器
 * @param key 缓存键
 * @param fetcher 数据获取函数
 * @param ttl 缓存时间（毫秒）
 */
export async function cachedRequest<T>(
  key: string,
  fetcher: () => Promise<T>,
  ttl?: number
): Promise<T> {
  // 尝试从缓存获取
  if (ttl !== 0) {
    const cached = cache.get<T>(key)
    if (cached !== null) {
      return cached
    }
  }

  // 命中进行中的同 key 请求，直接复用
  const inFlight = cache.getInFlight<T>(key)
  if (inFlight) {
    return inFlight
  }

  // 缓存未命中，执行请求并登记为 in-flight
  const request = (async () => {
    try {
      const data = await fetcher()
      if (ttl !== 0) {
        cache.set(key, data, ttl)
      }
      return data
    } finally {
      cache.deleteInFlight(key)
    }
  })()

  cache.setInFlight(key, request)
  return request
}

/**
 * 仅做请求去重（不缓存结果）
 * 相同 key 的并发请求会复用同一个 Promise
 */
export function dedupedRequest<T>(
  key: string,
  fetcher: () => Promise<T>,
): Promise<T> {
  return cachedRequest(key, fetcher, 0)
}

/**
 * 构建归一化的缓存 key
 * 将 params 的 key 排序并过滤 undefined 值，确保相同参数生成相同 key
 */
export function buildCacheKey(prefix: string, params?: Record<string, unknown>): string {
  if (!params) {
    return prefix
  }
  const normalizedParams = Object.entries(params)
    .filter(([, value]) => value !== undefined)
    .sort(([a], [b]) => a.localeCompare(b))
  if (normalizedParams.length === 0) {
    return prefix
  }
  return `${prefix}:${JSON.stringify(normalizedParams)}`
}

export default cache
