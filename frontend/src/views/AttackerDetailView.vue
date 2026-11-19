<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import IntentTag from '../components/IntentTag.vue'
import RiskBadge from '../components/RiskBadge.vue'
import SessionTimeline from '../components/SessionTimeline.vue'
import { ApiError, errorMessage, honeypotApi } from '../api'
import {
  formatDateTime,
  formatNumber,
  sessionStatusLabel,
  sessionStatusTagType,
  splitCodes
} from '../utils/format'
import type {
  AttackerDetailResponse,
  SessionSummary,
  SessionTimelineResponse
} from '../types'

const route = useRoute()
const router = useRouter()

const ip = computed(() => decodeURIComponent(String(route.params.ip ?? '')))

const detail = ref<AttackerDetailResponse | null>(null)
const loading = ref(false)
const loadError = ref('')
const notFound = ref(false)

const drawerVisible = ref(false)
const activeSessionId = ref('')
const timeline = ref<SessionTimelineResponse | null>(null)
const timelineLoading = ref(false)
const timelineError = ref('')

const intentTypes = computed(() => splitCodes(detail.value?.attacker.intent_labels ?? null))

const triggeredRules = computed(() =>
  splitCodes(detail.value?.attacker.triggered_rule_codes ?? null)
)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  notFound.value = false
  try {
    detail.value = await honeypotApi.getAttackerDetail(ip.value, {
      session_limit: 50,
      hit_limit: 20
    })
  } catch (error) {
    detail.value = null
    if (error instanceof ApiError && error.code === 'ATTACKER_NOT_FOUND') {
      notFound.value = true
    } else if (error instanceof ApiError && error.code === 'IP_FORMAT_INVALID') {
      notFound.value = true
      ElMessage.error('来源地址格式不合法，无法查询画像')
    } else {
      loadError.value = errorMessage(error)
      ElMessage.error(loadError.value)
    }
  } finally {
    loading.value = false
  }
}

async function loadTimeline(sessionId: string): Promise<void> {
  timeline.value = null
  timelineError.value = ''
  timelineLoading.value = true
  try {
    timeline.value = await honeypotApi.getSessionTimeline(sessionId)
  } catch (error) {
    if (error instanceof ApiError && error.code === 'SESSION_NOT_FOUND') {
      timelineError.value = '会话不存在，可能已被清理'
    } else {
      timelineError.value = errorMessage(error)
    }
    ElMessage.error(timelineError.value)
  } finally {
    timelineLoading.value = false
  }
}

function openTimeline(session: SessionSummary): void {
  drawerVisible.value = true
  activeSessionId.value = session.session_id
  void loadTimeline(session.session_id)
}

function retryTimeline(): void {
  if (!activeSessionId.value) return
  void loadTimeline(activeSessionId.value)
}

function goBack(): void {
  void router.push({ name: 'attackers' })
}

