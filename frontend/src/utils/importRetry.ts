/**
 * 带重试机制和缓存处理的动态导入工具
 */

const MAX_RETRIES = 3
const RETRY_DELAY = 1000 // 1秒
const CACHE_BUSTER_DELAY = 2000 // 2秒后尝试缓存清除

// 模块缓存
const moduleCache = new Map<string, Promise<unknown>>()

/**
 * 清除浏览器缓存的工具函数
 */
function clearBrowserCache() {
  if (typeof window !== 'undefined') {
    // 清除一些可能的缓存
    if ('caches' in window) {
      caches.keys().then(names => {
        names.forEach(name => {
          caches.delete(name)
        })
      })
    }
  }
}

/**
 * 检查错误是否是网络/缓存相关
 */
function isNetworkOrCacheError(error: unknown): boolean {
  const err = error as { message?: string; name?: string } | null
  const errorMessage = err?.message || ''
  return (
    errorMessage.includes('Failed to fetch') ||
    errorMessage.includes('Loading chunk') ||
    errorMessage.includes('dynamically imported module') ||
    errorMessage.includes('NetworkError') ||
    err?.name === 'ChunkLoadError'
  )
}

/**
 * 重试动态导入
 * @param importFn 动态导入函数
 * @param retries 剩余重试次数
 * @param cacheKey 缓存键
 * @returns Promise
 */
export async function importWithRetry<T = unknown>(
  importFn: () => Promise<T>,
  retries: number = MAX_RETRIES,
  cacheKey?: string
): Promise<T> {
  try {
    // 如果有缓存键且缓存中存在，直接返回
    if (cacheKey && moduleCache.has(cacheKey)) {
      return await moduleCache.get(cacheKey) as T
    }

    const importPromise = importFn()

    // 缓存 Promise
    if (cacheKey) {
      moduleCache.set(cacheKey, importPromise)
    }

    const result = await importPromise
    return result
  } catch (error) {
    // 如果是缓存相关错误，清除对应缓存
    if (cacheKey && moduleCache.has(cacheKey)) {
      moduleCache.delete(cacheKey)
    }

    if (retries > 0 && isNetworkOrCacheError(error)) {
      // 如果是第二次重试，尝试清除浏览器缓存
      if (MAX_RETRIES - retries + 1 === 2) {
        clearBrowserCache()
        await new Promise(resolve => setTimeout(resolve, CACHE_BUSTER_DELAY))
      } else {
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAY))
      }

      return importWithRetry(importFn, retries - 1, cacheKey)
    } else {
      // 最后的fallback：如果是网络/缓存错误，刷新页面
      if (isNetworkOrCacheError(error) && typeof window !== 'undefined') {
        // 添加一个时间戳参数来强制刷新
        const url = new URL(window.location.href)
        url.searchParams.set('_t', Date.now().toString())
        window.location.href = url.toString()
      }
      throw error
    }
  }
}

/**
 * 创建带重试的组件导入函数
 * @param importPath 组件路径
 * @returns 组件导入函数
 */
export function createRetryableImport(importPath: string) {
  const cacheKey = importPath
  return () => importWithRetry(() => import(/* @vite-ignore */ importPath), MAX_RETRIES, cacheKey)
}

/**
 * 预加载关键模块
 */
export function preloadCriticalModules() {
  // 在开发环境中预加载已被禁用，因为路径别名在运行时动态导入中不可用
  // 模块会在需要时按需加载，这在开发环境中是可接受的
  // 生产环境中模块已经被构建和优化，不需要预加载
}