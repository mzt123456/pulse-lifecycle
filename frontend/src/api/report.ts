import { request } from '@/api/request'

export interface DashboardData {
  equipment_total: number
  status_counts: Record<string, number>
  maintenance_due: number
  low_stock_consumables: number
  open_faults: number
  recent_maintenance: {
    order_no: string
    equipment_no: string | null
    level: string
    status: string
    start_date: string | null
  }[]
  recent_operations: {
    equipment_no: string | null
    well_no: string | null
    run_hours: string | null
    start_date: string | null
  }[]
}

export interface UtilizationData {
  start: string
  end: string
  total_hours: string
  formula: string
  items: {
    equipment_id: number
    equipment_no: string
    model: string | null
    status: string
    operation_count: number
    run_hours: string
    utilization_rate: string
  }[]
}

export interface FaultStatisticsData {
  start: string
  end: string
  total: number
  unresolved: number
  by_type: { fault_type: string; count: number }[]
  by_month: { month: string; count: number }[]
}

export interface OperationTrendData {
  months: number
  by_month: { month: string; count: number; hours: string }[]
  by_instrument: { instrument_type: string; hours: string }[]
}

export function getDashboard(): Promise<DashboardData> {
  return request<DashboardData>({ url: '/reports/dashboard', method: 'get' })
}

export function getUtilization(params: {
  start?: string
  end?: string
}): Promise<UtilizationData> {
  return request<UtilizationData>({ url: '/reports/equipment-utilization', method: 'get', params })
}

export function getFaultStatistics(params: {
  start?: string
  end?: string
}): Promise<FaultStatisticsData> {
  return request<FaultStatisticsData>({ url: '/reports/fault-statistics', method: 'get', params })
}

export function getOperationTrend(months: number): Promise<OperationTrendData> {
  return request<OperationTrendData>({
    url: '/reports/operation-trend',
    method: 'get',
    params: { months },
  })
}
