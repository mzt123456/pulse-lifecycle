import { request } from '@/api/request'

export interface PreferencesPayload {
  page_size: number
  nav_collapsed: boolean
  table_columns: Record<string, string[]>
}

export function getPreferences(): Promise<PreferencesPayload> {
  return request<PreferencesPayload>({ url: '/user-preferences', method: 'get' })
}

export function savePreferences(
  payload: Partial<PreferencesPayload>,
): Promise<PreferencesPayload> {
  return request<PreferencesPayload>({ url: '/user-preferences', method: 'put', data: payload })
}
