<script setup lang="ts">
import { computed } from 'vue'
import type { TrendItem } from '../types'

const props = withDefaults(defineProps<{ items: TrendItem[]; height?: number; showLegend?: boolean }>(), {
  height: 240,
  showLegend: true
})

const W = 700
const H = 240
const PAD = { left: 44, right: 16, top: 22, bottom: 28 }

interface Series {
  key: 'bruteforce' | 'data_dump' | 'scanning'
  label: string
  color: string
  fill: string
  values: number[]
}

const series = computed<Series[]>(() => [
  {
    key: 'bruteforce',
    label: '爆破 (R02)',
    color: 'var(--chart-1)',
    fill: 'url(#grad-cyan)',
    values: props.items.map((item) => item.hit_bruteforce ?? 0)
  },
  {
    key: 'data_dump',
    label: '拖库/查询 (R04)',
    color: 'var(--chart-2)',
    fill: 'url(#grad-green)',
    values: props.items.map((item) => item.hit_data_dump ?? 0)
  },
  {
    key: 'scanning',
    label: '踩点扫描 (R01/03)',
    color: 'var(--chart-3)',
    fill: 'none',
    values: props.items.map((item) => (item.hit_scanning ?? 0) + (item.hit_recon ?? 0))
  }
])

const maxValue = computed(() => {
  const all = series.value.flatMap((item) => item.values)
  const max = Math.max(1, ...all)
  return Math.ceil(max / 5) * 5 || 5
})

const x = computed(() => (index: number): number => {
  const count = Math.max(1, props.items.length - 1)
  return PAD.left + (index / count) * (W - PAD.left - PAD.right)
})

function y(value: number): number {
  const usable = H - PAD.top - PAD.bottom
  return PAD.top + usable - (value / maxValue.value) * usable
}

function linePath(values: number[]): string {
  if (values.length === 0) return ''
  return values
    .map((value, index) => `${index === 0 ? 'M' : 'L'}${x.value(index).toFixed(2)},${y(value).toFixed(2)}`)
    .join(' ')
}

function areaPath(values: number[]): string {
  if (values.length === 0) return ''
  const base = y(0)
  const line = linePath(values)
  return `${line} L${x.value(values.length - 1).toFixed(2)},${base.toFixed(2)} L${x.value(0).toFixed(2)},${base.toFixed(2)} Z`
}

const gridLines = computed(() =>
  [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    y: PAD.top + ratio * (H - PAD.top - PAD.bottom),
    label: Math.round(maxValue.value * (1 - ratio)).toString()
  }))
)

const xTicks = computed(() => {
  const step = Math.max(1, Math.ceil(props.items.length / 8))
  return props.items
    .map((item, index) => ({ index, label: item.stat_date.slice(5), show: index % step === 0 || index === props.items.length - 1 }))
    .filter((tick) => tick.show)
})

const peak = computed(() => {
  if (props.items.length === 0) return null
  let best = { index: 0, value: series.value[0]?.values[0] ?? 0 }
  series.value.forEach((item) => {
    item.values.forEach((value, index) => {
      if (value > best.value) best = { index, value }
    })
  })
  if (best.value <= 0) return null
  return { x: x.value(best.index), y: y(best.value), value: best.value, date: props.items[best.index]?.stat_date ?? '' }
})
</script>

<template>
  <div class="flex w-full flex-col gap-space-sm">
    <div class="relative w-full overflow-hidden rounded bg-surface-container-lowest p-space-sm">
      <svg :viewBox="`0 0 ${W} ${H}`" :style="{ height: `${height}px` }" class="w-full" preserveAspectRatio="none" role="img" aria-label="每日攻击趋势面积图">
        <defs>
          <linearGradient id="grad-cyan" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" :style="{ stopColor: 'var(--chart-1)' }" stop-opacity="0.35" />
            <stop offset="100%" :style="{ stopColor: 'var(--chart-1)' }" stop-opacity="0" />
          </linearGradient>
          <linearGradient id="grad-green" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" :style="{ stopColor: 'var(--chart-2)' }" stop-opacity="0.25" />
            <stop offset="100%" :style="{ stopColor: 'var(--chart-2)' }" stop-opacity="0" />
          </linearGradient>
        </defs>
        <g>
          <line
            v-for="line in gridLines.slice(0, 4)"
            :key="line.y"
            :x1="PAD.left"
            :x2="W - PAD.right"
            :y1="line.y"
            :y2="line.y"
            class="stroke-surface-container-high"
            stroke-dasharray="3,3"
            stroke-width="1"
          />
          <line :x1="PAD.left" :x2="W - PAD.right" :y1="y(0)" :y2="y(0)" class="stroke-surface-container-highest" stroke-width="1.5" />
          <text
            v-for="line in gridLines"
            :key="`label-${line.y}`"
            :x="PAD.left - 8"
            :y="line.y + 3"
            class="fill-outline"
            font-family="JetBrains Mono"
            font-size="10"
            text-anchor="end"
          >
            {{ line.label }}
          </text>
          <text
            v-for="tick in xTicks"
            :key="`x-${tick.index}`"
            :x="x(tick.index)"
            :y="H - 8"
            class="fill-outline"
            font-family="JetBrains Mono"
            font-size="10"
            text-anchor="middle"
          >
            {{ tick.label }}
          </text>
        </g>
        <path :d="areaPath(series[0].values)" :fill="series[0].fill" />
        <path :d="areaPath(series[1].values)" :fill="series[1].fill" />
        <path :d="linePath(series[0].values)" fill="none" :style="{ stroke: series[0].color }" stroke-width="2" />
        <path :d="linePath(series[1].values)" fill="none" :style="{ stroke: series[1].color }" stroke-width="1.75" />
        <path :d="linePath(series[2].values)" fill="none" :style="{ stroke: series[2].color }" stroke-width="1.5" stroke-dasharray="4,3" />
        <g v-if="peak">
          <circle :cx="peak.x" :cy="peak.y" r="4" :style="{ fill: 'var(--chart-1)', stroke: 'var(--chart-peak-ring)' }" stroke-width="2" />
          <g :transform="`translate(${Math.min(W - 100, Math.max(PAD.left, peak.x - 46))}, ${Math.max(8, peak.y - 34)})`">
            <rect width="92" height="22" rx="3" :style="{ fill: 'var(--chart-tooltip-bg)' }" />
            <text x="46" y="15" :style="{ fill: 'var(--chart-tooltip-fg)' }" font-family="JetBrains Mono" font-size="10" text-anchor="middle">{{ peak.value }} 次峰值</text>
          </g>
        </g>
      </svg>
    </div>
    <div v-if="showLegend" class="flex flex-wrap items-center gap-space-md">
      <div v-for="item in series" :key="item.key" class="flex items-center gap-1 font-code-sm text-code-sm text-on-surface">
        <span class="h-2 w-3 rounded-sm" :style="{ background: item.color }" aria-hidden="true" />
        <span>{{ item.label }}</span>
      </div>
    </div>
  </div>
</template>
