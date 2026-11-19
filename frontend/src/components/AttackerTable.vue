<script setup lang="ts">
import { formatDateTime, formatNumber } from '../utils/format'
import type { AttackerSummary } from '../types'
import IntentTag from './IntentTag.vue'
import RiskBadge from './RiskBadge.vue'

interface Props {
  items: AttackerSummary[]
  loading?: boolean
}

withDefaults(defineProps<Props>(), { loading: false })

const emit = defineEmits<{ (event: 'row-click', row: AttackerSummary): void }>()

function onRowClick(row: AttackerSummary): void {
  emit('row-click', row)
}

function rowClassName(): string {
  return 'clickable-row'
}
</script>

<template>
  <el-table
    v-loading="loading"
    :data="items"
    row-key="attacker_id"
    :row-class-name="rowClassName"
    stripe
    border
    style="width: 100%"
    @row-click="onRowClick"
  >
    <el-table-column prop="source_ip" label="来源地址" min-width="160" fixed>
      <template #default="{ row }">
        <span class="mono">{{ row.source_ip }}</span>
      </template>
    </el-table-column>

    <el-table-column label="风险" width="150" align="center">
      <template #default="{ row }">
        <RiskBadge :level="row.risk_level" :score="row.risk_score" />
      </template>
    </el-table-column>

    <el-table-column label="主要意图" width="130" align="center">
      <template #default="{ row }">
        <IntentTag v-if="row.main_intent" :intent-type="row.main_intent.intent_type" />
        <span v-else class="text-muted">—</span>
      </template>
    </el-table-column>

    <el-table-column label="连接数" width="90" align="right">
      <template #default="{ row }">{{ formatNumber(row.total_connections) }}</template>
    </el-table-column>

    <el-table-column label="认证尝试" width="100" align="right">
      <template #default="{ row }">{{ formatNumber(row.total_auth_attempts) }}</template>
    </el-table-column>

    <el-table-column label="查询数" width="90" align="right">
      <template #default="{ row }">{{ formatNumber(row.total_queries) }}</template>
    </el-table-column>

    <el-table-column label="告警" width="80" align="right">
      <template #default="{ row }">{{ formatNumber(row.alert_count) }}</template>
    </el-table-column>

    <el-table-column label="首次出现" min-width="165">
      <template #default="{ row }">{{ formatDateTime(row.first_seen) }}</template>
    </el-table-column>

    <el-table-column label="最近出现" min-width="165">
      <template #default="{ row }">{{ formatDateTime(row.last_seen) }}</template>
    </el-table-column>

    <el-table-column label="操作" width="110" align="center">
      <template #default="{ row }">
        <el-button type="primary" link size="small" @click.stop="onRowClick(row)">
          查看画像
        </el-button>
      </template>
    </el-table-column>

    <template #empty>
      <el-empty description="暂无攻击者数据" :image-size="80" />
    </template>
  </el-table>
</template>

<style scoped>
.text-muted {
  color: #c0c4cc;
}
</style>
