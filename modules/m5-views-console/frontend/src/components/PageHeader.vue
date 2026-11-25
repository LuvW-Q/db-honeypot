<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
  badge?: string
  badgeTone?: 'live' | 'muted'
}>()
</script>

<template>
  <div class="flex flex-col gap-space-md lg:flex-row lg:items-center lg:justify-between">
    <div class="flex flex-col gap-space-xs">
      <div class="flex flex-wrap items-center gap-space-sm">
        <h1 class="text-headline-lg font-semibold tracking-tight text-on-surface">{{ title }}</h1>
        <span v-if="subtitle" class="mono text-code-md font-medium tracking-wide text-primary">{{ subtitle }}</span>
        <span
          v-if="badge"
          class="inline-flex items-center gap-1 rounded px-2 py-0.5 font-label-badge text-label-badge uppercase tracking-wider"
          :class="badgeTone === 'muted' ? 'bg-surface-container-high text-on-surface-variant' : 'bg-surface-container-high text-secondary'"
        >
          <span v-if="badgeTone !== 'muted'" class="relative flex h-2 w-2">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-secondary opacity-70" />
            <span class="relative inline-flex h-2 w-2 rounded-full bg-secondary" />
          </span>
          {{ badge }}
        </span>
      </div>
      <slot name="sub" />
    </div>
    <div class="flex flex-wrap items-center gap-space-sm self-start lg:self-auto">
      <slot name="actions" />
    </div>
  </div>
</template>
