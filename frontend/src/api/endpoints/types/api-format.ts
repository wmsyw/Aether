// API 格式常量
export const API_FORMATS = {
  // 新模式：endpoint signature key（family:kind，全小写）
  CLAUDE: 'claude:chat',
  CLAUDE_CLI: 'claude:cli',
  OPENAI: 'openai:chat',
  OPENAI_CLI: 'openai:cli',
  OPENAI_COMPACT: 'openai:compact',
  OPENAI_VIDEO: 'openai:video',
  GEMINI: 'gemini:chat',
  GEMINI_CLI: 'gemini:cli',
  GEMINI_VIDEO: 'gemini:video',
} as const

export type APIFormat = typeof API_FORMATS[keyof typeof API_FORMATS]

// API 格式显示名称映射（按品牌分组：Chat 在前，CLI/Video 在后）
export const API_FORMAT_LABELS: Record<string, string> = {
  [API_FORMATS.CLAUDE]: 'Claude Chat',
  [API_FORMATS.CLAUDE_CLI]: 'Claude CLI',
  [API_FORMATS.OPENAI]: 'OpenAI Chat',
  [API_FORMATS.OPENAI_CLI]: 'OpenAI CLI',
  [API_FORMATS.OPENAI_COMPACT]: 'OpenAI Compact',
  [API_FORMATS.OPENAI_VIDEO]: 'OpenAI Video',
  [API_FORMATS.GEMINI]: 'Gemini Chat',
  [API_FORMATS.GEMINI_CLI]: 'Gemini CLI',
  [API_FORMATS.GEMINI_VIDEO]: 'Gemini Video',
  // legacy 兼容（仅用于展示历史数据）
  CLAUDE: 'Claude Chat',
  CLAUDE_CLI: 'Claude CLI',
  OPENAI: 'OpenAI Chat',
  OPENAI_CLI: 'OpenAI CLI',
  OPENAI_COMPACT: 'OpenAI Compact',
  OPENAI_VIDEO: 'OpenAI Video',
  GEMINI: 'Gemini Chat',
  GEMINI_CLI: 'Gemini CLI',
  GEMINI_VIDEO: 'Gemini Video',
}

// API 格式缩写映射（用于空间紧凑的显示场景）
export const API_FORMAT_SHORT: Record<string, string> = {
  [API_FORMATS.OPENAI]: 'O',
  [API_FORMATS.OPENAI_CLI]: 'OC',
  [API_FORMATS.OPENAI_COMPACT]: 'OCP',
  [API_FORMATS.OPENAI_VIDEO]: 'OV',
  [API_FORMATS.CLAUDE]: 'C',
  [API_FORMATS.CLAUDE_CLI]: 'CC',
  [API_FORMATS.GEMINI]: 'G',
  [API_FORMATS.GEMINI_CLI]: 'GC',
  [API_FORMATS.GEMINI_VIDEO]: 'GV',
  // legacy 兼容（仅用于展示历史数据）
  OPENAI: 'O',
  OPENAI_CLI: 'OC',
  OPENAI_COMPACT: 'OCP',
  OPENAI_VIDEO: 'OV',
  CLAUDE: 'C',
  CLAUDE_CLI: 'CC',
  GEMINI: 'G',
  GEMINI_CLI: 'GC',
  GEMINI_VIDEO: 'GV',
}

// API 格式排序顺序（统一的显示顺序）
export const API_FORMAT_ORDER: string[] = [
  API_FORMATS.OPENAI,
  API_FORMATS.OPENAI_CLI,
  API_FORMATS.OPENAI_COMPACT,
  API_FORMATS.OPENAI_VIDEO,
  API_FORMATS.CLAUDE,
  API_FORMATS.CLAUDE_CLI,
  API_FORMATS.GEMINI,
  API_FORMATS.GEMINI_CLI,
  API_FORMATS.GEMINI_VIDEO,
]

const LEGACY_API_FORMAT_MAP: Record<string, string> = {
  CLAUDE: API_FORMATS.CLAUDE,
  CLAUDE_CLI: API_FORMATS.CLAUDE_CLI,
  OPENAI: API_FORMATS.OPENAI,
  OPENAI_CLI: API_FORMATS.OPENAI_CLI,
  OPENAI_COMPACT: API_FORMATS.OPENAI_COMPACT,
  OPENAI_VIDEO: API_FORMATS.OPENAI_VIDEO,
  GEMINI: API_FORMATS.GEMINI,
  GEMINI_CLI: API_FORMATS.GEMINI_CLI,
  GEMINI_VIDEO: API_FORMATS.GEMINI_VIDEO,
}

