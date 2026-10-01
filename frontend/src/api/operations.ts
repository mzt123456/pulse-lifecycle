import { request } from '@/api/request'
import type { PageResult, WellOperation } from '@/types'

export interface OperationQuery {
  equipment_id?: number
  well_no?: string
}

export interface OperationPayload {
  equipment_id?: number
  well_no?: string | null
  well_depth?: string | null
  bit_size?: string | null
  mud_type?: string | null
  mud_density?: string | null
  flow_rate?: string | null
  start_date?: string | null
  end_date?: string | null
  run_hours?: string | null
  run_in_depth?: string | null
  run_out_depth?: string | null
  footage?: string | null
  temperature?: string | null
  instrument_type?: string | null
  instrument_config?: string | null
  operator_name?: string | null
  remark?: string | null
}

export function listOperations(
  params: OperationQuery & { page: number; page_size: number },
): Promise<PageResult<WellOperation>> {
  return request<PageResult<WellOperation>>({ url: '/well-operations', method: 'get', params })
}

export function createOperation(payload: OperationPayload): Promise<WellOperation> {
  return request<WellOperation>({ url: '/well-operations', method: 'post', data: payload })
}

export function updateOperation(id: number, payload: OperationPayload): Promise<WellOperation> {
  return request<WellOperation>({ url: `/well-operations/${id}`, method: 'put', data: payload })
}

export function deleteOperation(id: number): Promise<null> {
  return request<null>({ url: `/well-operations/${id}`, method: 'delete' })
}
