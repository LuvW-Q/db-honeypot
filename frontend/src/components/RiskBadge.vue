<script setup lang="ts">
import { computed } from 'vue'
import { riskLevelLabel } from '../utils/format'

interface Props {
  level?: string | null
  score?: number | null
  showScore?: boolean
  size?: 'large' | 'default' | 'small'
}

const props = withDefaults(defineProps<Props>(), {
  level: null,
  score: null,
  showScore: true,
  size: 'default'
})

const tagType = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  switch (props.level) {
    case 'low':
      return 'success'
    case 'medium':
      return 'warning'
    case 'high':
    case 'critical':
      return 'danger'
    default:
      return 'info'
  }
})

const effect = computed(() => (props.level === 'critical' ? 'dark' : 'light'))

const text = computed(() => {
  const label = riskLevelLabel(props.level)
  if (props.showScore && typeof props.score === 'number' && !Number.isNaN(props.score)) {
    return `${label} ${props.score}`
  }
  return label
})
</script>

<template>
  <el-tag :type="tagType" :effect="effect" :size="size" class="risk-badge">{{ text }}</el-tag>
</template>
