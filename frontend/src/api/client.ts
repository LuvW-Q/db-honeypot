// 类型化 HTTP 客户端：仅使用原生 fetch，集中解析 contracts/api.md 1.8 节的统一错误结构。
import type { ApiErrorBody, HealthResponse } from '../types'

export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | Array<string | number | boolean>

type QueryParams = Record<string, QueryValue>

/** 带契约错误码、状态码与 request_id 的请求异常。 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly detail: unknown
  readonly requestId: string

  constructor(
    message: string,
    options: { code?: string; status?: number; detail?: unknown; requestId?: string } = {}
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code ?? 'UNKNOWN_ERROR'
    this.status = options.status ?? 0
    this.detail = options.detail ?? null
    this.requestId = options.requestId ?? ''
  }
}

/** 将查询参数拼为 query string：跳过 undefined/null/空字符串，数组按同名重复参数展开。 */
export function buildQuery(params?: QueryParams): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === '') continue
        search.append(key, String(item))
      }
      continue
    }
    search.append(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

function parseJson(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}

async function request<T>(path: string, init: RequestInit = {}, params?: QueryParams): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${path}${buildQuery(params)}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init.headers ?? {})
      }
    })
  } catch (error) {
    throw new ApiError('无法连接后端服务，请确认 API 已启动', {
      code: 'NETWORK_ERROR',
      detail: error instanceof Error ? error.message : String(error)
    })
  }

  const payload = parseJson(await response.text())

  if (!response.ok) {
    const body = (payload ?? {}) as Partial<ApiErrorBody>
    throw new ApiError(
      typeof body.message === 'string' && body.message ? body.message : `请求失败（HTTP ${response.status}）`,
      {
        code: typeof body.code === 'string' ? body.code : 'HTTP_ERROR',
        status: response.status,
        detail: body.detail ?? null,
        requestId:
          typeof body.request_id === 'string'
            ? body.request_id
            : (response.headers.get('X-Request-ID') ?? '')
      }
    )
  }

  return payload as T
}

export const api = {
  get<T>(path: string, params?: QueryParams): Promise<T> {
    return request<T>(path, { method: 'GET' }, params)
  },
  post<T>(path: string, body?: unknown, params?: QueryParams): Promise<T> {
    return request<T>(
      path,
      { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) },
      params
    )
  },
  patch<T>(path: string, body?: unknown, params?: QueryParams): Promise<T> {
    return request<T>(
      path,
      { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) },
      params
    )
  }
}

/**
 * 健康检查：503 降级响应同样携带完整状态体，因此这里不抛错，
 * 返回响应体供概览页渲染降级横幅；网络不可达返回 null。
 */
export async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    const response = await fetch('/api/health', { headers: { Accept: 'application/json' } })
    const payload = parseJson(await response.text())
    if (payload && typeof payload === 'object') {
      return payload as HealthResponse
    }
    return null
  } catch {
    return null
  }
}

/** 将异常格式化为可展示的中文提示，附带契约错误码与 request_id 便于排查。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const extras: string[] = []
    if (error.code && error.code !== 'HTTP_ERROR' && error.code !== 'UNKNOWN_ERROR') {
      extras.push(`错误码 ${error.code}`)
    }
    if (error.requestId) extras.push(`请求编号 ${error.requestId}`)
    return extras.length ? `${error.message}（${extras.join('，')}）` : error.message
  }
  if (error instanceof Error) return error.message
  return '请求失败，请稍后重试'
}
