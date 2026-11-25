<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import IntentDonut, { type DonutSlice } from '../components/IntentDonut.vue'
import IntentTag from '../components/IntentTag.vue'
import KpiCard from '../components/KpiCard.vue'
import PageHeader from '../components/PageHeader.vue'
import RiskBadge from '../components/RiskBadge.vue'
import RiskBar from '../components/RiskBar.vue'
import SectionCard from '../components/SectionCard.vue'
import TrendChart from '../components/TrendChart.vue'
import { honeypotApi, errorMessage } from '../api'
import { useRefreshBus } from '../composables/refresh'
import { formatDate, formatNumber, formatPctValue, formatPercent, formatRelative } from '../utils/format'
import type { AttackerSummary, OverviewResponse, RangeKey, RuleEffectivenessItem, TrendItem } from '../types'

const route = useRoute()
const router = useRouter()
const bus = useRefreshBus()

const loading = ref(true)
const error = ref<string | null>(null)
const overview = ref<OverviewResponse | null>(null)
const trend = ref<TrendItem[]>([])
const rules = ref<RuleEffectivenessItem[]>([])
const topAttackers = ref<AttackerSummary[]>([])

const RANGES: Array<{ key: RangeKey; label: string }> = [
  { key: '24h', label: '今日 24H' },
  { key: '7d', label: '最近 7 天' },
  { key: 'all', label: '全部历史' }
]

const range = computed<RangeKey>(() => {
  const value = String(route.query.range ?? 'all')
  return value === '24h' || value === '7d' ? value : 'all'
})

function setRange(next: RangeKey): void {
  if (next === range.value) return
  void router.replace({ query: { ...route.query, range: next } })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  bus.refreshing.value = true
  try {
    const [overviewData, trendData, ruleData, attackerData] = await Promise.all([
      honeypotApi.getOverview(range.value),
      honeypotApi.getTrend(range.value === '24h' ? 2 : range.value === '7d' ? 7 : 30),
      honeypotApi.getRuleEffectiveness(20),
      honeypotApi.getAttackers({ page: 1, page_size: 5, sort: 'risk_score', order: 'desc' })
    ])
    overview.value = overviewData
    trend.value = trendData.items
    rules.value = ruleData.items
    topAttackers.value = attackerData.items
    bus.markUpdated()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
    bus.refreshing.value = false
  }
}

const rangeText = computed(() => {
  const item = RANGES.find((entry) => entry.key === range.value)
  return item?.label ?? '全部历史'
})

const trendSubtitle = computed(() => {
  const span = range.value === '24h' ? '最近 2 天' : range.value === '7d' ? '最近 7 天' : '最近 30 天'
  if (trend.value.length === 0) return `${span}全协议交互与行为意图演变`
  return `${span}全协议交互与行为意图演变 (${formatDate(trend.value[0]?.stat_date)} ~ ${formatDate(trend.value[trend.value.length - 1]?.stat_date)})`
})

const trendPeakNote = computed(() => {
  let peak = { date: '', value: 0 }
  trend.value.forEach((item) => {
    const value = (item.hit_bruteforce ?? 0) + (item.hit_data_dump ?? 0) + (item.hit_scanning ?? 0) + (item.hit_recon ?? 0)
    if (value > peak.value) peak = { date: item.stat_date, value }
  })
  if (peak.value === 0) return '窗口内暂无规则命中'
  return `峰值采样：${formatDate(peak.date)} · 当日命中 ${formatNumber(peak.value)} 次（7 日意图族合计）`
})

const donutSlices = computed<DonutSlice[]>(() => {
  // 图表配色全部走主题变量（深/浅两套在 main.css 定义），页面内不写裸色值。
  const colorByRule: Record<string, string> = {
    R01: 'var(--chart-4)',
    R02: 'var(--chart-5)',
    R03: 'var(--chart-2)',
    R04: 'var(--chart-1)',
    R05: 'var(--chart-3)'
  }
  return rules.value
    .filter((rule) => rule.hit_count > 0)
    .map((rule) => ({
      key: rule.rule_code,
      label: intentLabelOf(rule.rule_code),
      value: rule.hit_count,
      color: colorByRule[rule.rule_code] ?? 'var(--chart-1)'
    }))
})

