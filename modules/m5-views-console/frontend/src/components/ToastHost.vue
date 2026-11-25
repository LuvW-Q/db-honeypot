<script setup lang="ts">
import { dismissToast, toastState } from '../composables/toast'
</script>

<template>
  <div class="pointer-events-none fixed right-8 top-20 z-toast flex w-90 max-w-90 flex-col gap-space-sm">
    <article
      v-for="toast in toastState.items"
      :key="toast.id"
      class="pointer-events-auto flex items-start gap-space-md rounded-lg bg-surface-container-highest p-space-md shadow-panel"
      :class="{
        'border border-secondary/40': toast.tone === 'success',
        'border border-sev-critical/50': toast.tone === 'error',
        'border border-sev-medium/50': toast.tone === 'partial'
      }"
      role="status"
    >
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
        :class="{
          'bg-secondary/15 text-secondary': toast.tone === 'success',
          'bg-sev-critical/15 text-sev-critical': toast.tone === 'error',
          'bg-sev-medium/15 text-sev-medium': toast.tone === 'partial'
        }"
      >
        <span class="material-symbols-outlined text-icon-md" aria-hidden="true">{{ toast.tone === 'success' ? 'verified' : toast.tone === 'partial' ? 'warning' : 'error' }}</span>
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-headline-sm font-semibold text-on-surface">{{ toast.title }}</p>
        <p v-if="toast.message" class="mt-0.5 whitespace-pre-line break-words font-code-sm text-code-sm text-on-surface-variant">{{ toast.message }}</p>
      </div>
      <button type="button" class="text-outline hover:text-on-surface" aria-label="关闭提示" @click="dismissToast(toast.id)">
        <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">close</span>
      </button>
    </article>
  </div>
</template>
