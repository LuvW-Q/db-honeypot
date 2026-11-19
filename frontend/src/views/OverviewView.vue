<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import StatCard from '../components/StatCard.vue'
import TrendChart from '../components/TrendChart.vue'
import { errorMessage, honeypotApi } from '../api'
import { formatDateTime, formatNumber, intentLabel } from '../utils/format'
import type {
  HealthResponse,
  OverviewResponse,
  RuleEffectivenessResponse,
  TrendResponse
} from '../types'

interface StatCardData {
  title: string
  value: number | null
  hint: string
  tone: 'primary' | 'success' | 'warning' | 'danger'
}

const overview = ref<OverviewResponse | null>(null)
const trend = ref<TrendResponse | null>(null)
const rules = ref<RuleEffectivenessResponse | null>(null)
const health = ref<HealthResponse | null>(null)
const healthUnavailable = ref(false)
const errorText = ref('')

const loading = reactive({
  overview: false,
  trend: false,
  rules: false
})

const refreshing = computed(() => loading.overview || loading.trend || loading.rules)

const stats = computed<StatCardData[]>(() => [
  {
    title: '会话总数',
    value: overview.value?.sessions ?? null,
    hint: 'v_session_risk_summary 行数',
    tone: 'primary'
  },
  {
    title: '查询总数',
    value: overview.value?.queries ?? null,
    hint: '仅统计 event_type=query',
    tone: 'success'
  },
  {
    title: '告警总数',
    value: overview.value?.alerts ?? null,
    hint: '与 alerts 表计数一致',
    tone: 'warning'
  },
  {
    title: '高风险攻击者',
    value: overview.value?.high_risk_attackers ?? null,
    hint: '风险等级 high / critical 的来源数',
    tone: 'danger'
  }
])

const databaseDown = computed(
  () => health.value !== null && health.value.database?.status !== 'ok'
)

const honeypotStatus = computed(() => health.value?.honeypot?.status ?? null)

const healthRequestId = computed(() => health.value?.request_id ?? '')

async function loadOverview(): Promise<void> {
  loading.overview = true
  try {
    overview.value = await honeypotApi.getOverview()
  } catch (error) {
    errorText.value = errorMessage(error)
    ElMessage.error(errorText.value)
  } finally {
    loading.overview = false
  }
}

async function loadTrend(): Promise<void> {
  loading.trend = true
  try {
    trend.value = await honeypotApi.getTrend(14)
  } catch (error) {
    errorText.value = errorMessage(error)
    ElMessage.error(errorText.value)
  } finally {
    loading.trend = false
  }
}

async function loadRules(): Promise<void> {
  loading.rules = true
  try {
    rules.value = await honeypotApi.getRuleEffectiveness(50)
  } catch (error) {
    errorText.value = errorMessage(error)
    ElMessage.error(errorText.value)
  } finally {
    loading.rules = false
  }
}

async function loadHealth(): Promise<void> {
  const result = await honeypotApi.getHealth()
  health.value = result
  healthUnavailable.value = result === null
}

async function refreshAll(): Promise<void> {
  errorText.value = ''
  await Promise.allSettled([loadOverview(), loadTrend(), loadRules(), loadHealth()])
}

onMounted(() => {
  void refreshAll()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-header__title">概览</h2>
        <p class="page-header__desc">
          连接数、查询数、告警数与高风险攻击者数均来自核心分析视图，与数据库视图查询结果一致。
        </p>
      </div>
      <div class="page-header__actions">
        <span v-if="overview" class="generated-at">
          数据生成于 {{ formatDateTime(overview.generated_at) }}
        </span>
        <el-button :loading="refreshing" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="healthUnavailable"
      type="error"
      :closable="false"
      show-icon
      title="健康检查不可达"
      description="无法连接 /api/health，请确认后端服务已启动；页面其余数据仍按接口返回情况展示。"
    />

    <el-alert
      v-if="databaseDown"
      type="error"
      :closable="false"
      show-icon
      title="数据库不可用，数据可能不完整"
      :description="`请稍后重试或检查数据库连接。${healthRequestId ? `请求编号：${healthRequestId}` : ''}`"
    />

    <el-alert
      v-if="honeypotStatus === 'down'"
      type="warning"
      :closable="false"
      show-icon
      title="诱饵服务不可用（降级运行）"
      description="诱饵监听未就绪，捕获能力下降；分析视图与告警仍可查看。"
    />

    <el-alert
      v-else-if="honeypotStatus === 'disabled'"
      type="info"
      :closable="false"
      show-icon
      title="诱饵服务已禁用（降级为真实 MySQL 方案）"
      description="当前使用降级方案，事件采集口径与诱饵模式不同。"
    />

    <el-alert v-if="errorText" type="error" :closable="false" show-icon :title="errorText" />

    <div class="stat-grid">
      <StatCard
        v-for="card in stats"
        :key="card.title"
        :title="card.title"
        :value="card.value"
        :hint="card.hint"
        :tone="card.tone"
        :loading="loading.overview"
      />
    </div>

    <div class="overview-grid">
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-title">
            <span>每日攻击趋势（近 14 天）</span>
            <span class="section-title__hint">来源视图 v_daily_attack_trend</span>
          </div>
        </template>
        <TrendChart
          :items="trend?.items ?? []"
          :loading="loading.trend"
          :days="trend?.days ?? 14"
        />
      </el-card>

      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-title">
            <span>规则效果</span>
            <span class="section-title__hint">来源视图 v_rule_effectiveness</span>
          </div>
        </template>
        <el-table
          v-loading="loading.rules"
          :data="rules?.items ?? []"
          row-key="rule_code"
          size="small"
          border
          max-height="360"
        >
          <el-table-column prop="rule_code" label="规则" width="72" />
          <el-table-column label="名称 / 意图" min-width="150">
            <template #default="{ row }">
              <div>{{ row.rule_name }}</div>
              <div class="rule-meta">
                {{ intentLabel(row.intent_type) }} · 权重 {{ row.risk_weight }} ·
                {{ row.is_enabled ? '启用' : '已停用' }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="命中" width="72" align="right">
            <template #default="{ row }">{{ formatNumber(row.hit_count) }}</template>
          </el-table-column>
          <el-table-column label="来源" width="72" align="right">
            <template #default="{ row }">{{ formatNumber(row.affected_attacker_count) }}</template>
          </el-table-column>
          <el-table-column label="告警" width="72" align="right">
            <template #default="{ row }">
              {{ formatNumber(row.alert_count) }}
              <div v-if="row.unread_alert_count" class="rule-meta">
                未读 {{ row.unread_alert_count }}
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无规则效果数据" :image-size="60" />
          </template>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.generated-at {
  color: #909399;
  font-size: 12px;
}

.rule-meta {
  color: #909399;
  font-size: 12px;
}
</style>
