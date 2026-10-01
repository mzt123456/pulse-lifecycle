/** 统一请求封装：注入令牌、401 自动刷新并重放、错误集中提示。 */

import axios, {
  AxiosError,
  type AxiosResponse,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'

import router from '@/router'
import type { ApiEnvelope, TokenPayload } from '@/types'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '@/utils/token'

export const CODE_TOKEN_EXPIRED = 40101
export const CODE_UNAUTHENTICATED = 40100

export class ApiError extends Error {
  constructor(
    public readonly code: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const http = axios.create({ baseURL: '/api/v1', timeout: 15000 })

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshPromise: Promise<boolean> | null = null

async function requestNewTokens(): Promise<boolean> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    return false
  }
  try {
    // 用裸 axios，避免刷新请求本身再被拦截器接手造成递归
    const { data } = await axios.post<ApiEnvelope<TokenPayload>>('/api/v1/auth/refresh', {
      refresh_token: refreshToken,
    })
    if (data.code !== 0 || !data.data) {
      return false
    }
    setTokens(data.data.access_token, data.data.refresh_token)
    return true
  } catch {
    return false
  }
}

/** 并发请求同时过期时只发起一次刷新。 */
function ensureRefreshed(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = requestNewTokens().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiEnvelope
    // 只对统一信封做拆包；文件流等非信封响应原样返回
    if (!body || typeof body !== 'object' || typeof body.code !== 'number') {
      return body as unknown as AxiosResponse
    }
    if (body.code !== 0) {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new ApiError(body.code, body.message))
    }
    // 拦截器在这里剥掉外层信封，返回值不再是 AxiosResponse，故做一次类型断言
    return body.data as unknown as AxiosResponse
  },
  async (error: AxiosError<ApiEnvelope>) => {
    const status = error.response?.status
    const body = error.response?.data
    const original = error.config as (InternalAxiosRequestConfig & { retried?: boolean }) | undefined

    // 登录与刷新接口自身的 401 是业务失败（口令错误、刷新令牌失效），不能按会话过期处理
    const url = original?.url ?? ''
    const isAuthEntry = url.includes('/auth/login') || url.includes('/auth/refresh')

    if (
      status === 401 &&
      !isAuthEntry &&
      body?.code === CODE_TOKEN_EXPIRED &&
      original &&
      !original.retried
    ) {
      original.retried = true
      if (await ensureRefreshed()) {
        original.headers.Authorization = `Bearer ${getAccessToken()}`
        return http.request(original)
      }
    }

    if (status === 401 && !isAuthEntry) {
      clearTokens()
      if (router.currentRoute.value.name !== 'login') {
        ElMessage.warning('登录已失效，请重新登录')
        void router.push({
          name: 'login',
          query: { redirect: router.currentRoute.value.fullPath },
        })
      }
      return Promise.reject(new ApiError(body?.code ?? CODE_UNAUTHENTICATED, body?.message ?? '未登录'))
    }

    ElMessage.error(body?.message || '网络异常，请稍后重试')
    return Promise.reject(body?.code ? new ApiError(body.code, body.message) : error)
  },
)

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  return (await http.request(config)) as T
}

export default http
