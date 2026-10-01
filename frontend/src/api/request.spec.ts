/** 请求封装行为测试：令牌注入、信封剥离、401 刷新重放与并发去重。 */

import axios, { type InternalAxiosRequestConfig } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { pushMock, errorMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  errorMock: vi.fn(),
}))

vi.mock('@/router', () => ({
  default: {
    currentRoute: { value: { name: 'dashboard', fullPath: '/dashboard' } },
    push: pushMock,
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: errorMock, warning: vi.fn(), success: vi.fn() },
}))

import http, { ApiError, request } from '@/api/request'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '@/utils/token'

type Reply = { status: number; data: unknown }
type Route = { method: string; url: string; reply: Reply | (() => Reply) }

let routes: Route[] = []
let requested: string[] = []

function installMockTransport(): void {
  const adapter = async (config: InternalAxiosRequestConfig) => {
    const method = String(config.method ?? 'get').toLowerCase()
    const url = String(config.url)
    requested.push(`${method} ${url}`)

    const route = routes.find((item) => item.method === method && item.url === url)
    if (!route) {
      throw new Error(`未模拟的请求：${method} ${url}`)
    }

    const reply = typeof route.reply === 'function' ? route.reply() : route.reply
    const response = {
      data: reply.data,
      status: reply.status,
      statusText: '',
      headers: {},
      config,
    }

    if (reply.status >= 400) {
      throw new axios.AxiosError(`模拟 HTTP ${reply.status}`, String(reply.status), config, null, response as never)
    }
    return response
  }

  http.defaults.adapter = adapter
  // 刷新令牌用的是裸 axios，同样需要接管
  axios.defaults.adapter = adapter
}

function okReply(data: unknown): Reply {
  return { status: 200, data: { code: 0, message: 'ok', data } }
}

function expiredReply(): Reply {
  return { status: 401, data: { code: 40101, message: '令牌已过期', data: null } }
}

beforeEach(() => {
  clearTokens()
  routes = []
  requested = []
  vi.clearAllMocks()
  installMockTransport()
})

describe('请求封装', () => {
  it('剥离统一信封后返回 data', async () => {
    routes = [{ method: 'get', url: '/auth/me', reply: okReply({ username: 'admin' }) }]

    const data = await request<{ username: string }>({ url: '/auth/me', method: 'get' })

    expect(data.username).toBe('admin')
  })

  it('非信封响应（如文件流）原样返回', async () => {
    const blob = new Blob(['file-bytes'], { type: 'text/plain' })
    routes = [{ method: 'get', url: '/attachments/1', reply: { status: 200, data: blob } }]

    const data = await request<Blob>({ url: '/attachments/1', method: 'get' })

    expect(data).toBe(blob)
  })

  it('业务错误码转为 ApiError 并提示', async () => {
    routes = [
      {
        method: 'post',
        url: '/auth/login',
        reply: { status: 401, data: { code: 40100, message: '用户名或密码错误', data: null } },
      },
    ]

    await expect(request({ url: '/auth/login', method: 'post' })).rejects.toMatchObject({ code: 40100 })
    expect(errorMock).toHaveBeenCalledWith('用户名或密码错误')
  })

  it('访问令牌过期时刷新一次并重放原请求', async () => {
    setTokens('expired-access', 'good-refresh')
    let meCalls = 0
    routes = [
      {
        method: 'get',
        url: '/auth/me',
        reply: () => {
          meCalls += 1
          return meCalls === 1 ? expiredReply() : okReply({ username: 'admin' })
        },
      },
      {
        method: 'post',
        url: '/api/v1/auth/refresh',
        reply: okReply({ access_token: 'new-access', refresh_token: 'new-refresh' }),
      },
    ]

    const data = await request<{ username: string }>({ url: '/auth/me', method: 'get' })

    expect(data.username).toBe('admin')
    expect(meCalls).toBe(2)
    expect(getAccessToken()).toBe('new-access')
    expect(getRefreshToken()).toBe('new-refresh')
  })

  it('并发请求同时过期时只刷新一次', async () => {
    setTokens('expired-access', 'good-refresh')
    const seen = new Map<string, number>()
    const firstThenOk = (key: string, payload: unknown): Reply => {
      const count = (seen.get(key) ?? 0) + 1
      seen.set(key, count)
      return count === 1 ? expiredReply() : okReply(payload)
    }
    let refreshCalls = 0
    routes = [
      { method: 'get', url: '/auth/me', reply: () => firstThenOk('/auth/me', { username: 'admin' }) },
      { method: 'get', url: '/health', reply: () => firstThenOk('/health', { status: 'ok' }) },
      {
        method: 'post',
        url: '/api/v1/auth/refresh',
        reply: () => {
          refreshCalls += 1
          return okReply({ access_token: 'new-access', refresh_token: 'new-refresh' })
        },
      },
    ]

    const [me, health] = await Promise.all([
      request<{ username: string }>({ url: '/auth/me', method: 'get' }),
      request<{ status: string }>({ url: '/health', method: 'get' }),
    ])

    expect(me.username).toBe('admin')
    expect(health.status).toBe('ok')
    expect(refreshCalls).toBe(1)
  })

  it('刷新失败时清理令牌并跳转登录页', async () => {
    setTokens('expired-access', 'revoked-refresh')
    routes = [
      { method: 'get', url: '/auth/me', reply: expiredReply() },
      {
        method: 'post',
        url: '/api/v1/auth/refresh',
        reply: { status: 401, data: { code: 40100, message: '刷新令牌已撤销', data: null } },
      },
    ]

    await expect(request({ url: '/auth/me', method: 'get' })).rejects.toBeInstanceOf(ApiError)

    expect(getAccessToken()).toBe('')
    expect(getRefreshToken()).toBe('')
    expect(pushMock).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'login', query: { redirect: '/dashboard' } }),
    )
  })
})
