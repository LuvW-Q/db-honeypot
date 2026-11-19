// 与 specs/001-database-honeypot/contracts/api.md（v1.1.0）严格对齐的类型定义。
// 约定：字段一律 snake_case，与接口响应/数据库列名保持一致，前端不做驼峰转换。

/** 统一错误响应体（1.8 节）。 */
export interface ApiErrorBody {
  code: string
  message: string
  detail?: unknown
  request_id: string
}

/** 字段级校验错误（422 detail 数组元素）。 */
export interface ValidationErrorItem {
  field: string
  reason: string
  input?: string
}

/** 分页信封（1.4 节），所有列表接口一致。 */
export interface PageEnvelope<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type Severity = RiskLevel
export type IntentType = 'scanning' | 'bruteforce' | 'recon' | 'data_dump' | 'destructive'
export type AlertType = 'bruteforce' | 'data_dump' | 'destructive'
export type RuleType = 'frequency' | 'keyword' | 'sequence' | 'volume'
export type SessionStatus = 'active' | 'closed' | 'idle' | 'error' | string
export type EventType = 'connect' | 'auth' | 'query' | 'disconnect'
export type EventStatus = 'success' | 'failure' | 'denied' | 'error'
export type SortOrder = 'asc' | 'desc'

/* ------------------------------------------------------------------ */
/* 3.1 GET /api/health                                                 */
/* ------------------------------------------------------------------ */

export interface HealthDependency {
  status: 'ok' | 'down'
  latency_ms: number | null
}

export interface HealthHoneypot {
  status: 'ok' | 'down' | 'disabled'
  listen: string | null
  accepted_connections: number
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  database: HealthDependency
  honeypot: HealthHoneypot
  generated_at: string
  // 降级（503）响应会附带统一错误字段
  code?: string
  message?: string
  detail?: unknown
  request_id?: string
}

/* ------------------------------------------------------------------ */
/* 3.2 GET /api/overview                                               */
/* ------------------------------------------------------------------ */

export interface OverviewResponse {
  sessions: number
  queries: number
  alerts: number
  high_risk_attackers: number
  generated_at: string
}

/* ------------------------------------------------------------------ */
/* 3.3 GET /api/attackers                                              */
/* ------------------------------------------------------------------ */

export interface MainIntent {
  intent_type: IntentType
  intent_score: number
  evidence_count: number
  last_detected_at: string
}

export interface AttackerSummary {
  attacker_id: number
  source_ip: string
  first_seen: string
  last_seen: string
  total_connections: number
  total_auth_attempts: number
  total_queries: number
  main_intent: MainIntent | null
  risk_score: number
  risk_level: RiskLevel
  alert_count: number
}

export type AttackerListResponse = PageEnvelope<AttackerSummary>

export interface AttackerListParams {
  page?: number
  page_size?: number
  sort?: 'risk_score' | 'last_seen' | 'first_seen' | 'total_queries'
  order?: SortOrder
  risk_level?: string | string[]
  intent_type?: string | string[]
}

/* ------------------------------------------------------------------ */
/* 3.4 GET /api/attackers/{ip}                                         */
/* ------------------------------------------------------------------ */

export interface AttackerProfile {
  attacker_id: number
  source_ip: string
  first_seen: string
  last_seen: string
  total_connections: number
  total_auth_attempts: number
  total_auth_failures: number
  total_queries: number
  risk_score: number
  calculated_risk_score: number
  risk_level: RiskLevel
  session_count: number
  high_risk_session_count: number
  alert_count: number
  unread_alert_count: number
  intent_labels: string | null
  triggered_rule_codes: string | null
  evidence_summary: string | null
}

export interface IntentItem {
  intent_type: IntentType
  intent_score: number
  evidence_count: number
  first_detected_at: string
  last_detected_at: string
}

export interface SessionSummary {
  session_id: string
  source_port: number
  target_service: string
  started_at: string
  ended_at: string | null
  session_status: SessionStatus
  event_count: number
  query_count: number
  hit_rule_count: number
  hit_rule_codes: string | null
  risk_score: number
  risk_level: RiskLevel
  stored_max_risk_score: number
  alert_count: number
}

export interface RuleHit {
  hit_id: number
  event_id: number
  rule_code: string
  rule_name: string
  intent_type: IntentType
  rule_version: number
  risk_weight: number
  triggered_at: string
  evidence_summary: string
}

export interface AttackerDetailResponse {
  attacker: AttackerProfile
  intents: IntentItem[]
  sessions: SessionSummary[]
  recent_rule_hits: RuleHit[]
}

