<script setup lang="ts">
import { computed } from 'vue'
import { formatNumber } from '../utils/format'

interface Props {
  title: string
  value: number | string | null | undefined
  hint?: string
  loading?: boolean
  tone?: 'primary' | 'success' | 'warning' | 'danger'
}

const props = withDefaults(defineProps<Props>(), {
  hint: '',
  loading: false,
  tone: 'primary'
})

const displayValue = computed(() => {
  if (props.value === null || props.value === undefined) return '—'
  if (typeof props.value === 'number') return formatNumber(props.value)
  return props.value
})
</script>

<template>
  <el-card shadow="hover" class="stat-card" :class="`stat-card--${tone}`">
    <div class="stat-card__label">{{ title }}</div>
    <el-skeleton v-if="loading" class="stat-card__skeleton" animated :rows="1" />
    <div v-else class="stat-card__value">{{ displayValue }}</div>
    <div v-if="hint" class="stat-card__hint">{{ hint }}</div>
  </el-card>
</template>

<style scoped>
.stat-card {
  position: relative;
  overflow: hidden;
  border-radius: 8px;
}

.stat-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--stat-tone, #409eff);
}

.stat-card--primary {
  --stat-tone: #409eff;
}

.stat-card--success {
  --stat-tone: #67c23a;
}

.stat-card--warning {
  --stat-tone: #e6a23c;
}

.stat-card--danger {
  --stat-tone: #f56c6c;
}

.stat-card__label {
  font-size: 13px;
  color: #909399;
}

.stat-card__value {
  margin-top: 8px;
  font-size: 30px;
  font-weight: 600;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat-card__skeleton {
  margin-top: 8px;
}

.stat-card__hint {
  margin-top: 6px;
  font-size: 12px;
  color: #b1b3b8;
}
</style>
