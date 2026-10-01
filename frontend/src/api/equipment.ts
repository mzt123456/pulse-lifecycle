import { request } from '@/api/request'
import type { Equipment, PageResult } from '@/types'

export interface EquipmentQuery {
  keyword?: string
  status?: string
}

export interface EquipmentPayload {
  equipment_no: string
  model?: string | null
  status: string
  factory_date?: string | null
  temperature_grade?: string | null
  pressure_grade?: string | null
  valve_shell_size?: string | null
  company?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  remark?: string | null
}

export function listEquipment(
  params: EquipmentQuery & { page: number; page_size: number },
): Promise<PageResult<Equipment>> {
  return request<PageResult<Equipment>>({ url: '/equipment', method: 'get', params })
}

export function createEquipment(payload: EquipmentPayload): Promise<Equipment> {
  return request<Equipment>({ url: '/equipment', method: 'post', data: payload })
}

export function updateEquipment(
  id: number,
  payload: EquipmentPayload & { version: number },
): Promise<Equipment> {
  return request<Equipment>({ url: `/equipment/${id}`, method: 'put', data: payload })
}

export function deleteEquipment(id: number): Promise<null> {
  return request<null>({ url: `/equipment/${id}`, method: 'delete' })
}