export interface AttackerDetailParams {
  session_limit?: number
  hit_limit?: number
}

/* ------------------------------------------------------------------ */
/* 3.5 GET /api/sessions/{session_id}/timeline                         */
/* ------------------------------------------------------------------ */

export interface SessionHeader {
  session_id: string
  source_ip: string
  source_port: number
  target_service: string
  client_fingerprint: string | null
  started_at: string
  ended_at: string | null
  session_status: SessionStatus
  request_count: number
  event_count: number
  query_count: number
  max_risk_score: number
  calculated_risk_score: number
  risk_level: RiskLevel
  alert_count: number
}

export interface SessionEvent {
  event_id: number
  event_uuid: string
  event_type: EventType
  event_time: string
  source_ip: string
  username: string | null
  credential_test_id: string | null
  credential_masked: string | null
  sql_statement: string | null
  normalized_sql: string | null
  statement_type: string | null
  returned_rows: number
  response_ms: number
  status: EventStatus
  payload_truncated: boolean
}

export interface TimelineAlert {
  alert_id: number
  alert_type: AlertType
  severity: Severity
  title: string
  occurrence_count: number
  created_at: string
  is_read: boolean
}

export interface SessionTimelineResponse {
  session: SessionHeader
  events: SessionEvent[]
  rule_hits: RuleHit[]
  alerts: TimelineAlert[]
  events_truncated: boolean
}

/* ------------------------------------------------------------------ */
/* 3.6 GET /api/alerts、3.7 PATCH /api/alerts/{alert_id}               */
/* ------------------------------------------------------------------ */

export interface AlertItem {
  alert_id: number
  dedup_key: string
  session_id: string
  attacker_id: number
  source_ip: string
  rule_code: string
  rule_name: string
  latest_hit_id: number
  alert_type: AlertType
  severity: Severity
  title: string
  evidence_summary: string
  first_seen_at: string
  last_seen_at: string
  occurrence_count: number
  created_at: string
  is_read: boolean
  read_at: string | null
}

export type AlertListResponse = PageEnvelope<AlertItem>

export interface AlertListParams {
  page?: number
  page_size?: number
  alert_type?: string | string[]
  severity?: string | string[]
  is_read?: boolean
  from?: string
  to?: string
  sort?: 'created_at' | 'severity'
  order?: SortOrder
}

export interface AlertReadPatch {
  is_read: boolean
}

/* ------------------------------------------------------------------ */
/* 3.10 GET /api/trend                                                 */
/* ------------------------------------------------------------------ */

export interface TrendItem {
  stat_date: string
  day_seq: number
  event_count: number
  session_count: number
  source_count: number
  query_count: number
  denied_count: number
  alert_count: number
  high_level_alert_count: number
  prev_event_count: number | null
  event_count_delta: number | null
  event_change_pct: number | null
  cumulative_event_count: number
  busy_day_rank: number
}

export interface TrendResponse {
  days: number
  items: TrendItem[]
}

/* ------------------------------------------------------------------ */
/* 3.11 GET /api/rules/effectiveness                                   */
/* ------------------------------------------------------------------ */

export interface RuleEffectivenessItem {
  rule_code: string
  rule_name: string
  rule_type: RuleType
  intent_type: IntentType
  risk_weight: number
  current_version: number
  is_enabled: boolean
  hit_count: number
  affected_session_count: number
  affected_event_count: number
  affected_attacker_count: number
  used_version_count: number
  first_hit_at: string | null
  last_hit_at: string | null
  alert_count: number
  unread_alert_count: number
  alert_per_hit_ratio: number
  hit_rank: number
}

export interface RuleEffectivenessResponse {
  items: RuleEffectivenessItem[]
  total: number
}

/* ------------------------------------------------------------------ */
/* 3.8 GET /api/rules、3.9 PATCH /api/rules/{rule_code}（本版不建页面）  */
/* ------------------------------------------------------------------ */

export interface RuleItem {
  rule_id: number
  rule_code: string
  rule_name: string
  rule_type: RuleType
  intent_type: IntentType
  parameters: Record<string, unknown>
  risk_weight: number
  rule_version: number
  enabled: boolean
  description: string
  created_at: string
  updated_at: string
  previous_version?: number
}

export interface RuleListResponse {
  items: RuleItem[]
  total: number
}

export interface RuleListParams {
  include_history?: boolean
  enabled?: boolean
}

export interface RuleUpdatePayload {
  enabled?: boolean
  parameters?: Record<string, unknown>
  risk_weight?: number
  expected_version?: number
  change_reason?: string
}
