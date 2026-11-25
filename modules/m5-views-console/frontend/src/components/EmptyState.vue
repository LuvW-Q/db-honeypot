<script setup lang="ts">
defineProps<{ title: string; hint?: string; icon?: string }>()
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-space-sm py-space-xl text-center">
    <span class="material-symbols-outlined text-icon-3xl text-outline" aria-hidden="true">{{ icon || 'inbox' }}</span>
    <p class="text-headline-sm font-semibold text-on-surface">{{ title }}</p>
    <p v-if="hint" class="max-w-md text-body-sm text-on-surface-variant">{{ hint }}</p>
    <slot />
  </div>
</template>