watch(ip, () => {
  void load()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link type="primary" class="back-link" @click="goBack">
          ← 返回攻击者列表
        </el-button>
        <h2 class="page-header__title">攻击者详情</h2>
        <p class="page-header__desc">
          来源地址 <span class="mono">{{ ip }}</span
          >：画像统计、意图识别、会话摘要与最近规则证据。
        </p>
      </div>
      <div class="page-header__actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" type="error" :closable="false" show-icon :title="loadError">
      <template #default>
        <el-button link type="primary" @click="load">重试</el-button>
      </template>
    </el-alert>

    <el-result
      v-if="notFound"
      icon="warning"
      title="暂无该来源画像"
      :sub-title="`来源 ${ip} 尚无画像记录，或地址不在攻击者视图中。`"
    >
      <template #extra>
        <el-button type="primary" @click="goBack">返回攻击者列表</el-button>
      </template>
    </el-result>

    <template v-else-if="detail">
      <el-card v-loading="loading" shadow="never" class="section-card">
        <template #header>
          <div class="profile-header">
            <div class="profile-header__main">
              <span class="profile-header__ip mono">{{ detail.attacker.source_ip }}</span>
              <el-tag
                v-for="code in triggeredRules"
                :key="code"
                size="small"
                effect="plain"
                type="info"
                >{{ code }}</el-tag
              >
            </div>
            <RiskBadge
              :level="detail.attacker.risk_level"
              :score="detail.attacker.risk_score"
              size="large"
            />
          </div>
        </template>

        <div class="intent-labels">
          <span class="intent-labels__label">意图标签：</span>
          <template v-if="intentTypes.length > 0">
            <IntentTag
              v-for="intentType in intentTypes"
              :key="intentType"
              :intent-type="intentType"
              size="small"
            />
          </template>
          <span v-else class="intent-labels__empty">暂无意图命中</span>
        </div>

        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="首次出现">
            {{ formatDateTime(detail.attacker.first_seen) }}
          </el-descriptions-item>
          <el-descriptions-item label="最近出现">
            {{ formatDateTime(detail.attacker.last_seen) }}
          </el-descriptions-item>
          <el-descriptions-item label="风险等级">
            <RiskBadge
              :level="detail.attacker.risk_level"
              :score="detail.attacker.risk_score"
              size="small"
            />
          </el-descriptions-item>
          <el-descriptions-item label="连接数">
            {{ formatNumber(detail.attacker.total_connections) }}
          </el-descriptions-item>
          <el-descriptions-item label="认证尝试">
            {{ formatNumber(detail.attacker.total_auth_attempts) }}
          </el-descriptions-item>
          <el-descriptions-item label="认证失败">
            {{ formatNumber(detail.attacker.total_auth_failures) }}
          </el-descriptions-item>
          <el-descriptions-item label="查询数">
            {{ formatNumber(detail.attacker.total_queries) }}
          </el-descriptions-item>
          <el-descriptions-item label="会话数">
            {{ formatNumber(detail.attacker.session_count) }}
          </el-descriptions-item>
          <el-descriptions-item label="高风险会话">
            {{ formatNumber(detail.attacker.high_risk_session_count) }}
          </el-descriptions-item>
          <el-descriptions-item label="告警数">
            {{ formatNumber(detail.attacker.alert_count) }}
          </el-descriptions-item>
          <el-descriptions-item label="未读告警">
            {{ formatNumber(detail.attacker.unread_alert_count) }}
          </el-descriptions-item>
          <el-descriptions-item label="重算风险分">
            {{ formatNumber(detail.attacker.calculated_risk_score) }}
          </el-descriptions-item>
          <el-descriptions-item label="证据摘要" :span="3">
            {{ detail.attacker.evidence_summary || '暂无证据摘要' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-alert
        v-if="detail.attacker.risk_score !== detail.attacker.calculated_risk_score"
        type="warning"
        :closable="false"
        show-icon
        title="存储风险分与视图重算分不一致"
        :description="`存储值 ${detail.attacker.risk_score}，重算值 ${detail.attacker.calculated_risk_score}，可能存在数据漂移，请核对分析流水线。`"
      />

      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-title">
            <span>意图识别（{{ detail.intents.length }} 条）</span>
            <span class="section-title__hint">按可信分、最近识别时间排序</span>
          </div>
        </template>
        <el-table :data="detail.intents" row-key="intent_type" size="small" border>
          <el-table-column label="意图" width="140">
            <template #default="{ row }">
              <IntentTag :intent-type="row.intent_type" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="可信分" min-width="180">
            <template #default="{ row }">
              <el-progress :percentage="row.intent_score" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column prop="evidence_count" label="证据数" width="90" align="right" />
          <el-table-column label="首次识别" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.first_detected_at) }}</template>
          </el-table-column>
          <el-table-column label="最近识别" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.last_detected_at) }}</template>
          </el-table-column>
          <template #empty>
            <el-empty description="该来源暂无意图命中" :image-size="60" />
          </template>
        </el-table>
      </el-card>

      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-title">
            <span>会话摘要（{{ detail.sessions.length }} 条）</span>
            <span class="section-title__hint">点击任意行查看会话时间线</span>
          </div>
        </template>
        <el-table
          :data="detail.sessions"
          row-key="session_id"
          size="small"
          border
          row-class-name="clickable-row"
          @row-click="openTimeline"
        >
          <el-table-column label="会话编号" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.session_id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="开始时间" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
          </el-table-column>
          <el-table-column label="结束时间" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.ended_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="sessionStatusTagType(row.session_status)" size="small" effect="plain">
                {{ sessionStatusLabel(row.session_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="事件/查询" width="100" align="center">
            <template #default="{ row }">{{ row.event_count }} / {{ row.query_count }}</template>
          </el-table-column>
          <el-table-column label="风险" width="130" align="center">
            <template #default="{ row }">
              <RiskBadge :level="row.risk_level" :score="row.risk_score" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="命中规则" min-width="110">
            <template #default="{ row }">{{ row.hit_rule_codes || '—' }}</template>
          </el-table-column>
          <el-table-column label="告警" width="70" align="right">
            <template #default="{ row }">{{ row.alert_count }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="center">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click.stop="openTimeline(row)">
                查看时间线
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="该来源暂无会话摘要" :image-size="60" />
          </template>
        </el-table>
      </el-card>

      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-title">
            <span>最近规则证据（{{ detail.recent_rule_hits.length }} 条）</span>
            <span class="section-title__hint">命中时的规则版本与权重快照</span>
          </div>
        </template>
        <el-table :data="detail.recent_rule_hits" row-key="hit_id" size="small" border>
          <el-table-column prop="rule_code" label="规则" width="80" />
          <el-table-column prop="rule_name" label="规则名称" min-width="150" />
          <el-table-column label="意图" width="120">
            <template #default="{ row }">
              <IntentTag :intent-type="row.intent_type" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="命中时间" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.triggered_at) }}</template>
          </el-table-column>
          <el-table-column label="版本/权重" width="105" align="center">
            <template #default="{ row }">v{{ row.rule_version }} / {{ row.risk_weight }}</template>
          </el-table-column>
          <el-table-column prop="evidence_summary" label="证据摘要" min-width="280" />
          <template #empty>
            <el-empty description="暂无规则证据" :image-size="60" />
          </template>
        </el-table>
      </el-card>
    </template>

    <el-card v-else v-loading="loading" shadow="never" class="section-card">
      <el-empty description="暂无数据" :image-size="80" />
    </el-card>

    <el-drawer v-model="drawerVisible" size="62%" :destroy-on-close="true">
      <template #header>
        <div class="drawer-header">
          <span>会话时间线</span>
          <span v-if="activeSessionId" class="drawer-header__id mono">{{ activeSessionId }}</span>
        </div>
      </template>

      <el-alert
        v-if="timelineError"
        class="timeline-error"
        type="error"
        :closable="false"
        show-icon
        :title="timelineError"
      >
        <template #default>
          <el-button v-if="activeSessionId" link type="primary" @click="retryTimeline">
            重新加载
          </el-button>
        </template>
      </el-alert>

      <SessionTimeline :data="timeline" :loading="timelineLoading" />
    </el-drawer>
  </div>
</template>

<style scoped>
.back-link {
  padding: 0;
  margin-bottom: 4px;
}

.profile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.profile-header__main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.profile-header__ip {
  font-size: 18px;
  font-weight: 600;
}

.intent-labels {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.intent-labels__label {
  color: #909399;
  font-size: 13px;
}

.intent-labels__empty {
  color: #c0c4cc;
  font-size: 13px;
}

.drawer-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.drawer-header__id {
  color: #909399;
  font-size: 12px;
}

.timeline-error {
  margin-bottom: 12px;
}
</style>