function intentLabelOf(code: string): string {
  switch (code) {
    case 'R01':
      return '端口探测'
    case 'R02':
      return '认证爆破'
    case 'R03':
      return '敏感侦查'
    case 'R04':
      return '批量拖库'
    case 'R05':
      return '破坏性操作'
    default:
      return code
  }
}

const donutTotal = computed(() => rules.value.reduce((sum, rule) => sum + rule.hit_count, 0))
const trendLegend = [
  { key: 'bruteforce', label: '爆破 (R02)', color: 'var(--chart-1)' },
  { key: 'data_dump', label: '拖库/查询 (R04)', color: 'var(--chart-2)' },
  { key: 'scanning', label: '踩点扫描 (R01/03)', color: 'var(--chart-3)' }
]

const donutCenterValue = computed(() => formatNumber(donutTotal.value))
const donutCenterLabel = computed(() => `${rules.value.filter((rule) => rule.hit_count > 0).length} 类规则`)

const unreadLine = computed(() => {
  const bySeverity = overview.value?.alerts_by_severity
  if (!bySeverity) return '严重 — · 高危 —'
  return `严重 ${bySeverity.critical ?? 0} · 高危 ${bySeverity.high ?? 0}`
})

const blockedRate = computed(() => {
  const value = overview.value?.query_blocked_rate
  return value === null || value === undefined ? '—' : formatPercent(value)
})

const highRiskRatio = computed(() => {
  const value = overview.value?.high_risk_ratio
  return value === null || value === undefined ? null : Math.round(value * 1000) / 10
})

watch(
  () => range.value,
  () => void load()
)
watch(() => bus.tick.value, () => void load())
onMounted(() => void load())
</script>

