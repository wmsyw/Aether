/**
 * 字段钩子注册表
 *
 * 处理 schema 中 x-field-hooks 定义的客户端逻辑，
 * 如从 Cookie 解析 user_id 等。
 */

/**
 * 钩子函数签名
 * @param value 触发字段的值
 * @returns 目标字段的值，返回 null 表示不填充
 */
type FieldHookFn = (value: string) => string | null

/**
 * 钩子注册表
 */
const hooks: Record<string, FieldHookFn> = {
  parse_new_api_user_id: parseNewApiUserId,
}

/**
 * 执行字段钩子
 * @param action 钩子 action 名称
 * @param value 触发字段的值
 * @returns 目标字段的值，未找到钩子返回 null
 */
export function executeFieldHook(action: string, value: string): string | null {
  const fn = hooks[action]
  if (!fn) return null
  return fn(value)
}

// ==================== 钩子实现 ====================

/**
 * 从 New API session cookie 解析用户 ID
 *
 * New API 的 session cookie 格式:
 * base64(timestamp|gob_base64|signature)
 *
 * gob 数据中包含 id 和 username 字段
 *
 * 支持两种输入：
 * 1. 完整 Cookie: "session=xxx; acw_tc=xxx; ..."
 * 2. 仅 session 值: "MTc2ODc4..."
 */
function parseNewApiUserId(cookie: string): string | null {
  try {
    // 提取 session 值
    let sessionValue = cookie.trim()
    if (sessionValue.includes('session=')) {
      const match = sessionValue.match(/session=([^;]+)/)
      if (match) {
        sessionValue = match[1]
      }
    }

    // URL-safe base64 解码
    const padding = 4 - (sessionValue.length % 4)
    if (padding !== 4) {
      sessionValue += '='.repeat(padding)
    }
    const standardBase64 = sessionValue.replace(/-/g, '+').replace(/_/g, '/')
    const decoded = atob(standardBase64)

    // 分割: timestamp|gob_base64|signature
    const parts = decoded.split('|')
    if (parts.length < 2) return null

    // 解码 gob 数据（第二部分）
    let gobB64 = parts[1]
    const gobPadding = 4 - (gobB64.length % 4)
    if (gobPadding !== 4) {
      gobB64 += '='.repeat(gobPadding)
    }
    const gobStandardB64 = gobB64.replace(/-/g, '+').replace(/_/g, '/')
    const gobData = atob(gobStandardB64)

    // 解析 gob 编码的 id 字段
    const idIntPattern = '\x02id\x03int'
    const idIdx = gobData.indexOf(idIntPattern)
    if (idIdx === -1) return null

    // 跳过 "\x02id\x03int" (7字节) 和类型标记 (2字节)
    const valueStart = idIdx + 7 + 2
    if (valueStart >= gobData.length) return null

    const firstByte = gobData.charCodeAt(valueStart)
    if (firstByte !== 0) return null

    // 下一个字节是长度标记
    const marker = gobData.charCodeAt(valueStart + 1)
    if (marker < 0x80) return null

    const length = 256 - marker
    if (valueStart + 2 + length > gobData.length) return null

    // 读取 length 字节，大端序转整数
    let val = 0
    for (let i = 0; i < length; i++) {
      val = (val << 8) | gobData.charCodeAt(valueStart + 2 + i)
    }
    // gob zigzag 解码：正整数用 2*n 编码
    return (val >> 1).toString()
  } catch {
    return null
  }
}
