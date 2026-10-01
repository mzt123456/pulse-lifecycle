import { request } from '@/api/request'
import type { FaultRecord, PageResult } from '@/types'

export interface FaultQuery {
  equipment_id?: number
  fault_type?: string
  status?: string
}

export interface FaultPayload {
  equipment_id?: number
  occurred_at?: string | null
  position?: string | null
  fault_type?: string | null
  description?: string | null
  cause?: string | null
  solution?: string | null
  status?: string | null
}

export function listFaults(
  params: FaultQuery & { page: number; page_size: number },
): Promise<PageResult<FaultRecord>> {
  return request<PageResult<FaultRecord>>({ url: '/fault-records', method: 'get', params })
}

export function createFault(payload: FaultPayload): Promise<FaultRecord> {
  return request<FaultRecord>({ url: '/fault-records', method: 'post', data: payload })
}

export function updateFault(id: number, payload: FaultPayload): Promise<FaultRecord> {
  return request<FaultRecord>({ url: `/fault-records/${id}`, method: 'put', data: payload })
}
