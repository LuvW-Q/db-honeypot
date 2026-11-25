<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '../components/EmptyState.vue'
import RiskBadge from '../components/RiskBadge.vue'
import { errorMessage, honeypotApi } from '../api'
import { useRefreshBus } from '../composables/refresh'
import {
  eventStatusLabel,
  eventTypeLabel,
  eventTypeZh,
  formatDateTime,
  formatDuration,
  formatEventId,
  formatNumber,
  intentMeta,
  ruleLabel,
  sessionStatusShort,
  shortSessionId,
  truncateSql
} from '../utils/format'
import type { AttackerDetailResponse, RuleHit, SessionEvent, SessionSummary, SessionTimelineResponse } from '../types'

const route = useRoute()
const router = useRouter()
const bus = useRefreshBus()

const loading = ref(true)
const error = ref<string | null>(null)
const detail = ref<AttackerDetailResponse | null>(null)
const timeline = ref<SessionTimelineResponse | null>(null)
const timelineLoading = ref(false)
const timelineError = ref<string | null>(null)
const activeSession = ref<string>('')
const filter = ref<'all' | 'auth' | 'query' | 'hits'>('all')

const ip = computed(() => String(route.params.ip ?? ''))
const attacker = computed(() => detail.value?.attacker ?? null)
const sessions = computed(() => [...(detail.value?.sessions ?? [])].sort((a, b) => (a.started_at < b.started_at ? 1 : -1)))
const current = computed(() => sessions.value.find((item) => item.session_id === activeSession.value) ?? sessions.value[0] ?? null)
const hits = computed(() => detail.value?.recent_rule_hits ?? [])

const hitsByEvent = computed(() => {
  const map = new Map<number, RuleHit[]>()
  for (const hit of timeline.value?.rule_hits ?? []) {
    const list = map.get(hit.event_id) ?? []
    list.push(hit)
    map.set(hit.event_id, list)
  }
  return map
})

const events = computed<SessionEvent[]>(() => {
  const list = timeline.value?.events ?? []
  if (filter.value === 'all') return list
  if (filter.value === 'hits') return list.filter((event) => hitsByEvent.value.has(event.event_id))
  return list.filter((event) => event.event_type === filter.value)
})

const filterCounts = computed(() => ({
  all: timeline.value?.events.length ?? 0,
  auth: (timeline.value?.events ?? []).filter((event) => event.event_type === 'auth').length,
  query: (timeline.value?.events ?? []).filter((event) => event.event_type === 'query').length,
  hits: timeline.value?.rule_hits.length ?? 0
}))

const riskDescription = computed(() => {
  switch (attacker.value?.risk_level) {
    case 'critical':
      return '系统检测到高对抗性威胁，建议立即排查该源地址相关会话并复核高危操作。'
    case 'high':
      return '该源地址存在明确攻击意图，建议持续观察并阻断异常会话。'
    case 'medium':
      return '存在可疑探测行为，建议结合时间线证据人工复核。'
    default:
      return '当前风险较低，保持常规监测。'
  }
})

const maskedBanner = '安全脱敏保证：系统已对凭据与个人隐私进行脱敏处理，所有口令均以 *** 展示 · 不展示明文口令 · 不执行任何采集 SQL'

function openSession(session: SessionSummary): void {
  if (activeSession.value === session.session_id) return
  activeSession.value = session.session_id
  void router.replace({ query: { ...route.query, session: session.session_id } })
  void loadTimeline(session.session_id)
}

async function loadDetail(): Promise<void> {
  loading.value = true
  error.value = null
  bus.refreshing.value = true
  try {
    const data = await honeypotApi.getAttackerDetail(ip.value, { session_limit: 30, hit_limit: 20 })
    detail.value = data
    const querySession = typeof route.query.session === 'string' ? route.query.session : ''
    const exists = data.sessions.some((item) => item.session_id === querySession)
    activeSession.value = exists ? querySession : (data.sessions[0]?.session_id ?? '')
    if (activeSession.value) await loadTimeline(activeSession.value)
    bus.markUpdated()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
    bus.refreshing.value = false
  }
}