// Family 显示名称映射
export const API_FORMAT_FAMILY_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  claude: 'Claude',
  gemini: 'Gemini',
}

// Kind 显示名称映射
export const API_FORMAT_KIND_LABELS: Record<string, string> = {
  chat: 'Chat',
  cli: 'CLI',
  compact: 'Compact',
  video: 'Video',
}

// Family 排序顺序
const FAMILY_ORDER = ['openai', 'claude', 'gemini']

export function normalizeApiFormatKey(format: string | null | undefined): string {
  const raw = String(format || '').trim()
  if (!raw) return ''

  if (raw.includes(':')) {
    const [family, kind] = raw.split(':', 2)
    return `${family.trim().toLowerCase()}:${kind.trim().toLowerCase()}`
  }

  const legacyToken = raw.replace(/[-:]/g, '_').toUpperCase()
  return LEGACY_API_FORMAT_MAP[legacyToken] || raw.toLowerCase()
}

export function normalizeApiFormats(formats: string[] | null | undefined): string[] {
  if (!Array.isArray(formats)) return []

  const normalized: string[] = []
  const seen = new Set<string>()
  for (const raw of formats) {
    const format = normalizeApiFormatKey(raw)
    if (!format || seen.has(format)) continue
    seen.add(format)
    normalized.push(format)
  }
  return normalized
}

export function normalizeApiFormatRecord<T>(
  record: Record<string, T> | null | undefined
): Record<string, T> | null {
  if (!record || typeof record !== 'object') return null

  const normalized: Record<string, T> = {}
  for (const [rawKey, value] of Object.entries(record)) {
    const key = normalizeApiFormatKey(rawKey)
    if (!key || key in normalized) continue
    normalized[key] = value
  }
  return Object.keys(normalized).length > 0 ? normalized : null
}

// 工具函数：从 API 格式中提取 family 和 kind
export function parseApiFormat(format: string): { family: string; kind: string } {
  const idx = format.indexOf(':')
  if (idx === -1) return { family: format.toLowerCase(), kind: '' }
  return { family: format.slice(0, idx).toLowerCase(), kind: format.slice(idx + 1).toLowerCase() }
}

// 工具函数：按 family 分组并排序 API 格式数组
export interface ApiFormatGroup {
  family: string
  label: string
  formats: string[]
}

export function groupApiFormats(formats: string[]): ApiFormatGroup[] {
  const sorted = sortApiFormats(formats)
  const groups = new Map<string, string[]>()
  for (const f of sorted) {
    const { family } = parseApiFormat(f)
    if (!groups.has(family)) groups.set(family, [])
    groups.get(family)?.push(f)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => {
      const ai = FAMILY_ORDER.indexOf(a)
      const bi = FAMILY_ORDER.indexOf(b)
      if (ai === -1 && bi === -1) return 0
      if (ai === -1) return 1
      if (bi === -1) return -1
      return ai - bi
    })
    .map(([family, fmts]) => ({
      family,
      label: API_FORMAT_FAMILY_LABELS[family] || family,
      formats: fmts,
    }))
}

// 工具函数：将 API 格式签名转为友好显示名称
export function formatApiFormat(format: string | null | undefined): string {
  if (!format) return '-'
  const raw = format.trim()
  const normalized = normalizeApiFormatKey(raw)
  return API_FORMAT_LABELS[normalized] || API_FORMAT_LABELS[raw] || API_FORMAT_LABELS[raw.toUpperCase()] || raw
}

// 工具函数：按标准顺序排序 API 格式数组
export function sortApiFormats(formats: string[]): string[] {
  return normalizeApiFormats(formats).sort((a, b) => {
    const aIdx = API_FORMAT_ORDER.indexOf(a)
    const bIdx = API_FORMAT_ORDER.indexOf(b)
    if (aIdx === -1 && bIdx === -1) return 0
    if (aIdx === -1) return 1
    if (bIdx === -1) return -1
    return aIdx - bIdx
  })
}
