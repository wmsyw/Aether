export function normalizeApiKeyValue(value: string): string {
  return value.trim()
}

export function validateManualApiKeyValue(value: string): string | null {
  const normalized = normalizeApiKeyValue(value)
  if (!normalized) {
    return '请输入 API Key'
  }
  if (!normalized.startsWith('sk-')) {
    return '手动输入的 API Key 必须以 "sk-" 开头'
  }
  if (normalized.length <= 10) {
    return '手动输入的 API Key 长度必须大于 10 位'
  }
  return null
}
