import apiClient from './client'

// 视频任务状态
export type VideoTaskStatus = 'pending' | 'submitted' | 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'

// 视频任务列表项
export interface VideoTaskItem {
  id: string
  external_task_id: string
  user_id: string
  username: string
  model: string
  prompt: string
  status: VideoTaskStatus
  progress_percent: number
  progress_message: string | null
  provider_id: string
  provider_name: string
  duration_seconds: number
  resolution: string
  aspect_ratio: string
  video_url: string | null
  error_code: string | null
  error_message: string | null
  poll_count: number
  max_poll_count: number
  created_at: string
  completed_at: string | null
  submitted_at: string | null
}

// 候选 Key 信息
export interface CandidateKeyInfo {
  index: number
  provider_id: string
  provider_name: string
  endpoint_id: string
  key_id: string
  key_name: string | null
  auth_type: string
  has_billing_rule: boolean
  priority: number
  selected?: boolean
}

// 请求元数据
export interface VideoTaskRequestMetadata {
  candidate_keys: CandidateKeyInfo[]
  selected_key_id: string
  selected_endpoint_id: string
  client_ip: string
  user_agent: string
  request_id: string
  request_headers?: Record<string, string>
}

// 视频任务详情
export interface VideoTaskDetail extends VideoTaskItem {
  api_key_id: string
  endpoint_id: string
  key_id: string
  client_api_format: string
  provider_api_format: string
  format_converted: boolean
  original_request_body: any
  converted_request_body: any
  size: string | null
  video_urls: string[] | null
  thumbnail_url: string | null
  video_size_bytes: number | null
  video_expires_at: string | null
  stored_video_path: string | null
  storage_provider: string | null
  retry_count: number
  max_retries: number
  poll_interval_seconds: number
  next_poll_at: string | null
  updated_at: string | null
  endpoint: {
    id: string
    base_url: string
    api_format: string
  } | null
  request_metadata: VideoTaskRequestMetadata | null
}

// 视频任务列表响应
export interface VideoTaskListResponse {
  items: VideoTaskItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

// 视频任务统计响应
export interface VideoTaskStatsResponse {
  total: number
  by_status: Record<VideoTaskStatus, number>
  by_model: Record<string, number>
  today_count: number
  active_users?: number  // 仅管理员
  processing_count?: number  // 仅管理员
}

// 视频任务查询参数
export interface VideoTaskQueryParams {
  status?: VideoTaskStatus
  user_id?: string
  model?: string
  page?: number
  page_size?: number
}

export const videoTasksApi = {
  /**
   * 获取视频任务列表
   */
  async list(params: VideoTaskQueryParams = {}): Promise<VideoTaskListResponse> {
    const searchParams = new URLSearchParams()
    if (params.status) searchParams.append('status', params.status)
    if (params.user_id) searchParams.append('user_id', params.user_id)
    if (params.model) searchParams.append('model', params.model)
    if (params.page) searchParams.append('page', params.page.toString())
    if (params.page_size) searchParams.append('page_size', params.page_size.toString())

    const query = searchParams.toString()
    const url = query ? `/api/admin/video-tasks?${query}` : '/api/admin/video-tasks'
    const response = await apiClient.get(url)
    return response.data
  },

  /**
   * 获取视频任务统计
   */
  async getStats(): Promise<VideoTaskStatsResponse> {
    const response = await apiClient.get('/api/admin/video-tasks/stats')
    return response.data
  },

  /**
   * 获取视频任务详情
   */
  async getDetail(taskId: string): Promise<VideoTaskDetail> {
    const response = await apiClient.get(`/api/admin/video-tasks/${taskId}`)
    return response.data
  },

  /**
   * 取消视频任务
   */
  async cancel(taskId: string): Promise<{ id: string; status: string; message: string }> {
    const response = await apiClient.post(`/api/admin/video-tasks/${taskId}/cancel`)
    return response.data
  },
}

export default videoTasksApi
