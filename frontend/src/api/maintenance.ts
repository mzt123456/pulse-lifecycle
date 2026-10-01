import { request } from '@/api/request'
import type { MaintenanceOrder, MaintenanceStep, PageResult } from '@/types'

export interface MaintenanceQuery {
  equipment_id?: number
  level?: string
  status?: string
}

export interface MaintenancePayload {
  equipment_id?: number
  level?: string
  start_date?: string | null
  end_date?: string | null
  result?: string | null
  oil_level?: string | null
  suggestion?: string | null
  status?: string | null
}

export function listMaintenanceOrders(
  params: MaintenanceQuery & { page: number; page_size: number },
): Promise<PageResult<MaintenanceOrder>> {
  return request<PageResult<MaintenanceOrder>>({
    url: '/maintenance-orders',
    method: 'get',
    params,
  })
}

export function getMaintenanceOrder(id: number): Promise<MaintenanceOrder> {
  return request<MaintenanceOrder>({ url: `/maintenance-orders/${id}`, method: 'get' })
}

export function createMaintenanceOrder(payload: MaintenancePayload): Promise<MaintenanceOrder> {
  return request<MaintenanceOrder>({ url: '/maintenance-orders', method: 'post', data: payload })
}

export function updateMaintenanceOrder(
  id: number,
  payload: MaintenancePayload,
): Promise<MaintenanceOrder> {
  return request<MaintenanceOrder>({
    url: `/maintenance-orders/${id}`,
    method: 'put',
    data: payload,
  })
}

export function completeStep(
  orderId: number,
  stepId: number,
  isDone: boolean,
  remark?: string | null,
): Promise<MaintenanceStep> {
  return request<MaintenanceStep>({
    url: `/maintenance-orders/${orderId}/steps/${stepId}`,
    method: 'post',
    data: { is_done: isDone, remark },
  })
}
