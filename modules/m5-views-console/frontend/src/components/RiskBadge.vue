<script setup lang="ts">
import { computed } from 'vue'
import { riskLevelLabel } from '../utils/format'

interface Props {
  level?: string | null
  score?: number | null
  showScore?: boolean
  size?: 'default' | 'small'
  dot?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  level: null,
  score: null,
  showScore: false,
  size: 'default',
  dot: true
})

const toneClass = computed(() => {
  switch (props.level) {
    case 'low':
      return 'border-sev-low/40 bg-sev-low/10 text-sev-low'
    case 'medium':
      return 'border-sev-medium/40 bg-sev-medium/10 text-sev-medium'
    case 'high':
      return 'border-sev-high/40 bg-sev-high/10 text-sev-high'
    case 'critical':
      return 'border-sev-critical/45 bg-sev-critical/15 text-sev-critical'
    default:
      return 'border-outline-variant bg-surface-container-high text-on-surface-variant'
  }
})

const dotClass = computed(() => {
  switch (props.level) {
    case 'low':
      return 'bg-sev-low'
    case 'medium':
      return 'bg-sev-medium'
    case 'high':
      return 'bg-sev-high'
    case 'critical':
      return 'bg-sev-critical'
    default:
      return 'bg-outline'
  }
})

const sizeClass = computed(() =>
  props.size === 'small' ? 'px-1.5 py-0 text-micro leading-4' : ''
)

const text = computed(() => {
  const label = riskLevelLabel(props.level)
  if (props.showScore && typeof props.score === 'number' && !Number.isNaN(props.score)) {
    return `${props.score} ${label}`
  }
  return label
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1 whitespace-nowrap rounded border font-label-badge font-semibold uppercase tracking-wider"
    :class="[toneClass, sizeClass, size === 'small' ? '' : 'px-2 py-0.5']"
  >
    <span v-if="dot" class="inline-block h-1.5 w-1.5 rounded-full" :class="dotClass" aria-hidden="true" />
    {{ text }}
  </span>
</template>
