<script setup lang="ts">
import { alertTypeLabel, formatDateTime, severityLabel } from '../utils/format'
import type { AlertItem } from '../types'

interface Props {
  items: AlertItem[]
  loading?: boolean
  markingId?: number | null
}

withDefaults(defineProps<Props>(), { loading: false, markingId: null })

const emit = defineEmits<{ (event: 'mark-read', row: AlertItem): void }>()

function severityType(severity: string): 'success' | 'warning' | 'danger' | 'info' {
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

function severityEffect(severity: string): 'light' | 'dark' {
  return severity === 'critical' ? 'dark' : 'light'
}

function alertTypeValue(type: string): 'success' | 'warning' | 'danger' | 'info' {
  switch (type) {
    case 'bruteforce':
      return 'warning'
    case 'data_dump':
      return 'danger'
    case 'destructive':
      return 'danger'
    default:
      return 'info'
  }
}

function markRead(row: AlertItem): void {
  emit('mark-read', row)
}
</script>

<template>
  <el-table
    v-loading="loading"
    :data="items"
    row-key="alert_id"
    stripe
    border
    style="width: 100%"
  >
    <el-table-column label="等级" width="80" align="center" fixed>
      <template #default="{ row }">
        <el-tag :type="severityType(row.severity)" :effect="severityEffect(row.severity)" size="small">
          {{ severityLabel(row.severity) }}
        </el-tag>
      </template>
    </el-table-column>

    <el-table-column label="类型" width="105" align="center">
      <template #default="{ row }">
        <el-tag :type="alertTypeValue(row.alert_type)" size="small" effect="plain">
          {{ alertTypeLabel(row.alert_type) }}
        </el-tag>
      </template>
    </el-table-column>

    <el-table-column prop="title" label="标题" min-width="170" show-overflow-tooltip />

    <el-table-column label="来源地址" min-width="140">
      <template #default="{ row }">
        <span class="mono">{{ row.source_ip }}</span>
      </template>
    </el-table-column>

    <el-table-column label="触发规则" min-width="150">
      <template #default="{ row }">
        <span class="mono">{{ row.rule_code }}</span>
        <span class="rule-name">{{ row.rule_name }}</span>
      </template>
    </el-table-column>

    <el-table-column
      prop="evidence_summary"
      label="证据摘要"
      min-width="260"
      show-overflow-tooltip
    />

    <el-table-column label="次数" width="70" align="right">
      <template #default="{ row }">{{ row.occurrence_count }}</template>
    </el-table-column>

    <el-table-column label="最近触发" min-width="165">
      <template #default="{ row }">{{ formatDateTime(row.last_seen_at) }}</template>
    </el-table-column>

    <el-table-column label="状态" width="85" align="center">
      <template #default="{ row }">
        <el-tag :type="row.is_read ? 'info' : 'warning'" size="small" effect="plain">
          {{ row.is_read ? '已读' : '未读' }}
        </el-tag>
      </template>
    </el-table-column>

    <el-table-column label="操作" width="120" align="center" fixed="right">
      <template #default="{ row }">
        <el-button
          v-if="!row.is_read"
          type="primary"
          link
          size="small"
          :loading="markingId === row.alert_id"
          @click="markRead(row)"
        >
          标记已读
        </el-button>
        <span v-else class="text-muted">已处置</span>
      </template>
    </el-table-column>

    <template #empty>
      <el-empty description="暂无告警数据" :image-size="80" />
    </template>
  </el-table>
</template>

<style scoped>
.rule-name {
  margin-left: 6px;
  color: #909399;
  font-size: 12px;
}

.text-muted {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
