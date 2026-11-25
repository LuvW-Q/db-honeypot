<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import PaginationBar from '../components/PaginationBar.vue'
import RiskBadge from '../components/RiskBadge.vue'
import { errorMessage, honeypotApi } from '../api'
import { pushToast } from '../composables/toast'
import { useRefreshBus } from '../composables/refresh'
import {
  alertTypeLabel,
  alertTypeRule,
  addDays,
  formatDateTime,
  formatDateTimeShort,
  formatPctValue,
  formatPercent,
  ruleLabel,
  shortSessionId
} from '../utils/format'
import type { AlertItem, AlertSummaryResponse, AlertType, Severity } from '../types'

const route = useRoute()
const router = useRouter()
const bus = useRefreshBus()

const READ_TABS = [
  { value: 'all', label: '全部告警' },
  { value: 'false', label: '未读' },
  { value: 'true', label: '已读' }
] as const

const SEVERITIES: Array<{ value: string; label: string }> = [
  { value: 'critical', label: '严重' },
  { value: 'high', label: '高危' },
  { value: 'medium', label: '中危' },
  { value: 'low', label: '低危' }
]

const ALERT_TYPES: Array<{ value: string; label: string }> = [
  { value: 'bruteforce', label: '认证爆破 (R02)' },
  { value: 'data_dump', label: '批量拖库 (R04)' },
  { value: 'destructive', label: '破坏性操作 (R05)' }
]

const TIME_PRESETS = [
  { value: '1', label: '今日' },
  { value: '3', label: '近 3 天' },
  { value: '7', label: '近 7 天' }
] as const

const loading = ref(true)
const error = ref<string | null>(null)
const items = ref<AlertItem[]>([])
const summary = ref<AlertSummaryResponse | null>(null)
const total = ref(0)
const totalPages = ref(1)
const selected = reactive(new Set<number>())
const batchRunning = ref(false)

const filters = reactive({
  is_read: 'all' as 'all' | 'true' | 'false',
  severity: [] as string[],
  alert_type: 'all',
  days: '7',
  page: 1,
  page_size: 20
})

function utc8DateString(date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date)
  const get = (type: string): string => parts.find((item) => item.type === type)?.value ?? '01'
  return `${get('year')}-${get('month')}-${get('day')}`
}

function fromParam(): string | undefined {
  const days = Number(filters.days)
  if (!Number.isFinite(days) || days <= 0) return undefined
  const today = utc8DateString()
  const startDate = addDays(today, -(days - 1))
  return new Date(`${startDate}T00:00:00+08:00`).toISOString()
}

function toParam(): string | undefined {
  const from = fromParam()
  if (!from) return undefined
  const end = new Date(from)
  end.setUTCDate(end.getUTCDate() + Number(filters.days))
  return end.toISOString()
}

const timeLabel = computed(() => TIME_PRESETS.find((item) => item.value === filters.days)?.label ?? '自定义')

const unreadCount = computed(() => summary.value?.unread ?? 0)
const readCount = computed(() => summary.value?.read ?? 0)
const allCount = computed(() => summary.value?.total ?? 0)

const resolutionText = computed(() =>
  summary.value ? formatPercent(summary.value.resolution_rate) : '—'
)

