<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = withDefaults(
  defineProps<{
    label: string
    value: number | string
    unit?: string
    note?: string
    source?: string
    icon?: string
    tone?: 'primary' | 'secondary' | 'error' | 'tertiary' | 'surface'
    to?: string
    deltaText?: string
    deltaTone?: 'up' | 'down' | 'muted' | 'error'
    progress?: number | null
  }>(),
  {
    unit: '',
    note: '',
    source: '',
    icon: 'hub',
    tone: 'primary',
    to: '',
    deltaText: '',
    deltaTone: 'muted',
    progress: null
  }
)

const router = useRouter()

const iconClass = ((): string => {
  switch (props.tone) {
    case 'secondary':
      return 'text-secondary'
    case 'error':
      return 'text-sev-critical'
    case 'tertiary':
      return 'text-tertiary'
    case 'surface':
      return 'text-on-surface-variant'
    default:
      return 'text-primary'
  }
})()
const iconBoxClass = props.tone === 'error' ? 'bg-error-container/60' : 'bg-surface-container'

const glowClass = ((): string => {
  switch (props.tone) {
    case 'secondary':
      return 'bg-secondary/5 group-hover:bg-secondary/10'
    case 'error':
      return 'bg-sev-critical/10 group-hover:bg-sev-critical/20'
    case 'tertiary':
      return 'bg-tertiary/10 group-hover:bg-tertiary/20'
    default:
      return 'bg-primary/5 group-hover:bg-primary/10'
  }
})()

const valueClass = props.tone === 'error' ? 'text-sev-critical' : 'text-on-surface'

function activate(): void {
  if (props.to) void router.push(props.to)
}
</script>

<template>
  <component
    :is="to ? 'a' : 'div'"
    class="group relative flex flex-col justify-between overflow-hidden rounded-lg bg-surface-container-low p-space-lg shadow-panel transition-colors"
    :class="to ? 'cursor-pointer hover:bg-surface-container' : ''"
    :href="to ? `#${to}` : undefined"
    @click="to ? activate() : undefined"
  >
    <div class="pointer-events-none absolute -bottom-4 -right-4 h-28 w-28 rounded-full blur-2xl transition-colors" :class="glowClass" />
    <div>
      <div class="flex items-center justify-between">
        <span class="text-body-sm font-semibold uppercase tracking-wider text-on-surface-variant">{{ label }}</span>
        <div class="flex h-8 w-8 items-center justify-center rounded transition-transform group-hover:scale-110" :class="iconBoxClass">
          <span class="material-symbols-outlined text-icon-md" :class="iconClass" aria-hidden="true">{{ icon }}</span>
        </div>
      </div>
      <div class="mt-space-sm flex flex-wrap items-baseline gap-space-sm">
        <span class="text-display-hero font-bold tracking-tight" :class="valueClass">{{ value }}</span>
        <span v-if="unit" class="font-code-sm text-code-sm text-outline">{{ unit }}</span>
        <span
          v-if="deltaText"
          class="inline-flex items-center gap-0.5 font-label-badge font-bold"
          :class="{
            'text-secondary': deltaTone === 'up',
            'text-primary': deltaTone === 'down',
            'text-on-surface-variant': deltaTone === 'muted',
            'text-sev-critical': deltaTone === 'error'
          }"
        >
          <span class="material-symbols-outlined text-icon-xs" aria-hidden="true">{{ deltaTone === 'down' ? 'arrow_downward' : 'arrow_upward' }}</span>
          {{ deltaText }}
        </span>
      </div>
      <div v-if="progress !== null" class="mt-space-sm h-1.5 w-full overflow-hidden rounded-full bg-surface-container-highest">
        <div class="h-full rounded-full bg-secondary" :style="{ width: `${Math.min(100, Math.max(0, progress))}%` }" />
      </div>
    </div>
    <div class="mt-space-md flex items-center justify-between border-t border-surface-container-high pt-space-sm font-code-sm text-code-sm text-on-surface-variant">
      <span class="flex min-w-0 items-center gap-1.5">
        <span class="inline-block h-1.5 w-1.5 shrink-0 rounded-full" :class="tone === 'error' ? 'bg-sev-critical' : 'bg-secondary'" />
        <span class="truncate" :title="note">{{ note }}</span>
      </span>
      <span v-if="source" class="shrink-0 whitespace-nowrap font-label-badge text-label-badge text-outline">SRC: {{ source }}</span>
    </div>
  </component>
</template>
