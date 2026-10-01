import { request } from '@/api/request'
import type { Consumable, ConsumableUsage, ImportSummary, PageResult } from '@/types'

export interface ConsumableQuery {
  keyword?: string
  low_stock_only?: boolean
}

export interface ConsumablePayload {
  part_no?: string
  description?: string
  quantity?: number
  safety_stock?: number
  unit?: string | null
  remark?: string | null
}

export function listConsumables(
  params: ConsumableQuery & { page: number; page_size: number },
): Promise<PageResult<Consumable>> {
  return request<PageResult<Consumable>>({ url: '/consumables', method: 'get', params })
}

export function createConsumable(payload: ConsumablePayload): Promise<Consumable> {
  return request<Consumable>({ url: '/consumables', method: 'post', data: payload })
}

export function updateConsumable(id: number, payload: ConsumablePayload): Promise<Consumable> {
  return request<Consumable>({ url: `/consumables/${id}`, method: 'put', data: payload })
}

export function issueConsumable(
  consumableId: number,
  quantity: number,
  remark?: string | null,
): Promise<ConsumableUsage> {
  return request<ConsumableUsage>({
    url: '/consumables/usages',
    method: 'post',
    data: { consumable_id: consumableId, quantity, remark },
  })
}

export function importConsumables(file: File): Promise<ImportSummary> {
  const formData = new FormData()
  formData.append('file', file)
  return request<ImportSummary>({
    url: '/consumables/import',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
