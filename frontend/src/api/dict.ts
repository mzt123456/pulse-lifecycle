import { request } from '@/api/request'
import type { DictMap } from '@/types'

export function getDictItems(): Promise<DictMap> {
  return request<DictMap>({ url: '/dict-items', method: 'get' })
}
