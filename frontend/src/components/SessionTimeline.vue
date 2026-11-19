<script setup lang="ts">
import {
  alertTypeLabel,
  eventStatusLabel,
  eventTypeLabel,
  formatDateTime,
  sessionStatusLabel,
  severityLabel
} from '../utils/format'
import type { SessionTimelineResponse } from '../types'
import RiskBadge from './RiskBadge.vue'

interface Props {
  data: SessionTimelineResponse | null
  loading?: boolean
}

withDefaults(defineProps<Props>(), { loading: false })

function eventTimelineType(status: string): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  switch (status) {
    case 'success':
      return 'success'
    case 'failure':
    case 'error':
      return 'danger'
    case 'denied':
      return 'warning'
    default:
      return 'primary'
  }
}

function statusTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  switch (status) {
    case 'success':
      return 'success'
    case 'failure':
    case 'error':
      return 'danger'
    case 'denied':
      return 'warning'
    default:
      return 'info'
  }
}

function severityTagType(severity: string): 'success' | 'warning' | 'danger' | 'info' {
  switch (severity) {
    case 'low':
      return 'info'
    case 'medium':
      return 'warning'
    case 'high':
    case 'critical':
      return 'danger'
    default:
      return 'info'
  }
}
</script>

<template>
  <div class="session-timeline">
    <el-skeleton v-if="loading" animated :rows="10" />

    <el-empty v-else-if="!data" description="请选择会话查看时间线" :image-size="80" />

    <template v-else>
      <el-descriptions class="session-timeline__head" :column="2" border size="small">
        <el-descriptions-item label="会话编号" :span="2">
          <span class="mono">{{ data.session.session_id }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="来源地址">
          <span class="mono">
            {{ data.session.source_ip }}:{{ data.session.source_port }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="目标服务">
          {{ data.session.target_service }}
        </el-descriptions-item>
        <el-descriptions-item label="会话状态">
          <el-tag
            size="small"
            :type="data.session.session_status === 'active' ? 'success' : 'info'"
            effect="plain"
          >
            {{ sessionStatusLabel(data.session.session_status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="风险等级">
          <RiskBadge
            :level="data.session.risk_level"
            :score="data.session.calculated_risk_score"
            size="small"
          />
        </el-descriptions-item>
        <el-descriptions-item label="开始时间">
          {{ formatDateTime(data.session.started_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="结束时间">
          {{ formatDateTime(data.session.ended_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="事件 / 查询数">
          {{ data.session.event_count }} / {{ data.session.query_count }}
        </el-descriptions-item>
        <el-descriptions-item label="告警数">
          {{ data.session.alert_count }}
        </el-descriptions-item>
        <el-descriptions-item label="客户端特征" :span="2">
          {{ data.session.client_fingerprint || '—' }}
        </el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="data.events_truncated"
        class="session-timeline__alert"
        type="warning"
        :closable="false"
        show-icon
        title="事件数量超过单会话返回上限，仅展示前 1000 条"
      />

      <section class="session-timeline__section">
        <h4 class="session-timeline__title">事件时间线（{{ data.events.length }} 条）</h4>
        <el-empty v-if="data.events.length === 0" description="该会话暂无事件" :image-size="60" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="event in data.events"
            :key="event.event_id"
            :timestamp="formatDateTime(event.event_time)"
            placement="top"
            :type="eventTimelineType(event.status)"
          >
            <div class="event-card">
              <div class="event-card__head">
                <el-tag size="small" effect="plain">{{ eventTypeLabel(event.event_type) }}</el-tag>
                <el-tag size="small" :type="statusTagType(event.status)">
                  {{ eventStatusLabel(event.status) }}
                </el-tag>
                <span class="event-card__meta mono">#{{ event.event_id }}</span>
                <span class="event-card__meta">{{ event.response_ms }} ms</span>
              </div>

              <div v-if="event.username" class="event-card__row">
                <span class="event-card__label">用户名：</span>
                <span class="mono">{{ event.username }}</span>
              </div>

              <div
                v-if="event.credential_masked !== null || event.credential_test_id"
                class="event-card__row"
              >
                <span class="event-card__label">凭据：</span>
                <span class="mono">{{ event.credential_masked ?? '****' }}</span>
                <span v-if="event.credential_test_id" class="event-card__meta">
                  （测试标识 {{ event.credential_test_id }}）
                </span>
              </div>

              <div v-if="event.statement_type" class="event-card__row">
                <span class="event-card__label">语句类型：</span>
                <span class="mono">{{ event.statement_type }}</span>
                <span v-if="event.returned_rows > 0" class="event-card__meta">
                  返回 {{ event.returned_rows }} 行
                </span>
              </div>

              <pre v-if="event.sql_statement" class="event-card__sql">{{
                event.sql_statement
              }}</pre>

              <div v-if="event.payload_truncated" class="event-card__meta">内容已按上限截断</div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </section>

      <section class="session-timeline__section">
        <h4 class="session-timeline__title">规则命中（{{ data.rule_hits.length }} 条）</h4>
        <el-empty
          v-if="data.rule_hits.length === 0"
          description="该会话暂无规则命中"
          :image-size="60"
        />
        <el-table v-else :data="data.rule_hits" row-key="hit_id" size="small" border>
          <el-table-column prop="rule_code" label="规则" width="90" />
          <el-table-column prop="rule_name" label="规则名称" min-width="140" />
          <el-table-column label="命中时间" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.triggered_at) }}</template>
          </el-table-column>
          <el-table-column prop="risk_weight" label="权重" width="80" align="right" />
          <el-table-column prop="evidence_summary" label="证据摘要" min-width="260" />
        </el-table>
      </section>

      <section class="session-timeline__section">
        <h4 class="session-timeline__title">关联告警（{{ data.alerts.length }} 条）</h4>
        <el-empty v-if="data.alerts.length === 0" description="该会话暂无告警" :image-size="60" />
        <el-table v-else :data="data.alerts" row-key="alert_id" size="small" border>
          <el-table-column label="等级" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="severityTagType(row.severity)" size="small">
                {{ severityLabel(row.severity) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="105">
            <template #default="{ row }">{{ alertTypeLabel(row.alert_type) }}</template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="180" />
          <el-table-column prop="occurrence_count" label="次数" width="80" align="right" />
          <el-table-column label="创建时间" min-width="165">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">{{ row.is_read ? '已读' : '未读' }}</template>
          </el-table-column>
        </el-table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.session-timeline__head {
  margin-bottom: 16px;
}

.session-timeline__alert {
  margin-bottom: 16px;
}

.session-timeline__section + .session-timeline__section {
  margin-top: 20px;
}

.session-timeline__title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
}

.event-card {
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fafbfc;
}

.event-card__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.event-card__row {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
  word-break: break-all;
}

.event-card__label {
  color: #909399;
}

.event-card__meta {
  color: #909399;
  font-size: 12px;
}

.event-card__sql {
  margin: 8px 0 0;
  padding: 8px 10px;
  background: #fff;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