const todayDeltaText = computed(() => {
  const value = summary.value?.today_delta_pct
  if (value === null || value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${formatPctValue(value)}`
})

const peakText = computed(() => {
  const peak = summary.value?.peak_window
  if (!peak) return '暂无今日高峰'
  return `今日高峰 ${formatDateTimeShort(peak.start).slice(6)} 时段 · ${peak.count} 条`
})

const selectedCount = computed(() => selected.size)

function readQuery(): void {
  const query = route.query
  const isRead = typeof query.is_read === 'string' && (query.is_read === 'true' || query.is_read === 'false') ? query.is_read : 'all'
  const severity = typeof query.severity === 'string' && SEVERITIES.some((item) => item.value === query.severity) ? query.severity : ''
  const alertType = typeof query.alert_type === 'string' && ALERT_TYPES.some((item) => item.value === query.alert_type) ? query.alert_type : 'all'
  const days = typeof query.days === 'string' && TIME_PRESETS.some((item) => item.value === query.days) ? query.days : '7'
  const page = Number(query.page ?? 1)
  filters.is_read = isRead
  filters.severity = severity ? [severity] : []
  filters.alert_type = alertType
  filters.days = days
  filters.page = Number.isFinite(page) && page >= 1 ? Math.floor(page) : 1
}

function writeQuery(): void {
  const query: Record<string, string> = {}
  if (filters.is_read !== 'all') query.is_read = filters.is_read
  if (filters.severity.length > 0) query.severity = filters.severity[0]
  if (filters.alert_type !== 'all') query.alert_type = filters.alert_type
  if (filters.days !== '7') query.days = filters.days
  if (filters.page > 1) query.page = String(filters.page)
  if (JSON.stringify(query) !== JSON.stringify(route.query)) {
    void router.replace({ query })
  }
}

function applyFilter(patch: Partial<typeof filters>, resetPage = true): void {
  Object.assign(filters, patch)
  if (resetPage) filters.page = 1
  selected.clear()
  writeQuery()
  void load()
}

function toggleSeverity(value: string): void {
  const list = new Set(filters.severity)
  if (list.has(value)) list.delete(value)
  else list.add(value)
  applyFilter({ severity: [...list] })
}

function toggleSelected(alertId: number): void {
  if (selected.has(alertId)) selected.delete(alertId)
  else selected.add(alertId)
}

function clearSelection(): void {
  selected.clear()
}

function toggleSelectAll(): void {
  if (selected.size === items.value.length) selected.clear()
  else items.value.forEach((item) => selected.add(item.alert_id))
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  bus.refreshing.value = true
  try {
    const from = fromParam()
    const [list, summaryData] = await Promise.all([
      honeypotApi.getAlerts({
        page: filters.page,
        page_size: filters.page_size,
        alert_type: filters.alert_type === 'all' ? undefined : (filters.alert_type as AlertType),
        severity: filters.severity.length ? filters.severity : undefined,
        is_read: filters.is_read === 'all' ? undefined : filters.is_read === 'true',
        from,
        sort: 'created_at',
        order: 'desc'
      }),
      honeypotApi.getAlertsSummary({ from, to: toParam() })
    ])
    items.value = list.items
    total.value = list.total
    totalPages.value = Math.max(1, list.total_pages)
    summary.value = summaryData
    if (list.total_pages > 0 && filters.page > list.total_pages) {
      filters.page = 1
      writeQuery()
    }
    bus.markUpdated()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
    bus.refreshing.value = false
  }
}

async function patchOne(alertId: number): Promise<{ ok: boolean; message?: string }> {
  try {
    await honeypotApi.updateAlertRead(alertId, true)
    return { ok: true }
  } catch (caught) {
    return { ok: false, message: errorMessage(caught) }
  }
}

async function batchMarkRead(): Promise<void> {
  const ids = [...selected]
  if (ids.length === 0 || batchRunning.value) return
  batchRunning.value = true
  const failures: string[] = []
  let succeeded = 0
  // 并发 2：契约要求逐条 PATCH，避免一次事务锁过多行。
  for (let index = 0; index < ids.length; index += 2) {
    const chunk = ids.slice(index, index + 2)
    const results = await Promise.all(chunk.map((id) => patchOne(id)))
    results.forEach((result) => {
      if (result.ok) succeeded += 1
      else failures.push(result.message ?? '未知错误')
    })
  }
  batchRunning.value = false
  clearSelection()
  if (failures.length === 0) {
    pushToast('success', `已标记 ${succeeded} 条告警为已读`, '列表与统计卡已同步更新')
  } else if (succeeded > 0) {
    pushToast('partial', `部分成功：${succeeded} 条已读，${failures.length} 条失败`, failures.slice(0, 3).join('\n'))
  } else {
    pushToast('error', '批量标记失败', failures[0] ?? '请稍后重试')
  }
  void load()
}

async function markOne(alert: AlertItem): Promise<void> {
  try {
    await honeypotApi.updateAlertRead(alert.alert_id, true)
    pushToast('success', `告警 #${alert.alert_id} 已标记已读`)
    void load()
  } catch (caught) {
    pushToast('error', '标记已读失败', errorMessage(caught))
  }
}

function evidenceLink(alert: AlertItem): string {
  return `/attackers/${alert.source_ip}?session=${alert.session_id}`
}

watch(() => route.query, () => {
  readQuery()
  void load()
})
watch(() => bus.tick.value, () => void load())
onMounted(() => {
  readQuery()
  writeQuery()
  void load()
})
</script>

<template>
  <div class="flex flex-col gap-space-lg">
    <div data-region="AL-HEAD">
    <PageHeader title="告警列表" subtitle="ALERTS">
      <template #actions>
        <div class="flex items-center gap-space-sm">
          <span class="flex items-center gap-1.5 rounded bg-surface-container-high px-space-sm py-1 font-code-sm text-code-sm text-secondary">
            <span class="relative flex h-2 w-2">
              <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-secondary opacity-70" />
              <span class="relative inline-flex h-2 w-2 rounded-full bg-secondary" />
            </span>
            规则引擎: ACTIVE (R01-R05)
          </span>
          <button
            type="button"
            class="btn-primary"
            :disabled="selectedCount === 0 || batchRunning"
            :title="selectedCount === 0 ? '请先勾选告警' : `批量标记 ${selectedCount} 条为已读`"
            @click="batchMarkRead"
          >
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">done_all</span>
            {{ batchRunning ? '批量处理中…' : `批量标记已读 (${selectedCount})` }}
          </button>
        </div>
      </template>
    </PageHeader>
    </div>

    <div v-if="error" class="rounded-lg border border-sev-critical/40 bg-sev-critical/10 px-space-lg py-space-md text-body-sm text-sev-critical" role="alert">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="load">重试</button>
    </div>

    <!-- AL-STATS -->
    <div data-region="AL-STATS" class="grid grid-cols-1 gap-gutter sm:grid-cols-2 xl:grid-cols-4">
      <div class="flex flex-col rounded-lg bg-surface-container-low p-space-lg shadow-panel">
        <span class="font-code-sm text-code-sm uppercase tracking-wider text-outline">告警总数</span>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-headline-lg font-bold text-on-surface">{{ summary?.total ?? '—' }}</span>
          <span class="font-code-sm text-code-sm text-secondary">今日 +{{ summary?.today_new ?? 0 }} ({{ todayDeltaText }})</span>
        </div>
      </div>
      <div class="flex flex-col rounded-lg bg-surface-container-low p-space-lg shadow-panel">
        <span class="font-code-sm text-code-sm uppercase tracking-wider text-outline">未读告警</span>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-headline-lg font-bold text-sev-critical">{{ summary?.unread ?? '—' }}</span>
          <span class="font-code-sm text-code-sm text-outline">待处理 (PENDING)</span>
        </div>
      </div>
      <div class="flex flex-col rounded-lg bg-surface-container-low p-space-lg shadow-panel">
        <span class="font-code-sm text-code-sm uppercase tracking-wider text-outline">处置完成率</span>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-headline-lg font-bold text-secondary">{{ resolutionText }}</span>
          <span class="font-code-sm text-code-sm text-outline">已读 {{ readCount }} / 共 {{ allCount }}</span>
        </div>
      </div>
      <div class="flex flex-col rounded-lg bg-surface-container-low p-space-lg shadow-panel">
        <span class="font-code-sm text-code-sm uppercase tracking-wider text-outline">今日告警峰值</span>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-headline-lg font-bold text-sev-high">{{ summary?.peak_window?.count ?? 0 }}</span>
          <span class="font-code-sm text-code-sm text-outline">{{ peakText }}</span>
        </div>
      </div>
    </div>

    <!-- AL-FILTER -->
    <section data-region="AL-FILTER" class="flex flex-col gap-space-md rounded-lg bg-surface-container-low p-space-lg shadow-panel">
      <div class="flex flex-wrap items-center gap-space-sm">
        <div class="flex items-center gap-1 rounded bg-surface-container-lowest p-0.5">
          <button
            v-for="tab in READ_TABS"
            :key="tab.value"
            type="button"
            class="rounded px-space-md py-1 font-body-sm text-body-sm transition-colors"
            :class="filters.is_read === tab.value ? 'bg-primary-container font-semibold text-on-primary-container' : 'text-on-surface-variant hover:text-on-surface'"
            :aria-pressed="filters.is_read === tab.value"
            @click="applyFilter({ is_read: tab.value })"
          >
            {{ tab.label }}
            <span class="ml-1 font-code-sm text-code-sm opacity-80">
              {{ tab.value === 'false' ? unreadCount : tab.value === 'true' ? readCount : allCount }}
            </span>
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-1">
          <span class="mr-1 font-code-sm text-code-sm text-outline">严重度:</span>
          <button
            v-for="item in SEVERITIES"
            :key="item.value"
            type="button"
            class="rounded px-2 py-0.5 font-label-badge text-label-badge transition-colors"
            :class="filters.severity.includes(item.value) ? 'bg-primary-container font-semibold text-on-primary-container' : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'"
            :aria-pressed="filters.severity.includes(item.value)"
            @click="toggleSeverity(item.value)"
          >
            {{ item.label }} {{ summary?.by_severity?.[item.value as Severity] ?? 0 }}
          </button>
        </div>
        <div class="ml-auto flex items-center gap-space-sm">
          <label class="font-code-sm text-code-sm text-outline" for="alert-type">类型:</label>
          <select id="alert-type" v-model="filters.alert_type" class="select w-auto" @change="applyFilter({ alert_type: filters.alert_type })">
            <option value="all">全部类型</option>
            <option v-for="item in ALERT_TYPES" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
          <span class="font-code-sm text-code-sm text-outline">时间:</span>
          <div class="flex items-center gap-1">
            <button
              v-for="preset in TIME_PRESETS"
              :key="preset.value"
              type="button"
              class="rounded px-2 py-0.5 font-label-badge text-label-badge transition-colors"
              :class="filters.days === preset.value ? 'bg-primary-container font-semibold text-on-primary-container' : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'"
              :aria-pressed="filters.days === preset.value"
              @click="applyFilter({ days: preset.value })"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-space-sm border-t border-surface-container-high pt-space-sm">
        <div class="flex items-center gap-space-sm font-code-sm text-code-sm">
          <span class="text-on-surface-variant">筛选结果 <span class="text-on-surface">{{ total }}</span> 条</span>
          <span class="text-outline">·</span>
          <span class="text-outline">{{ timeLabel }} · 已选 {{ selectedCount }} 条</span>
          <button v-if="items.length > 0" type="button" class="text-primary hover:underline" @click="toggleSelectAll">
            {{ selected.size === items.length ? '取消全选' : '全选本页' }}
          </button>
        </div>
        <span class="font-code-sm text-code-sm text-outline">批量标记逐条提交（并发 2），失败条目不静默丢弃</span>
      </div>
    </section>

    <!-- AL-LIST -->
    <div v-if="loading && items.length === 0" class="flex min-h-60 items-center justify-center gap-2 font-code-sm text-code-sm text-outline" role="status">
      <span class="material-symbols-outlined animate-spin text-icon-lg" aria-hidden="true">progress_activity</span>加载告警…
    </div>
    <div v-else-if="items.length === 0" class="rounded-lg bg-surface-container-low shadow-panel">
      <EmptyState title="没有匹配的告警" hint="调整筛选条件或时间范围后再试；当前选择不会自动放宽。" icon="notifications_off">
        <button type="button" class="btn-secondary mt-space-sm" @click="applyFilter({ is_read: 'all', severity: [], alert_type: 'all', days: '7' })">重置筛选</button>
      </EmptyState>
    </div>
    <div v-else data-region="AL-CARDS" class="flex flex-col gap-space-sm">
      <article
        v-for="alert in items"
        :key="alert.alert_id"
        class="flex flex-col gap-space-sm rounded-lg bg-surface-container-low p-space-lg shadow-panel"
        :class="[alert.is_read ? '' : 'border-l-2 border-l-sev-critical', selected.has(alert.alert_id) ? 'ring-1 ring-primary/60' : '']"
      >
        <div class="flex flex-wrap items-center gap-space-sm">
          <input
            type="checkbox"
            class="h-4 w-4 accent-primary"
            :checked="selected.has(alert.alert_id)"
            :aria-label="`选择告警 ${alert.alert_id}`"
            @change="toggleSelected(alert.alert_id)"
          />
          <span class="h-1.5 w-1.5 rounded-full" :class="alert.is_read ? 'bg-outline' : 'bg-sev-critical'" aria-hidden="true" />
          <RiskBadge :level="alert.severity" size="small" />
          <span class="rounded bg-surface-container-high px-1.5 py-0.5 font-code-sm text-code-sm text-on-surface-variant">
            {{ alertTypeLabel(alert.alert_type) }} · {{ alertTypeRule(alert.alert_type) }}
          </span>
          <span class="font-code-sm text-code-sm text-outline">{{ ruleLabel(alert.rule_code) }}</span>
          <span class="ml-auto font-code-sm text-code-sm text-outline">
            {{ alert.is_read ? '已读' : '未读' }} · ID #{{ alert.alert_id }}
          </span>
        </div>
        <div class="flex flex-wrap items-baseline gap-space-sm">
          <h2 class="text-headline-sm font-semibold text-on-surface">{{ alert.title }}</h2>
          <span class="font-code-sm text-code-sm text-outline">首次 {{ formatDateTime(alert.first_seen_at) }} · 最近 {{ formatDateTime(alert.last_seen_at) }}</span>
          <span v-if="alert.occurrence_count > 1" class="rounded bg-sev-medium/15 px-1.5 py-0.5 font-label-badge text-label-badge text-sev-medium">
            聚合 {{ alert.occurrence_count }} 次
          </span>
        </div>
        <p class="rounded border border-surface-container-high bg-surface-container-lowest p-space-md font-code-sm text-code-sm leading-relaxed text-on-surface">
          <span class="text-outline">证据摘要 / </span>{{ alert.evidence_summary }}
        </p>
        <div class="flex flex-wrap items-center gap-space-md font-code-sm text-code-sm text-outline">
          <span class="flex items-center gap-1"><span class="material-symbols-outlined text-icon-xs" aria-hidden="true">dns</span>{{ alert.source_ip }}</span>
          <span class="flex items-center gap-1"><span class="material-symbols-outlined text-icon-xs" aria-hidden="true">lan</span>{{ shortSessionId(alert.session_id) }}</span>
          <span class="flex items-center gap-1"><span class="material-symbols-outlined text-icon-xs" aria-hidden="true">tag</span>{{ alert.rule_code }} · 命中 #{{ alert.latest_hit_id }}</span>
          <span class="ml-auto">创建 {{ formatDateTimeShort(alert.created_at) }}</span>
        </div>
        <div class="flex flex-wrap items-center gap-space-sm border-t border-surface-container-high pt-space-sm">
          <router-link :to="evidenceLink(alert)" class="btn-primary">
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">timeline</span>查看会话证据链
          </router-link>
          <button
            v-if="!alert.is_read"
            type="button"
            class="btn-secondary"
            @click="markOne(alert)"
          >
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">done</span>标记已读
          </button>
          <span v-else class="font-code-sm text-code-sm text-outline">已于 {{ alert.read_at ? formatDateTime(alert.read_at) : '—' }} 处置</span>
        </div>
      </article>

      <div data-region="AL-FOOTER" class="rounded-lg bg-surface-container-low px-space-lg shadow-panel">
        <PaginationBar
          :page="filters.page"
          :page-size="filters.page_size"
          :total="total"
          :total-pages="totalPages"
          :loading="loading"
          @update:page="(page) => applyFilter({ page }, false)"
        />
      </div>
    </div>
  </div>
</template>
