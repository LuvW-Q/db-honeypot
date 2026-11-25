<script setup lang="ts">
import { computed } from 'vue'

export interface DonutSlice {
  key: string
  label: string
  value: number
  color: string
}

const props = defineProps<{ slices: DonutSlice[]; centerValue: number | string; centerLabel: string }>()

const total = computed(() => props.slices.reduce((sum, item) => sum + item.value, 0))

const radius = 54
const circumference = 2 * Math.PI * radius

const arcs = computed(() => {
  if (total.value <= 0) return []
  let offset = 0
  return props.slices.map((slice) => {
    const ratio = slice.value / total.value
    const length = ratio * circumference
    const arc = {
      ...slice,
      ratio,
      dasharray: `${length} ${circumference - length}`,
      dashoffset: -offset,
      percent: ratio * 100
    }
    offset += length
    return arc
  })
})
</script>

<template>
  <div class="flex flex-col items-center gap-space-lg lg:flex-row lg:items-center">
    <svg viewBox="0 0 160 160" class="h-40 w-40 shrink-0 -rotate-90" role="img" aria-label="规则命中与意图分布环图">
      <circle cx="80" cy="80" :r="radius" fill="none" class="stroke-surface-container-highest" stroke-width="16" />
      <circle
        v-for="arc in arcs"
        :key="arc.key"
        cx="80"
        cy="80"
        :r="radius"
        fill="none"
        :style="{ stroke: arc.color }"
        stroke-width="16"
        :stroke-dasharray="arc.dasharray"
        :stroke-dashoffset="arc.dashoffset"
        stroke-linecap="butt"
      />
      <g class="rotate-90" style="transform-origin: 80px 80px">
        <text x="80" y="78" text-anchor="middle" class="fill-on-surface" font-family="Inter" font-size="24" font-weight="700">{{ centerValue }}</text>
        <text x="80" y="96" text-anchor="middle" class="fill-on-surface-variant" font-family="Inter" font-size="10">{{ centerLabel }}</text>
      </g>
    </svg>
    <ul class="flex w-full flex-col gap-space-xs">
      <li v-for="arc in arcs" :key="`legend-${arc.key}`" class="flex items-center gap-space-sm">
        <span class="h-2.5 w-2.5 shrink-0 rounded-full" :style="{ background: arc.color }" aria-hidden="true" />
        <span class="font-code-sm text-code-sm text-on-surface">{{ arc.key }} {{ arc.label }}</span>
        <span class="ml-auto font-code-sm text-code-sm text-on-surface-variant">{{ arc.percent.toFixed(0) }}% ({{ arc.value }}次)</span>
      </li>
      <li v-if="arcs.length === 0" class="text-body-sm text-on-surface-variant">暂无命中数据</li>
    </ul>
  </div>
</template>
