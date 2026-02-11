const regionLabels: Record<string, string> = {
  US: 'US(美国)',
  SG: 'SG(新加坡)',
  JP: 'JP(日本)',
  KR: 'KR(韩国)',
  HK: 'HK(中国香港)',
  TW: 'TW(中国台湾)',
  DE: 'DE(德国)',
  GB: 'GB(英国)',
  FR: 'FR(法国)',
  NL: 'NL(荷兰)',
  AU: 'AU(澳大利亚)',
  CA: 'CA(加拿大)',
  IN: 'IN(印度)',
  BR: 'BR(巴西)',
  RU: 'RU(俄罗斯)',
  CN: 'CN(中国)',
}

export function formatRegion(region: string | null, fallback = '-'): string {
  if (!region) return fallback
  return regionLabels[region.toUpperCase()] || region
}
