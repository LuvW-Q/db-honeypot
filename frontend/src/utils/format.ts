// 展示层格式化与中文标签映射（契约字段保持 snake_case，不在此处改字段名）。

function pad(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

/** ISO 8601 UTC 字符串 → 浏览器本地时区 `YYYY-MM-DD HH:mm:ss`。 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** ISO 8601 UTC 字符串 → 本地 `YYYY-MM-DD`。 */
export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 契约 date（YYYY-MM-DD）加减天数，返回 YYYY-MM-DD；用于构造左闭右开时间区间。 */
export function addDays(dateText: string, days: number): string {
  const date = new Date(`${dateText}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return dateText
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString('zh-CN')
}

export function formatPercent(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}%`
}

export function formatRatio(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(4)
}

/** 规则编码串（如 "R01,R02"）拆为数组，空值返回空数组。 */
export function splitCodes(value?: string | null): string[] {
  if (!value) return []
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

export function riskLevelLabel(level?: string | null): string {
  switch (level) {
    case 'low':
      return '低风险'
    case 'medium':
      return '中风险'
    case 'high':
      return '高风险'
    case 'critical':
      return '严重'
    default:
      return '未知'
  }
}

export function intentLabel(type?: string | null): string {
  switch (type) {
    case 'scanning':
      return '扫描'
    case 'bruteforce':
      return '暴力破解'
    case 'recon':
      return '踩点探测'
    case 'data_dump':
      return '拖库'
    case 'destructive':
      return '破坏性操作'
    default:
      return type || '未知意图'
  }
}

export function alertTypeLabel(type?: string | null): string {
  switch (type) {
    case 'bruteforce':
      return '暴力破解'
    case 'data_dump':
      return '拖库'
    case 'destructive':
      return '破坏性操作'
    default:
      return type || '未知类型'
  }
}

export function severityLabel(level?: string | null): string {
  switch (level) {
    case 'low':
      return '低'
    case 'medium':
      return '中'
    case 'high':
      return '高'
    case 'critical':
      return '严重'
    default:
      return level || '未知'
  }
}

export function eventTypeLabel(type?: string | null): string {
  switch (type) {
    case 'connect':
      return '连接'
    case 'auth':
      return '认证'
    case 'query':
      return '查询'
    case 'disconnect':
      return '断开'
    default:
      return type || '事件'
  }
}

export function eventStatusLabel(status?: string | null): string {
  switch (status) {
    case 'success':
      return '成功'
    case 'failure':
      return '失败'
    case 'denied':
      return '拒绝'
    case 'error':
      return '错误'
    default:
      return status || '未知'
  }
}

export function sessionStatusLabel(status?: string | null): string {
  switch (status) {
    case 'active':
      return '进行中'
    case 'closed':
      return '已关闭'
    case 'idle':
      return '空闲'
    case 'error':
      return '异常'
    default:
      return status || '未知'
  }
}

export function sessionStatusTagType(status?: string | null): 'success' | 'info' | 'warning' | 'danger' {
  switch (status) {
    case 'active':
      return 'success'
    case 'closed':
      return 'info'
    case 'error':
      return 'danger'
    default:
      return 'warning'
  }
}
