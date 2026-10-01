/** 当前用户状态：令牌、资料与权限集合。 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getMeApi, loginApi, logoutApi } from '@/api/auth'
import type { TokenPayload, UserInfo } from '@/types'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  getStoredUser,
  setStoredUser,
  setTokens,
} from '@/utils/token'

export const useUserStore = defineStore('user', () => {
  const accessToken = ref(getAccessToken())
  const refreshToken = ref(getRefreshToken())
  const user = ref<UserInfo | null>(getStoredUser())

  const isLoggedIn = computed(() => Boolean(accessToken.value))
  const displayName = computed(() => user.value?.real_name || user.value?.username || '')
  const roles = computed(() => user.value?.roles ?? [])
  const permissionSet = computed(() => new Set(user.value?.permissions ?? []))

  function has(permission: string): boolean {
    return permissionSet.value.has(permission)
  }

  function applySession(payload: TokenPayload): void {
    setTokens(payload.access_token, payload.refresh_token)
    setStoredUser(payload.user)
    accessToken.value = payload.access_token
    refreshToken.value = payload.refresh_token
    user.value = payload.user
  }

  async function login(username: string, password: string): Promise<void> {
    applySession(await loginApi(username, password))
  }

  async function loadMe(): Promise<void> {
    const me = await getMeApi()
    setStoredUser(me)
    user.value = me
  }

  async function logout(): Promise<void> {
    const token = refreshToken.value
    try {
      if (token) {
        await logoutApi(token)
      }
    } catch {
      // 注销失败不阻塞退出：本地凭证照常清理
    } finally {
      clearTokens()
      accessToken.value = ''
      refreshToken.value = ''
      user.value = null
    }
  }

  return {
    accessToken,
    refreshToken,
    user,
    isLoggedIn,
    displayName,
    roles,
    has,
    login,
    loadMe,
    logout,
  }
})