async function loadTimeline(sessionId: string): Promise<void> {
  if (!sessionId) return
  timelineLoading.value = true
  timelineError.value = null
  try {
    timeline.value = await honeypotApi.getSessionTimeline(sessionId)
  } catch (caught) {
    timelineError.value = errorMessage(caught)
    timeline.value = null
  } finally {
    timelineLoading.value = false
  }
}

watch(() => route.query.session, (value) => {
  if (typeof value === 'string' && value && value !== activeSession.value) {
    activeSession.value = value
    void loadTimeline(value)
  }
})

function riskLabel(level?: string | null): string {
  switch (level) {
    case 'critical':
      return '严重威胁'
    case 'high':
      return '高风险'
    case 'medium':
      return '中风险'
    case 'low':
      return '低风险'
    default:
      return '未知'
  }
}

function eventIcon(event: SessionEvent): string {
  if (event.event_type === 'query') return 'terminal'
  if (event.event_type === 'auth') return event.status === 'success' ? 'verified_user' : 'key_off'
  if (event.event_type === 'disconnect') return 'link_off'
  return 'link'
}

function eventIconBox(event: SessionEvent): string {
  if (event.event_type === 'auth' && event.status !== 'success') return 'bg-sev-critical/15 text-sev-critical'
  if (event.event_type === 'auth' && event.status === 'success') return 'bg-secondary/15 text-secondary'
  if (event.event_type === 'query') return 'bg-primary/15 text-primary'
  return 'bg-surface-container-highest text-on-surface-variant'
}

watch(() => bus.tick.value, () => void loadDetail())
onMounted(() => void loadDetail())
</script>

