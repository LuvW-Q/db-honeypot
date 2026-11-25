<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ value?: number | null; level?: string | null }>(), {
  value: 0,
  level: null
})

const width = computed(() => {
  const raw = typeof props.value === 'number' && !Number.isNaN(props.value) ? props.value : 0
  return `${Math.min(100, Math.max(0, raw))}%`
})

const tone = computed(() => {
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
      return 'bg-primary'
  }
})
</script>

<template>
  <div class="flex items-center gap-space-sm" :aria-label="`风险分 ${value ?? 0}`">
    <div class="h-1.5 w-full min-w-14 overflow-hidden rounded-full bg-surface-container-highest">
      <div class="h-full rounded-full transition-all" :class="tone" :style="{ width }" />
    </div>
    <span class="mono w-7 shrink-0 text-right text-code-sm text-on-surface">{{ value ?? 0 }}</span>
  </div>
</template>
