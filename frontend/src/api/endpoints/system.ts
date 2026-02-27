import { client } from '../client'

// AWS Regions

let _awsRegionsCache: string[] | null = null

export async function getAwsRegions(): Promise<string[]> {
  if (_awsRegionsCache) return _awsRegionsCache
  const resp = await client.get<{ regions: string[] }>('/api/admin/system/aws-regions')
  _awsRegionsCache = resp.data.regions
  return _awsRegionsCache
}