<template>
  <div class="flex flex-col gap-space-lg">
    <div data-region="AD-HEAD" class="flex flex-col gap-space-md">
      <div class="flex flex-wrap items-center gap-space-sm font-code-sm text-code-sm text-outline">
        <router-link to="/attackers" class="flex items-center gap-1 text-primary hover:underline">
          <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">arrow_back</span>
          返回攻击者列表
        </router-link>
        <span>/</span>
        <span class="uppercase tracking-wider">TARGET IP:</span>
        <span class="mono text-on-surface">{{ ip }}</span>
        <span v-if="attacker" class="rounded bg-surface-container-high px-space-sm py-0.5 font-label-badge text-label-badge text-on-surface-variant">
          {{ attacker.network_scope_label ?? '未知归属' }}
        </span>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-space-md">
        <div class="flex items-center gap-space-md">
          <h1 class="mono text-headline-lg font-bold text-on-surface">{{ ip }}</h1>
          <RiskBadge v-if="attacker" :level="attacker.risk_level" :score="attacker.risk_score" show-score />
        </div>
        <div class="flex flex-wrap gap-space-md font-code-sm text-code-sm">
          <div class="rounded bg-surface-container-low px-space-md py-1">
            <span class="text-outline">综合风险分</span>
            <span class="mono ml-1 text-sev-critical">{{ attacker?.risk_score ?? '—' }}</span>
          </div>
          <div class="rounded bg-surface-container-low px-space-md py-1">
            <span class="text-outline">累计会话</span>
            <span class="mono ml-1 text-on-surface">{{ attacker?.session_count ?? '—' }}</span>
          </div>
          <div class="rounded bg-surface-container-low px-space-md py-1">
            <span class="text-outline">执行查询</span>
            <span class="mono ml-1 text-on-surface">{{ formatNumber(attacker?.total_queries) }}</span>
          </div>
          <div class="rounded bg-surface-container-low px-space-md py-1">
            <span class="text-outline">认证尝试</span>
            <span class="mono ml-1 text-on-surface">{{ attacker?.total_auth_attempts ?? '—' }}</span>
            <span class="ml-1 text-outline">(失败 {{ attacker?.total_auth_failures ?? 0 }} / 成功 {{ attacker?.auth_success_count ?? 0 }})</span>
          </div>
        </div>
      </div>
      <div data-region="AD-BANNER" class="flex flex-wrap items-center gap-space-sm rounded border border-secondary/30 bg-secondary/5 px-space-md py-1.5 font-code-sm text-code-sm text-secondary">
        <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">verified_user</span>
        {{ maskedBanner }}
        <span class="ml-auto rounded bg-surface-container-high px-2 py-0.5 font-label-badge text-label-badge text-on-surface-variant">AUTO-MASKED</span>
      </div>
    </div>

    <div v-if="error" class="rounded-lg border border-sev-critical/40 bg-sev-critical/10 px-space-lg py-space-md text-body-sm text-sev-critical" role="alert">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="loadDetail">重试</button>
    </div>

    <div v-else-if="loading" class="flex min-h-72 items-center justify-center gap-2 font-code-sm text-code-sm text-outline" role="status">
      <span class="material-symbols-outlined animate-spin text-icon-lg" aria-hidden="true">progress_activity</span>正在加载攻击者画像…
    </div>

    <template v-else-if="attacker">
      <div class="grid grid-cols-1 gap-gutter xl:grid-cols-12">
        <section data-region="AD-PROFILE" class="flex flex-col rounded-lg bg-surface-container-low p-space-lg shadow-panel xl:col-span-5">
          <div class="mb-space-md flex items-center justify-between border-b border-surface-container-high pb-space-sm">
            <h2 class="flex items-center gap-2 text-headline-sm font-bold text-on-surface">
              <span class="material-symbols-outlined text-icon-md text-primary" aria-hidden="true">person</span>
              攻击者实体画像 (Profile)
            </h2>
            <code class="font-code-sm text-code-sm text-outline">v_attacker_profile_summary</code>
          </div>
          <dl class="grid grid-cols-profile gap-x-space-lg gap-y-space-sm text-body-sm">
            <dt class="text-on-surface-variant">来源 IP 归属</dt>
            <dd class="mono text-on-surface">{{ attacker.source_ip }}（{{ attacker.network_scope_label ?? '未知' }}）</dd>
            <dt class="text-on-surface-variant">首次出现时间</dt>
            <dd class="mono text-on-surface">{{ formatDateTime(attacker.first_seen) }}</dd>
            <dt class="text-on-surface-variant">最近活跃时间</dt>
            <dd class="mono text-on-surface">{{ formatDateTime(attacker.last_seen) }}</dd>
            <dt class="text-on-surface-variant">累计连接与会话</dt>
            <dd class="mono text-on-surface">{{ attacker.total_connections }} 次 (平均时长 {{ formatDuration(attacker.avg_session_seconds) }})</dd>
            <dt class="text-on-surface-variant">认证尝试行为</dt>
            <dd class="mono text-on-surface">{{ attacker.total_auth_attempts }} 次 (失败 {{ attacker.total_auth_failures }}, 成功 {{ attacker.auth_success_count ?? 0 }})</dd>
            <dt class="text-on-surface-variant">敏感查询捕获量</dt>
            <dd class="mono text-on-surface">{{ formatNumber(attacker.total_queries) }} 条 (高危操作 {{ attacker.high_risk_op_count ?? 0 }} 次)</dd>
            <dt class="text-on-surface-variant">高危操作次数</dt>
            <dd class="mono text-on-surface">{{ attacker.high_risk_op_count ?? 0 }} 次</dd>
          </dl>

          <div class="mt-space-lg rounded border border-sev-critical/40 bg-sev-critical/10 p-space-md">
            <div class="flex flex-wrap items-center justify-between gap-space-sm">
              <span class="font-label-badge text-label-badge uppercase tracking-wider text-sev-critical">THREAT LEVEL: {{ attacker.risk_level?.toUpperCase() }}</span>
              <span class="mono text-code-sm text-sev-critical">风险评分: {{ attacker.risk_score }}（{{ riskLabel(attacker.risk_level) }}）</span>
            </div>
            <p class="mt-space-xs text-body-sm text-on-surface-variant">{{ riskDescription }}</p>
            <div class="mt-space-md flex flex-col gap-space-xs">
              <button type="button" class="btn-danger-ghost w-full" disabled aria-disabled="true" title="演示未开放：系统仅分析，不执行主动反制">
                <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">block</span>联动 DMZ 隔离
              </button>
              <span class="text-center font-code-sm text-code-sm text-outline">演示未开放：系统仅分析，不执行主动反制</span>
            </div>
          </div>
        </section>

        <section data-region="AD-CHAIN" class="flex flex-col rounded-lg bg-surface-container-low p-space-lg shadow-panel xl:col-span-7">
          <div class="mb-space-md flex items-center justify-between border-b border-surface-container-high pb-space-sm">
            <h2 class="flex items-center gap-2 text-headline-sm font-bold text-on-surface">
              <span class="material-symbols-outlined text-icon-md text-primary" aria-hidden="true">account_tree</span>
              攻击意图判定与规则证据链
            </h2>
            <span class="font-code-sm text-code-sm text-outline">FR-451 证据链视图</span>
          </div>
          <div v-if="hits.length === 0" class="py-space-lg text-center text-body-sm text-on-surface-variant">暂无规则命中证据</div>
          <div v-else class="flex flex-col gap-space-sm">
            <article v-for="(hit, index) in hits" :key="hit.hit_id" class="rounded border border-surface-container-high bg-surface-container p-space-md">
              <div class="flex flex-wrap items-center gap-space-sm">
                <span class="rounded bg-sev-critical/15 px-1.5 py-0.5 font-label-badge text-label-badge font-bold text-sev-critical">CRITICAL</span>
                <span class="text-body-md font-semibold text-on-surface">{{ hit.rule_code }} · {{ ruleLabel(hit.rule_code) }}</span>
                <span class="ml-auto font-code-sm text-code-sm text-sev-critical">+{{ hit.risk_weight }} 分</span>
              </div>
              <div class="mt-space-xs flex flex-wrap items-center gap-space-sm font-code-sm text-code-sm text-on-surface-variant">
                <span>规则强度 {{ hit.rule_version }} · 意图 {{ intentMeta(hit.intent_type).label }}</span>
                <span>· 事件 {{ formatEventId(hit.event_id) }}</span>
                <span class="ml-auto">最近命中：{{ formatDateTime(hit.triggered_at) }}</span>
              </div>
              <p class="mt-space-sm rounded bg-surface-container-lowest p-space-sm font-code-sm text-code-sm leading-relaxed text-on-surface">
                <span class="text-outline">证据摘要 / </span>{{ hit.evidence_summary }}
              </p>
              <div v-if="index === hits.length - 1" class="mt-1 font-code-sm text-code-sm text-outline">正在陆续聚合证据链 ({{ hits.length }} 条)</div>
            </article>
          </div>
        </section>
      </div>

      <!-- AD-SESSIONS -->
      <section data-region="AD-SESSIONS" class="flex flex-col rounded-lg bg-surface-container-low shadow-panel">
        <div class="flex flex-wrap items-center justify-between gap-space-sm px-space-lg py-space-md">
          <h2 class="flex items-center gap-2 text-headline-sm font-bold text-on-surface">
            <span class="material-symbols-outlined text-icon-md text-primary" aria-hidden="true">list_alt</span>
            攻击者关联历史会话 (v_session_risk_summary)
          </h2>
          <span class="font-code-sm text-code-sm text-outline">共 {{ sessions.length }} 条关联记录 · 点击行切换右侧时间线详情</span>
        </div>
        <div class="overflow-x-auto">
          <table class="tbl">
            <thead>
              <tr>
                <th>会话识别码 (SESSION_ID)</th>
                <th>时间跨度 (UTC+8)</th>
                <th>事件整体</th>
                <th>含 SQL 数</th>
                <th>会话最高风险分</th>
                <th>会话状态</th>
                <th class="text-right">操作 / 展开</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="session in sessions" :key="session.session_id">
                <td>
                  <button type="button" class="flex items-center gap-1.5 font-mono text-code-md" @click="openSession(session)">
                    <span class="h-1.5 w-1.5 rounded-full" :class="session.session_id === activeSession ? 'bg-primary' : 'bg-outline'" aria-hidden="true" />
                    <span class="text-on-surface">{{ shortSessionId(session.session_id) }}</span>
                    <span v-if="session.session_id === activeSession" class="rounded bg-primary/15 px-1 font-label-badge text-label-badge text-primary">当前查看</span>
                  </button>
                </td>
                <td class="mono text-code-sm">{{ formatDateTime(session.started_at) }} → {{ session.ended_at ? formatDateTime(session.ended_at) : '进行中' }}</td>
                <td class="mono text-code-sm">{{ session.event_count }} 个事件</td>
                <td class="mono text-code-sm">{{ session.query_count }} 条</td>
                <td><RiskBadge :level="session.risk_level" :score="session.risk_score" show-score size="small" /></td>
                <td class="text-code-sm">{{ sessionStatusShort(session.session_status) }}</td>
                <td class="text-right">
                  <button type="button" class="font-code-sm text-code-sm text-primary hover:underline" @click="openSession(session)">
                    时间线展开
                  </button>
                </td>
              </tr>
              <tr v-if="sessions.length === 0">
                <td colspan="7" class="py-space-lg text-center text-on-surface-variant">暂无关联会话</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- AD-TIMELINE -->
      <section data-region="AD-TIMELINE" class="flex flex-col rounded-lg bg-surface-container-low shadow-panel">
        <div class="flex flex-wrap items-center justify-between gap-space-sm px-space-lg py-space-md">
          <div class="flex items-center gap-space-sm">
            <h2 class="flex items-center gap-2 text-headline-sm font-bold text-on-surface">
              <span class="material-symbols-outlined text-icon-md text-primary" aria-hidden="true">timeline</span>
              会话执行溯源时间线 (Session Event Timeline)
            </h2>
            <span v-if="current" class="mono text-code-sm text-outline">{{ shortSessionId(current.session_id) }}</span>
          </div>
          <div class="flex flex-wrap gap-1" role="tablist" aria-label="时间线筛选">
            <button
              v-for="item in [
                { key: 'all', label: `全部 ${filterCounts.all}` },
                { key: 'auth', label: `仅认证 ${filterCounts.auth}` },
                { key: 'query', label: `仅查询 SQL ${filterCounts.query}` },
                { key: 'hits', label: `仅规则命中 ${filterCounts.hits}` }
              ]"
              :key="item.key"
              type="button"
              role="tab"
              :aria-selected="filter === item.key"
              class="rounded px-space-sm py-1 font-body-sm text-body-sm transition-colors"
              :class="filter === item.key ? 'bg-primary-container font-semibold text-on-primary-container' : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'"
              @click="filter = item.key as 'all' | 'auth' | 'query' | 'hits'"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
        <p class="border-t border-surface-container-high px-space-lg py-space-sm font-code-sm text-code-sm text-outline">
          严格依据 FR-085 按 event_time 升序排列，所有凭据与指纹按 FR-088 隐藏脱敏。
        </p>

        <div v-if="timelineError" class="px-space-lg pb-space-md text-body-sm text-sev-critical">时间线加载失败：{{ timelineError }}</div>
        <div v-else-if="timelineLoading" class="px-space-lg pb-space-md font-code-sm text-code-sm text-outline">加载时间线…</div>
        <div v-else-if="events.length === 0" class="px-space-lg pb-space-md">
          <EmptyState title="当前筛选无事件" hint="切换筛选条件或选择其它会话查看时间线。" />
        </div>
        <ol v-else class="flex flex-col gap-space-sm px-space-lg pb-space-lg">
          <li
            v-for="event in events"
            :key="event.event_id"
            class="flex gap-space-md rounded border border-surface-container-high bg-surface-container p-space-md"
            :class="hitsByEvent.get(event.event_id) ? 'border-l-2 border-l-sev-critical' : ''"
          >
            <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full" :class="eventIconBox(event)">
              <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">{{ eventIcon(event) }}</span>
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-space-sm">
                <span class="font-code-md text-code-md font-semibold text-on-surface">{{ eventTypeLabel(event.event_type) }}</span>
                <span class="font-code-sm text-code-sm text-outline">{{ formatDateTime(event.event_time) }}</span>
                <span class="font-code-sm text-code-sm text-on-surface-variant">{{ eventTypeZh(event.event_type) }} · {{ eventStatusLabel(event.status) }}</span>
                <span
                  v-for="hit in hitsByEvent.get(event.event_id) ?? []"
                  :key="hit.hit_id"
                  class="rounded bg-sev-critical/15 px-1.5 py-0.5 font-label-badge text-label-badge font-semibold text-sev-critical"
                >
                  {{ hit.rule_code }} +{{ hit.risk_weight }}
                </span>
                <span class="ml-auto font-code-sm text-code-sm text-outline">EVENT ID: {{ event.event_id }}</span>
              </div>

              <div class="mt-space-xs flex flex-col gap-1">
                <p v-if="event.event_type === 'connect'" class="text-body-sm text-on-surface-variant">
                  客户端 TCP 握手建立 · 源端口 {{ current?.source_port ?? '—' }} → 诱饵监听端口 3306 · 协议探测握手完成
                </p>
                <p v-else-if="event.event_type === 'disconnect'" class="text-body-sm text-on-surface-variant">
                  客户端主动断开 TCP 链路 · 会话状态 {{ sessionStatusShort(current?.session_status) }}
                </p>
                <p v-else-if="event.event_type === 'auth'" class="text-body-sm text-on-surface-variant">
                  尝试用户名 <span class="mono text-on-surface">“{{ event.username ?? '未知' }}”</span> · 口令
                  <span class="mono text-on-surface">“{{ event.credential_masked ?? '***' }}”</span> · 响应：{{ eventStatusLabel(event.status) }}
                  <span class="mono text-outline">({{ event.response_ms }} ms)</span>
                </p>
                <template v-else-if="event.event_type === 'query'">
                  <div class="rounded bg-surface-container-lowest p-space-sm">
                    <div class="mb-1 font-label-badge text-label-badge uppercase tracking-wider text-outline">SQL Payload (Normalized)</div>
                    <p class="mono truncate text-code-md text-primary" :title="event.sql_statement ?? ''">{{ truncateSql(event.sql_statement) }}</p>
                    <pre v-if="event.normalized_sql && event.normalized_sql !== event.sql_statement" class="mt-1 whitespace-pre-wrap break-all font-mono text-code-sm text-on-surface-variant">{{ event.normalized_sql }}</pre>
                  </div>
                  <div class="flex flex-wrap gap-space-md font-code-sm text-code-sm text-outline">
                    <span>返回 {{ event.returned_rows }} 行结果</span>
                    <span>响应耗时 {{ event.response_ms }} ms</span>
                    <span v-if="event.payload_truncated" class="text-sev-medium">载荷已截断</span>
                    <span>语句类型 {{ event.statement_type ?? '—' }}</span>
                  </div>
                </template>
              </div>
            </div>
          </li>
        </ol>

        <div data-region="AD-FOOTER" class="flex flex-wrap items-center justify-between gap-space-sm border-t border-surface-container-high px-space-lg py-space-md">
          <span class="flex items-center gap-2 font-code-sm text-code-sm text-outline">
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">shield</span>
            分析对象: {{ attacker.source_ip }} | 关联会话: {{ sessions.length }} | 当前检查会话: {{ current ? shortSessionId(current.session_id) : '—' }}
          </span>
          <div class="flex flex-wrap gap-space-sm">
            <button type="button" class="btn-secondary btn-disabled" disabled aria-disabled="true" title="演示未开放：导出功能不在本版范围">导出取证报告 (JSON/CSV)</button>
            <button type="button" class="btn-primary btn-disabled" disabled aria-disabled="true" title="演示未开放：需要规则下发通道">同步证据链至防御规则库</button>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
