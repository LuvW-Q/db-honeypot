// 展示层格式化与中文标签映射（契约字段保持 snake_case，不在此处改字段名）。
// 时间统一按 UTC+8（Asia/Shanghai）展示，与页头时钟/契约 §1.2 一致。

const TIME_ZONE = 'Asia/Shanghai'

function pad(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

function toDate(value?: string | null): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** ISO 8601（UTC）→ UTC+8 的 `YYYY-MM-DD HH:mm:ss`。 */
export function formatDateTime(value?: string | null): string {
  const date = toDate(value)
  if (!date) return '—'
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).formatToParts(date)
  const get = (type: string): string => parts.find((item) => item.type === type)?.value ?? '00'
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`
}

/** ISO 8601 → UTC+8 的 `MM-DD HH:mm`（密集表格用）。 */
export function formatDateTimeShort(value?: string | null): string {
  const full = formatDateTime(value)
  return full === '—' ? full : full.slice(5, 16)
}

/** ISO 8601 → UTC+8 的 `HH:mm:ss`（时钟/分桶）。 */
export function formatClock(value?: string | null): string {
  const full = formatDateTime(value)
  return full === '—' ? full : full.slice(11)
}

/** ISO 8601 → UTC+8 的 `YYYY-MM-DD`。 */
export function formatDate(value?: string | null): string {
  const full = formatDateTime(value)
  return full === '—' ? full : full.slice(0, 10)
}

/** 相对时间：刚刚 / N 分钟前 / N 小时前 / 日期（跨天回退到完整时间）。 */
export function formatRelative(value?: string | null, now: number = Date.now()): string {
  const date = toDate(value)
  if (!date) return '—'
  const diff = now - date.getTime()
  if (diff < 0) return formatDateTime(value)
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return formatDateTime(value)
}

/** 契约 date（YYYY-MM-DD）加减天数，返回 YYYY-MM-DD；用于构造左闭右开时间区间。 */
export function addDays(dateText: string, days: number): string {
  const date = new Date(`${dateText}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return dateText
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

/** UTC 时刻的 `HH:mm`（UTC+8）。 */
export function formatHourMinute(value?: string | null): string {
  return formatClock(value).slice(0, 5)
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString('zh-CN')
}

/** 百分比：入参为 0–1 的比率；1 位小数，分母 0（null）→ —。 */
export function formatPercent(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

/** 已是百分数值（如 delta_pct=12.5）→ `12.5%`。 */
export function formatPctValue(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}%`
}

/** 秒 → `N 秒` / `M 分 S 秒` / `H 小时 M 分`。 */
export function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds) || seconds < 0) return '—'
  const total = Math.round(seconds)
  if (total < 60) return `${total} 秒`
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes < 60) return `${minutes} 分 ${rest} 秒`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分`
}

/** SQL 单行截断（默认 120 字符），悬浮用完整文本。 */
export function truncateSql(sql?: string | null, limit = 120): string {
  if (!sql) return '—'
  const single = sql.replace(/\s+/g, ' ').trim()
  return single.length > limit ? `${single.slice(0, limit)}…` : single
}

/** UUID 会话号展示为 sess_xxxxxxxx，完整值放 title。 */
export function shortSessionId(sessionId?: string | null): string {
  if (!sessionId) return '—'
  if (sessionId.startsWith('sess_')) return sessionId
  return `sess_${sessionId.slice(0, 8)}`
}

/** 事件编号展示为 #10421。 */
export function formatEventId(eventId?: number | null): string {
  return eventId === null || eventId === undefined ? '—' : `#${eventId}`
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

export type IntentMeta = { label: string; short: string; rule: string }

const INTENT_META: Record<string, IntentMeta> = {
  bruteforce: { label: '暴力破解', short: '爆破', rule: 'R02' },
  data_dump: { label: '批量拖库', short: '拖库', rule: 'R04' },
  recon: { label: '踩点探测', short: '踩点', rule: 'R03' },
  scanning: { label: '端口扫描', short: '扫描', rule: 'R01' },
  destructive: { label: '破坏性操作', short: '破坏', rule: 'R05' }
}

export function intentMeta(type?: string | null): IntentMeta {
  return (
    INTENT_META[type ?? ''] ?? { label: type || '未知意图', short: type || '未知', rule: '—' }
  )
}

export function intentLabel(type?: string | null): string {
  return intentMeta(type).label
}

export const RULE_LABELS: Record<string, string> = {
  R01: '端口服务探测',
  R02: '高频认证失败爆破',
  R03: '敏感配置信息侦查',
  R04: '敏感表批量拖库',
  R05: '破坏性操作拦截'
}

export function ruleLabel(code?: string | null): string {
  if (!code) return '—'
  return RULE_LABELS[code] ?? code
}

export function alertTypeLabel(type?: string | null): string {
  switch (type) {
    case 'bruteforce':
      return '认证爆破'
    case 'data_dump':
      return '批量拖库'
    case 'destructive':
      return '破坏性操作'
    default:
      return type || '未知类型'
  }
}

export function alertTypeRule(type?: string | null): string {
  switch (type) {
    case 'bruteforce':
      return 'R02'
    case 'data_dump':
      return 'R04'
    case 'destructive':
      return 'R05'
    default:
      return '—'
  }
}

export function eventTypeLabel(type?: string | null): string {
  switch (type) {
    case 'connect':
      return 'CONNECT'
    case 'auth':
      return 'AUTH'
    case 'query':
      return 'QUERY'
    case 'disconnect':
      return 'DISCONNECT'
    default:
      return (type || 'EVENT').toUpperCase()
  }
}

export function eventTypeZh(type?: string | null): string {
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

export function sessionStatusShort(status?: string | null): string {
  switch (status) {
    case 'active':
      return '活动'
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

/** 浏览器本地时间是否处于 UTC+8 时区（令牌审计用于提示）。 */
export function isUtc8(): boolean {
  return new Intl.DateTimeFormat('en-US', { timeZone: TIME_ZONE }).resolvedOptions().timeZone === TIME_ZONE
}

export { pad }
