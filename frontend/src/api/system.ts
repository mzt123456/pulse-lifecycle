import http, { request } from '@/api/request'
import type { PageResult } from '@/types'

export interface AuditLog {
  id: number
  user_id: number | null
  username: string | null
  action: string
  object_type: string | null
  object_id: number | null
  detail: string | null
  client_ip: string | null
  created_at: string
}

export interface Attachment {
  id: number
  object_type: string
  object_id: number
  file_name: string
  content_type: string | null
  size_bytes: number | null
  uploaded_by: number | null
  uploaded_at: string
}

export interface AuditQuery {
  action?: string
  object_type?: string
  user_id?: number
  start?: string
  end?: string
}

export function listAuditLogs(
  params: AuditQuery & { page: number; page_size: number },
): Promise<PageResult<AuditLog>> {
  return request<PageResult<AuditLog>>({ url: '/system/audit-logs', method: 'get', params })
}

export function listAttachments(params: {
  object_type: string
  object_id: number
  page?: number
  page_size?: number
}): Promise<PageResult<Attachment>> {
  return request<PageResult<Attachment>>({ url: '/attachments', method: 'get', params })
}

export function uploadAttachment(
  file: File,
  objectType: string,
  objectId: number,
): Promise<Attachment> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('object_type', objectType)
  formData.append('object_id', String(objectId))
  return request<Attachment>({
    url: '/attachments',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 下载走带令牌的请求再触发浏览器保存，避免直接开链接丢掉鉴权头。 */
export async function downloadAttachment(id: number, fileName: string): Promise<void> {
  const blob = (await http.get(`/attachments/${id}`, { responseType: 'blob' })) as unknown as Blob
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
