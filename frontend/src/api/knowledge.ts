import { request } from '@/api/request'
import type { PageResult } from '@/types'

export interface KnowledgeChunk {
  seq: number
  text: string
  char_count: number
}

export interface KnowledgeDocument {
  id: number
  title: string
  source_type: 'text' | 'file'
  file_name: string | null
  content_type: string | null
  size_bytes: number | null
  char_count: number
  chunk_count: number
  status: 'ready' | 'failed'
  error: string | null
  created_by_name: string | null
  created_at: string
}

/** 详情带回前几个分块，用来确认解析质量 */
export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  chunks: KnowledgeChunk[]
}

export interface KnowledgeStats {
  documents: number
  chunks: number
  failed: number
  characters: number
}

export interface KnowledgeQuery {
  keyword?: string
  status?: string
}

export function listKnowledgeDocuments(
  params: KnowledgeQuery & { page: number; page_size: number },
): Promise<PageResult<KnowledgeDocument>> {
  return request<PageResult<KnowledgeDocument>>({ url: '/knowledge/documents', method: 'get', params })
}

export function getKnowledgeDocument(id: number): Promise<KnowledgeDocumentDetail> {
  return request<KnowledgeDocumentDetail>({ url: `/knowledge/documents/${id}`, method: 'get' })
}

export function getKnowledgeStats(): Promise<KnowledgeStats> {
  return request<KnowledgeStats>({ url: '/knowledge/stats', method: 'get' })
}

export function createKnowledgeText(payload: {
  title: string
  content: string
}): Promise<KnowledgeDocument> {
  return request<KnowledgeDocument>({
    url: '/knowledge/documents/text',
    method: 'post',
    data: payload,
  })
}

export function uploadKnowledgeDocument(file: File, title?: string): Promise<KnowledgeDocument> {
  const formData = new FormData()
  formData.append('file', file)
  if (title) {
    formData.append('title', title)
  }
  return request<KnowledgeDocument>({
    url: '/knowledge/documents/upload',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteKnowledgeDocument(id: number): Promise<KnowledgeDocument> {
  return request<KnowledgeDocument>({ url: `/knowledge/documents/${id}`, method: 'delete' })
}
