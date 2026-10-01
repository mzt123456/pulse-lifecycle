export interface ApiEnvelope<T = unknown> {
  code: number
  message: string
  data: T
}

export interface UserInfo {
  id: number
  username: string
  real_name: string | null
  department: string | null
  roles: string[]
  permissions: string[]
}

export interface TokenPayload {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Equipment {
  id: number
  equipment_no: string
  model: string | null
  status: string
  factory_date: string | null
  total_run_hours: string
  total_run_count: number
  temperature_grade: string | null
  pressure_grade: string | null
  valve_shell_size: string | null
  company: string | null
  contact_name: string | null
  contact_phone: string | null
  last_maintenance_at: string | null
  remark: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface WellOperation {
  id: number
  equipment_id: number
  equipment_no: string | null
  well_no: string | null
  well_depth: string | null
  bit_size: string | null
  mud_type: string | null
  mud_density: string | null
  flow_rate: string | null
  start_date: string | null
  end_date: string | null
  run_hours: string | null
  run_in_depth: string | null
  run_out_depth: string | null
  footage: string | null
  temperature: string | null
  instrument_type: string | null
  instrument_config: string | null
  operator_name: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export type DictMap = Record<string, string[]>

export interface MaintenanceStep {
  id: number
  seq: number
  name: string
  is_done: boolean
  done_by: number | null
  done_by_name: string | null
  done_at: string | null
  remark: string | null
}

export interface MaintenanceOrder {
  id: number
  order_no: string
  equipment_id: number
  equipment_no: string | null
  level: string
  start_date: string | null
  end_date: string | null
  result: string | null
  oil_level: string | null
  suggestion: string | null
  status: string
  report_path: string | null
  created_at: string
  updated_at: string
  steps?: MaintenanceStep[]
}

export interface FaultRecord {
  id: number
  equipment_id: number
  equipment_no: string | null
  occurred_at: string | null
  position: string | null
  fault_type: string | null
  description: string | null
  cause: string | null
  solution: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface Consumable {
  id: number
  part_no: string
  description: string
  quantity: number
  safety_stock: number
  unit: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface ConsumableUsage {
  id: number
  consumable_id: number
  part_no: string | null
  description: string | null
  order_id: number | null
  quantity: number
  used_by: number | null
  used_by_name: string | null
  used_at: string
  remark: string | null
}

export interface ImportSummary {
  created: number
  updated: number
  failed: number
  errors: string[]
}
