<script setup lang="ts">
defineProps<{
  title?: string
  subtitle?: string
  loading?: boolean
  error?: string | null
  empty?: boolean
  padded?: boolean
}>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <section class="flex flex-col rounded-lg bg-surface-container-low shadow-panel" :class="padded === false ? '' : 'p-space-lg'">
    <header v-if="title || $slots.actions" class="mb-space-md flex flex-wrap items-start justify-between gap-space-sm">
      <div v-if="title" class="flex flex-col gap-0.5">
        <h2 class="text-headline-sm font-bold text-on-surface">{{ title }}</h2>
        <p v-if="subtitle" class="text-body-sm text-on-surface-variant">{{ subtitle }}</p>
      </div>
      <div class="flex items-center gap-space-sm"><slot name="actions" /></div>
    </header>
    <div v-if="loading" class="flex min-h-30 items-center justify-center gap-2 font-code-sm text-code-sm text-outline" role="status">
      <span class="material-symbols-outlined animate-spin text-icon-md" aria-hidden="true">progress_activity</span>加载中…
    </div>
    <div v-else-if="error" class="flex flex-col items-start gap-space-sm rounded border border-sev-critical/40 bg-sev-critical/10 p-space-md" role="alert">
      <p class="text-body-sm text-sev-critical">{{ error }}</p>
      <button type="button" class="btn-secondary" @click="$emit('retry')">
        <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">refresh</span>重试
      </button>
    </div>
    <div v-else-if="empty" class="flex min-h-30 flex-col items-center justify-center gap-space-xs text-center">
      <span class="material-symbols-outlined text-icon-2xl text-outline" aria-hidden="true">inbox</span>
      <p class="text-body-sm text-on-surface-variant">暂无数据</p>
      <slot name="empty" />
    </div>
    <slot v-else />
  </section>
</template>