<template>
  <div class="flex flex-col gap-space-lg">
    <div data-region="OV-HEAD">
    <PageHeader title="首页概览" subtitle="DASHBOARD" badge="演示库就绪: SEED RULES ACTIVE, LIVE TRAP ONLINE">
      <template #actions>
        <div class="flex items-center gap-0.5 rounded bg-surface-container-low p-0.5 shadow-sm">
          <button
            v-for="item in RANGES"
            :key="item.key"
            type="button"
            class="rounded px-space-md py-1 font-body-sm text-body-sm transition-all"
            :class="range === item.key ? 'bg-primary-container font-semibold text-on-primary-container shadow-sm' : 'font-normal text-on-surface-variant hover:text-on-surface'"
            :aria-pressed="range === item.key"
            @click="setRange(item.key)"
          >
            {{ item.label }}
          </button>
        </div>
      </template>
    </PageHeader>
    </div>

    <div v-if="error" class="rounded-lg border border-sev-critical/40 bg-sev-critical/10 px-space-lg py-space-md text-body-sm text-sev-critical" role="alert">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="load">重试</button>
    </div>

    <template v-if="overview">
      <!-- 四张 KPI 指标卡（OV-KPI） -->
      <div data-region="OV-KPI" class="grid grid-cols-1 gap-gutter sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="连接数 · SESSIONS"
          :value="formatNumber(overview.sessions)"
          icon="hub"
          tone="primary"
          to="/attackers"
          :delta-text="overview.sessions_delta_pct === null || overview.sessions_delta_pct === undefined ? '' : formatPctValue(overview.sessions_delta_pct)"
          delta-tone="up"
          :note="`今日新增 +${formatNumber(overview.sessions_today ?? 0)} 会话`"
          source="sessions"
        />
        <KpiCard
          label="查询数 · QUERIES"
          :value="formatNumber(overview.queries)"
          icon="terminal"
          tone="primary"
          to="/attackers"
          :delta-text="`${blockedRate} 拦截`"
          delta-tone="down"
          :note="`今日执行 +${formatNumber(overview.queries_today ?? 0)} 次`"
          source="attack_log"
        />
        <KpiCard
          label="未处理告警 · ALERTS"
          :value="formatNumber(overview.alerts_unread ?? overview.alerts)"
          icon="warning"
          tone="error"
          to="/alerts?is_read=false"
          delta-text="需立即复核"
          delta-tone="error"
          :note="unreadLine"
          source="alerts 未读"
        />
        <KpiCard
          label="高风险攻击者 · RISK >= 60"
          :value="formatNumber(overview.high_risk_attackers)"
          icon="security"
          tone="tertiary"
          to="/attackers?risk_level=high"
          :delta-text="`/ ${formatNumber(overview.attackers_total ?? 0)} 总量`"
          delta-tone="muted"
          :note="highRiskRatio === null ? '占比 —' : `占比 ${highRiskRatio}% (阈值超标)`"
          source="v_attacker_profile"
          :progress="highRiskRatio"
        />
      </div>

      <!-- 趋势 + 环图 -->
      <div class="grid grid-cols-1 gap-gutter lg:grid-cols-12">
        <SectionCard data-region="OV-TREND" class="lg:col-span-7" title="每日攻击趋势" :subtitle="trendSubtitle" :loading="loading">
          <template #actions>
            <div class="flex flex-wrap items-center gap-space-md" aria-label="趋势图例">
              <span v-for="item in trendLegend" :key="item.key" class="flex items-center gap-1 font-code-sm text-code-sm text-on-surface">
                <span class="h-2 w-3 rounded-sm" :style="{ background: item.color }" aria-hidden="true" />
                <span>{{ item.label }}</span>
              </span>
            </div>
          </template>
          <TrendChart v-if="trend.length > 0" :items="trend" :height="240" :show-legend="false" />
          <p v-else class="py-space-lg text-center text-body-sm text-on-surface-variant">窗口内暂无趋势数据</p>
          <p class="mt-space-sm font-code-sm text-code-sm text-outline">{{ trendPeakNote }}</p>
        </SectionCard>
        <SectionCard data-region="OV-DONUT" class="lg:col-span-5" title="规则命中与意图分布" subtitle="攻击意图分析引擎命中量汇总" :loading="loading">
          <template #actions>
            <span class="font-code-sm text-code-sm text-outline">{{ formatNumber(donutTotal) }} 次命中</span>
          </template>
          <IntentDonut :slices="donutSlices" :center-value="donutCenterValue" :center-label="donutCenterLabel" />
        </SectionCard>
      </div>

      <!-- 高风险 TOP5 -->
      <SectionCard data-region="OV-TOP5" :padded="false" title="高风险攻击者实时榜单 TOP 5" subtitle="基于会话深度、提权意图与高危指令聚合评分 (v_attacker_profile_summary)">
        <template #actions>
          <router-link to="/attackers" class="btn-secondary">
            进入攻击者列表 (全部 {{ overview.attackers_total ?? 0 }} 位)
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">arrow_forward</span>
          </router-link>
        </template>
        <div class="overflow-x-auto px-space-lg pb-space-lg">
          <table class="tbl">
            <thead>
              <tr>
                <th class="w-10">排名</th>
                <th>攻击源 IP（来源）</th>
                <th>风险评分 (RISK SCORE)</th>
                <th>识别意图标签</th>
                <th>累计会话</th>
                <th>最后活跃时间</th>
                <th class="text-right">处置与下钻</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(attacker, index) in topAttackers" :key="attacker.source_ip">
                <td class="mono text-outline">{{ String(index + 1).padStart(2, '0') }}</td>
                <td>
                  <div class="flex flex-col">
                    <span class="mono text-on-surface">{{ attacker.source_ip }}</span>
                    <span class="text-code-sm text-outline">{{ attacker.network_scope_label ?? '—' }} / {{ attacker.intent_labels?.[0] ?? '未分类' }}</span>
                  </div>
                </td>
                <td class="min-w-38">
                  <RiskBar :value="attacker.risk_score" :level="attacker.risk_level" />
                </td>
                <td>
                  <div class="flex flex-wrap gap-1">
                    <IntentTag v-for="code in attacker.triggered_rule_codes ?? []" :key="code" :intent="null" :label="code" />
                  </div>
                </td>
                <td class="mono text-on-surface">{{ attacker.total_connections }} 次</td>
                <td class="mono text-code-sm">{{ formatRelative(attacker.last_seen) }}</td>
                <td class="text-right">
                  <router-link :to="`/attackers/${attacker.source_ip}`" class="btn-secondary">
                    画像详情
                    <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">open_in_new</span>
                  </router-link>
                </td>
              </tr>
              <tr v-if="topAttackers.length === 0">
                <td colspan="7" class="py-space-lg text-center text-on-surface-variant">当前窗口内暂无攻击者数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </template>

    <div v-else-if="loading" class="flex min-h-72 items-center justify-center gap-2 font-code-sm text-code-sm text-outline" role="status">
      <span class="material-symbols-outlined animate-spin text-icon-lg" aria-hidden="true">progress_activity</span>正在加载概览数据…
    </div>
  </div>
</template>
