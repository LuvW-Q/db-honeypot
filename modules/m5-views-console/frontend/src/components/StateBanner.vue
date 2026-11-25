<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'info' | 'warn' | 'error'; title: string }>(), { tone: 'info' })
defineEmits<{ retry: [] }>()
</script>

<template>
  <div
    class="flex flex-wrap items-center justify-between gap-space-sm rounded-lg border px-space-lg py-space-md"
    :class="{
      'border-primary/30 bg-primary/10 text-primary': tone === 'info',
      'border-sev-medium/40 bg-sev-medium/10 text-sev-medium': tone === 'warn',
      'border-sev-critical/40 bg-sev-critical/10 text-sev-critical': tone === 'error'
    }"
    role="alert"
  >
    <div class="flex items-center gap-space-sm">
      <span class="material-symbols-outlined text-icon-md" aria-hidden="true">{{ tone === 'error' ? 'error' : tone === 'warn' ? 'warning' : 'info' }}</span>
      <span class="text-body-sm font-semibold">{{ title }}</span>
      <slot />
    </div>
    <button v-if="$attrs.onRetry" type="button" class="rounded border border-current px-space-sm py-0.5 font-body-sm text-body-sm" @click="$emit('retry')">
      重试
    </button>
  </div>
</template>
