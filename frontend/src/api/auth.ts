import { request } from '@/api/request'
import type { TokenPayload, UserInfo } from '@/types'

export function loginApi(username: string, password: string): Promise<TokenPayload> {
  return request<TokenPayload>({
    url: '/auth/login',
    method: 'post',
    data: { username, password },
  })
}

export function logoutApi(refreshToken: string): Promise<null> {
  return request<null>({
    url: '/auth/logout',
    method: 'post',
    data: { refresh_token: refreshToken },
  })
}

export function getMeApi(): Promise<UserInfo> {
  return request<UserInfo>({ url: '/auth/me', method: 'get' })
}
