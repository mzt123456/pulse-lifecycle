/** 令牌与当前用户的本地存储读写。单独成模块，避免请求层与状态层循环引用。 */

import type { UserInfo } from '@/types'

const ACCESS_KEY = 'pulse.access_token'
const REFRESH_KEY = 'pulse.refresh_token'
const USER_KEY = 'pulse.user'

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_KEY) ?? ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_KEY) ?? ''
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_KEY, accessToken)
  localStorage.setItem(REFRESH_KEY, refreshToken)
}

export function setStoredUser(user: UserInfo | null): void {
  if (user === null) {
    localStorage.removeItem(USER_KEY)
    return
  }
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function getStoredUser(): UserInfo | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    return null
  }
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
}
