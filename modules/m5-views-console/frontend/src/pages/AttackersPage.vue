<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '../components/EmptyState.vue'
import IntentTag from '../components/IntentTag.vue'
import PageHeader from '../components/PageHeader.vue'
import PaginationBar from '../components/PaginationBar.vue'
import RiskBadge from '../components/RiskBadge.vue'
import RiskBar from '../components/RiskBar.vue'
import SectionCard from '../components/SectionCard.vue'
import { errorMessage, honeypotApi } from '../api'
import { useRefreshBus } from '../composables/refresh'
import {
  formatDateTime,
  formatDateTimeShort,
  formatNumber,
  intentLabel,
  intentMeta,
  splitCodes
} from '../utils/format'
import type { AttackerSummary, AttackersSummaryResponse } from '../types'

const route = useRoute()
const router = useRouter()
const bus = useRefreshBus()

const RISK_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'critical', label: '严重 (≥80)' },
  { value: 'high', label: '高 (60–79)' },
  { value: 'medium', label: '中 (30–59)' },
  { value: 'low', label: '低 (0–29)' }
]

const INTENT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'all', label: '全部意图类型 (All Patterns)' },
  { value: 'bruteforce', label: '暴力破解 (R02)' },
  { value: 'data_dump', label: '批量拖库 (R04)' },
  { value: 'recon', label: '踩点探测 (R03)' },
  { value: 'scanning', label: '端口扫描 (R01)' },
  { value: 'destructive', label: '破坏性操作 (R05)' }
]

function extraRuleCodes(item: AttackerSummary): string[] {
  const mainRule = item.main_intent ? intentMeta(item.main_intent.intent_type).rule : ''
  return splitCodes(item.triggered_rule_codes?.join(',') ?? '').filter((code) => code !== mainRule)
}


const SORT_OPTIONS = [
  { value: 'risk_score', label: '按风险分降序 (默认)' },
  { value: 'last_seen', label: '按最近出现降序' },
  { value: 'first_seen', label: '按首次出现降序' },
  { value: 'total_connections', label: '按累计会话降序' }
]

const loading = ref(true)
const error = ref<string | null>(null)
const items = ref<AttackerSummary[]>([])
const summary = ref<AttackersSummaryResponse | null>(null)
const total = ref(0)
const totalPages = ref(1)
const searchDraft = ref('')

const filters = reactive({
  q: '',
  risk_level: 'all',
  intent: 'all',
  sort: 'risk_score',
  page: 1,
  page_size: 20
})

const activeMatchText = computed(() => {
  const parts: string[] = []
  if (filters.q) parts.push(`搜索「${filters.q}」`)
  if (filters.risk_level !== 'all') parts.push(`等级 = ${filters.risk_level}`)
  if (filters.intent !== 'all') parts.push(`意图 = ${intentLabel(filters.intent)}`)
  return parts.length ? parts.join(' · ') : '默认视图'
})

const highRiskRatio = computed(() => {
  if (!summary.value || summary.value.total === 0) return 0
  return Math.round((summary.value.high_risk_count / summary.value.total) * 1000) / 10
})

function readQuery(): void {
  const query = route.query
  const q = typeof query.q === 'string' ? query.q.slice(0, 64) : ''
  const risk = typeof query.risk_level === 'string' ? query.risk_level : 'all'
  const intent = typeof query.intent === 'string' ? query.intent : 'all'
  const sort = typeof query.sort === 'string' ? query.sort : 'risk_score'
  const page = Number(query.page ?? 1)

  filters.q = q
  filters.risk_level = RISK_OPTIONS.some((item) => item.value === risk) ? risk : 'all'
  filters.intent = INTENT_OPTIONS.some((item) => item.value === intent) ? intent : 'all'
  filters.sort = SORT_OPTIONS.some((item) => item.value === sort) ? sort : 'risk_score'
  filters.page = Number.isFinite(page) && page >= 1 ? Math.floor(page) : 1
  searchDraft.value = filters.q
}

function writeQuery(): void {
  const query: Record<string, string> = {}
  if (filters.q) query.q = filters.q
  if (filters.risk_level !== 'all') query.risk_level = filters.risk_level
  if (filters.intent !== 'all') query.intent = filters.intent
  if (filters.sort !== 'risk_score') query.sort = filters.sort
  if (filters.page > 1) query.page = String(filters.page)
  const current = JSON.stringify(route.query)
  if (JSON.stringify(query) !== current) {
    void router.replace({ query })
  }
}

function applyFilter(patch: Partial<typeof filters>): void {
  Object.assign(filters, patch)
  filters.page = 1
  writeQuery()
  void load()
}

function submitSearch(): void {
  applyFilter({ q: searchDraft.value.trim() })
}

function clearFilters(): void {
  searchDraft.value = ''
  Object.assign(filters, { q: '', risk_level: 'all', intent: 'all', sort: 'risk_score', page: 1 })
  writeQuery()
  void load()
}

