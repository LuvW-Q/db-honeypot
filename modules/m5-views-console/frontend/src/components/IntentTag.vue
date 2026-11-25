<script setup lang="ts">
import { computed } from 'vue'
import { intentMeta } from '../utils/format'

const props = withDefaults(
  defineProps<{ intent?: string | null; label?: string; compact?: boolean; showRule?: boolean }>(),
  { intent: null, label: '', compact: false, showRule: true }
)

const meta = computed(() => intentMeta(props.intent))
const text = computed(() => props.label || (props.compact ? meta.value.short : meta.value.label))

// 意图族色（与趋势图/环图同色族，原型 _1/_4 的标签配色）：静态类名便于 Tailwind 扫描
const TONES: Record<string, { box: string; rule: string }> = {
  bruteforce: { box: 'border-sev-critical/35 bg-sev-critical/15 text-sev-critical', rule: 'text-sev-critical/70' },
  data_dump: { box: 'border-primary/35 bg-primary/15 text-primary', rule: 'text-primary/70' },
  recon: { box: 'border-sev-medium/35 bg-sev-medium/15 text-sev-medium', rule: 'text-sev-medium/70' },
  scanning: { box: 'border-outline/40 bg-outline/15 text-on-surface-variant', rule: 'text-outline' },
  destructive: { box: 'border-sev-high/35 bg-sev-high/15 text-sev-high', rule: 'text-sev-high/70' }
}
const tone = computed(() => TONES[props.intent ?? ''] ?? { box: 'border-tertiary/35 bg-tertiary/15 text-tertiary', rule: 'text-tertiary/70' })
</script>

<template>
  <span
    class="inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-code-xs font-medium"
    :class="tone.box"
    :title="meta.label"
  >
    {{ text }}
    <span v-if="showRule && !compact && meta.rule !== '—'" :class="tone.rule">{{ meta.rule }}</span>
    <span v-else-if="showRule && compact" :class="tone.rule">{{ meta.rule }}</span>
  </span>
</template>
