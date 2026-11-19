// 契约接口的集中封装：路径与 contracts/api.md 一一对应，页面只依赖本模块。
import { api, fetchHealth } from './client'
import type {
  AlertItem,
  AlertListParams,
  AlertListResponse,
  AttackerDetailParams,
  AttackerDetailResponse,
  AttackerListParams,
  AttackerListResponse,
  HealthResponse,
  OverviewResponse,
  RuleEffectivenessResponse,
  RuleItem,
  RuleListParams,
  RuleListResponse,
  RuleUpdatePayload,
  SessionTimelineResponse,
  TrendResponse
} from '../types'

export { ApiError, errorMessage, fetchHealth } from './client'
export type { HealthResponse } from '../types'

export const honeypotApi = {
  /** 3.1 GET /api/health（503 降级也返回状态体，网络异常返回 null）。 */
  getHealth(): Promise<HealthResponse | null> {
    return fetchHealth()
  },
  /** 3.2 GET /api/overview */
  getOverview(): Promise<OverviewResponse> {
    return api.get<OverviewResponse>('/api/overview')
  },
  /** 3.3 GET /api/attackers */
  getAttackers(params: AttackerListParams): Promise<AttackerListResponse> {
    return api.get<AttackerListResponse>('/api/attackers', { ...params })
  },
  /** 3.4 GET /api/attackers/{ip} */
  getAttackerDetail(ip: string, params: AttackerDetailParams = {}): Promise<AttackerDetailResponse> {
    return api.get<AttackerDetailResponse>(`/api/attackers/${encodeURIComponent(ip)}`, { ...params })
  },
  /** 3.5 GET /api/sessions/{session_id}/timeline */
  getSessionTimeline(sessionId: string): Promise<SessionTimelineResponse> {
    return api.get<SessionTimelineResponse>(
      `/api/sessions/${encodeURIComponent(sessionId)}/timeline`
    )
  },
  /** 3.6 GET /api/alerts */
  getAlerts(params: AlertListParams): Promise<AlertListResponse> {
    return api.get<AlertListResponse>('/api/alerts', { ...params })
  },
  /** 3.7 PATCH /api/alerts/{alert_id} */
  updateAlertRead(alertId: number, isRead: boolean): Promise<AlertItem> {
    return api.patch<AlertItem>(`/api/alerts/${alertId}`, { is_read: isRead })
  },
  /** 3.10 GET /api/trend */
  getTrend(days = 14): Promise<TrendResponse> {
    return api.get<TrendResponse>('/api/trend', { days })
  },
  /** 3.11 GET /api/rules/effectiveness */
  getRuleEffectiveness(limit = 50): Promise<RuleEffectivenessResponse> {
    return api.get<RuleEffectivenessResponse>('/api/rules/effectiveness', { limit })
  },
  /** 3.8 GET /api/rules（本版不单独建页面，供规则配置能力演示与运维调用）。 */
  getRules(params: RuleListParams = {}): Promise<RuleListResponse> {
    return api.get<RuleListResponse>('/api/rules', { ...params })
  },
  /** 3.9 PATCH /api/rules/{rule_code}（本版不单独建页面；带乐观并发校验）。 */
  updateRule(ruleCode: string, payload: RuleUpdatePayload): Promise<RuleItem> {
    return api.patch<RuleItem>(`/api/rules/${encodeURIComponent(ruleCode)}`, payload)
  }
}