function changePage(page: number): void {
  filters.page = page
  writeQuery()
  void load()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  bus.refreshing.value = true
  try {
    const [list, summaryData] = await Promise.all([
      honeypotApi.getAttackers({
        page: filters.page,
        page_size: filters.page_size,
        q: filters.q || undefined,
        risk_level: filters.risk_level === 'all' ? undefined : filters.risk_level,
        intent_type: filters.intent === 'all' ? undefined : filters.intent,
        sort: filters.sort as 'risk_score' | 'last_seen' | 'first_seen' | 'total_queries' | 'total_connections',
        order: 'desc'
      }),
      honeypotApi.getAttackersSummary()
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

watch(
  () => route.query,
  () => {
    readQuery()
    void load()
  }
)
watch(() => bus.tick.value, () => void load())
onMounted(() => {
  readQuery()
  writeQuery()
  void load()
})
</script>

<template>
  <div class="flex flex-col gap-space-lg">
    <div data-region="AT-HEAD">
    <PageHeader title="攻击者列表" subtitle="ATTACKER LIST">
      <template #actions>
        <div class="flex items-stretch gap-space-sm">
          <div class="flex min-w-40 flex-col justify-between rounded-lg bg-surface-container-low p-space-md">
            <span class="flex items-center justify-between font-code-sm text-code-sm uppercase tracking-wider text-outline">
              高危及严重攻击源
              <span class="material-symbols-outlined text-icon-md text-sev-critical" aria-hidden="true">warning</span>
            </span>
            <div class="mt-1 flex items-baseline gap-1">
              <span class="text-headline-lg font-bold text-sev-critical">{{ summary?.high_risk_count ?? '—' }}</span>
              <span class="font-code-sm text-code-sm text-outline">/ {{ summary?.total ?? '—' }} IP</span>
            </div>
            <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-container-highest">
              <div class="h-full rounded-full bg-sev-critical" :style="{ width: `${highRiskRatio}%` }" />
            </div>
          </div>
          <div class="flex min-w-48 flex-col justify-between rounded-lg bg-surface-container-low p-space-md">
            <span class="flex items-center justify-between font-code-sm text-code-sm uppercase tracking-wider text-outline">
              最近活跃意图
              <span class="material-symbols-outlined text-icon-md text-tertiary" aria-hidden="true">bolt</span>
            </span>
            <template v-if="summary?.latest_intent">
              <span class="mt-1 font-code-md text-code-md font-semibold text-on-surface">
                {{ summary.latest_intent.rule_code }} {{ intentLabel(summary.latest_intent.intent_type) }}
              </span>
              <span class="font-code-sm text-code-sm text-on-surface-variant">IP: {{ summary.latest_intent.source_ip }} · {{ formatDateTimeShort(summary.latest_intent.last_detected_at) }}</span>
            </template>
            <span v-else class="mt-1 font-code-sm text-code-sm text-on-surface-variant">暂无规则命中</span>
          </div>
        </div>
      </template>
    </PageHeader>
    </div>

    <div v-if="error" class="rounded-lg border border-sev-critical/40 bg-sev-critical/10 px-space-lg py-space-md text-body-sm text-sev-critical" role="alert">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="load">重试</button>
    </div>

    <!-- AT-FILTER -->
    <section data-region="AT-FILTER" class="flex flex-col gap-space-md rounded-lg bg-surface-container-low p-space-lg shadow-panel">
      <div class="flex flex-col gap-space-sm lg:flex-row lg:items-center">
        <div class="flex flex-1 items-center gap-space-sm">
          <div class="relative flex-1">
            <span class="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-icon-md text-outline" aria-hidden="true">search</span>
            <input
              v-model="searchDraft"
              class="input pl-8"
              type="search"
              placeholder="搜索恶意 IP 地址（例: 192.168.* 或 10.0.*）…"
              aria-label="搜索攻击源 IP"
              @keyup.enter="submitSearch"
            />
          </div>
          <button type="button" class="btn-secondary whitespace-nowrap" @click="submitSearch">搜索</button>
        </div>
        <div class="flex items-center gap-space-sm">
          <button type="button" class="btn-secondary btn-disabled" aria-disabled="true" disabled title="演示未开放：导出功能不在本版范围">
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">download</span>导出遥测 CSV
          </button>
          <button type="button" class="btn-primary" @click="load">
            <span class="material-symbols-outlined text-icon-sm" :class="loading ? 'animate-spin' : ''" aria-hidden="true">sync</span>实时重查
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-space-md xl:grid-cols-3">
        <div class="flex flex-col gap-space-xs">
          <span class="font-code-sm text-code-sm text-outline">风险等级 (Risk Level Threshold):</span>
          <div class="flex flex-wrap gap-1">
            <button
              v-for="item in RISK_OPTIONS"
              :key="item.value"
              type="button"
              class="rounded px-space-sm py-1 font-label-badge text-label-badge transition-colors"
              :class="filters.risk_level === item.value ? 'bg-primary-container text-on-primary-container' : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'"
              @click="applyFilter({ risk_level: item.value })"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
        <div class="flex flex-col gap-space-xs">
          <label class="font-code-sm text-code-sm text-outline" for="intent-select">规则意图类型 (Intent Pattern):</label>
          <select id="intent-select" v-model="filters.intent" class="select" @change="applyFilter({ intent: filters.intent })">
            <option v-for="item in INTENT_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="flex flex-col gap-space-xs">
          <label class="font-code-sm text-code-sm text-outline" for="sort-select">排序基准 (Stable Sort):</label>
          <select id="sort-select" v-model="filters.sort" class="select" @change="applyFilter({ sort: filters.sort })">
            <option v-for="item in SORT_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
      </div>
    </section>

    <!-- AT-TABLE -->
    <SectionCard data-region="AT-TABLE" :padded="false">
      <div class="flex flex-wrap items-center justify-between gap-space-sm px-space-lg py-space-md">
        <div class="flex items-center gap-space-sm">
          <span class="font-code-sm text-code-sm text-on-surface-variant">筛选结果：<span class="text-on-surface">{{ total }}</span> 个实</span>
          <span class="text-outline">·</span>
          <span class="font-code-sm text-code-sm text-outline">{{ activeMatchText }}</span>
        </div>
        <span class="flex items-center gap-1 font-code-sm text-code-sm text-secondary">
          <span class="relative flex h-2 w-2">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-secondary opacity-70" />
            <span class="relative inline-flex h-2 w-2 rounded-full bg-secondary" />
          </span>
          监听活跃中
        </span>
      </div>

      <div v-if="items.length === 0 && !loading" class="border-t border-surface-container-high">
        <EmptyState title="没有匹配的攻击者" hint="当前筛选条件下无结果，可清除筛选后查看全部攻击源。">
          <button type="button" class="btn-primary mt-space-sm" @click="clearFilters">清除筛选条件</button>
        </EmptyState>
      </div>

      <div v-else class="overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>来源地址 (IP ADDRESS)</th>
              <th>首次出现时间</th>
              <th>最近出现时间</th>
              <th>主要意图标签 (RULE CODE)</th>
              <th class="text-right">会话 / 查询计数</th>
              <th>综合风险分</th>
              <th>等级</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.source_ip">
              <td>
                <div class="flex flex-col gap-0.5">
                  <span class="mono text-on-surface">{{ item.source_ip }}</span>
                  <span class="font-code-sm text-code-sm text-outline" :title="item.network_scope ?? ''">{{ item.network_scope_label ?? item.network_scope ?? '—' }}</span>
                </div>
              </td>
              <td class="mono text-code-sm">{{ formatDateTime(item.first_seen) }}</td>
              <td class="mono text-code-sm">{{ formatDateTime(item.last_seen) }}</td>
              <td>
                <div class="flex flex-wrap items-center gap-1">
                  <IntentTag
                    v-if="item.main_intent"
                    :intent="item.main_intent.intent_type"
                    :label="`${intentMeta(item.main_intent.intent_type).short} ${intentMeta(item.main_intent.intent_type).rule}`"
                    :show-rule="false"
                  />
                  <span
                    v-for="code in extraRuleCodes(item)"
                    :key="`${item.source_ip}-${code}`"
                    class="rounded border border-outline-variant/60 bg-surface-container-high px-1.5 py-0.5 font-mono text-code-xs text-on-surface-variant"
                  >{{ code }}</span>
                  <span v-if="!item.main_intent && extraRuleCodes(item).length === 0" class="font-code-sm text-code-sm text-outline">—</span>
                </div>
              </td>
              <td class="text-right">
                <div class="mono text-on-surface">{{ item.total_connections }} 会话</div>
                <div class="font-code-sm text-code-sm text-outline">{{ formatNumber(item.total_queries) }} 次查询</div>
              </td>
              <td class="min-w-38">
                <RiskBar :value="item.risk_score" :level="item.risk_level" />
              </td>
              <td><RiskBadge :level="item.risk_level" size="small" /></td>
              <td class="text-right">
                <router-link :to="`/attackers/${item.source_ip}`" class="btn-secondary">
                  画像详情
                  <span class="material-symbols-outlined text-icon-xs" aria-hidden="true">open_in_new</span>
                </router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div data-region="AT-PAGER" class="px-space-lg pb-space-md">
        <PaginationBar
          :page="filters.page"
          :page-size="filters.page_size"
          :total="total"
          :total-pages="totalPages"
          :loading="loading"
          @update:page="changePage"
        />
      </div>
    </SectionCard>
  </div>
</template>
