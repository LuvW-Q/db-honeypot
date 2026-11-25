<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ page: number; pageSize: number; total: number; totalPages: number; loading?: boolean }>()
const emit = defineEmits<{ 'update:page': [value: number] }>()

const pages = computed<number[]>(() => {
  const total = Math.max(1, props.totalPages)
  const start = Math.max(1, Math.min(props.page - 2, total - 4))
  const end = Math.min(total, start + 4)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})

function go(page: number): void {
  if (props.loading) return
  if (page < 1 || page > Math.max(1, props.totalPages) || page === props.page) return
  emit('update:page', page)
}
</script>

<template>
  <div class="mt-space-md flex flex-wrap items-center justify-between gap-space-sm border-t border-surface-container-high pt-space-md">
    <span class="font-code-sm text-code-sm text-on-surface-variant">
      显示第 {{ total === 0 ? 0 : (page - 1) * pageSize + 1 }} 至 {{ Math.min(page * pageSize, total) }} 条 · 共 {{ total }} 条记录 · 每页 {{ pageSize }} 条
    </span>
    <div class="flex items-center gap-1">
      <button type="button" class="btn-secondary px-2 py-1" :disabled="page <= 1 || loading" aria-label="上一页" @click="go(page - 1)">
        <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">chevron_left</span>
      </button>
      <button
        v-for="item in pages"
        :key="item"
        type="button"
        class="min-w-8 rounded px-2 py-1 font-code-sm text-code-sm transition-colors"
        :class="item === page ? 'bg-primary-container font-semibold text-on-primary-container' : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'"
        :aria-current="item === page ? 'page' : undefined"
        @click="go(item)"
      >
        {{ item }}
      </button>
      <button type="button" class="btn-secondary px-2 py-1" :disabled="page >= totalPages || totalPages <= 1 || loading" aria-label="下一页" @click="go(page + 1)">
        <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">chevron_right</span>
      </button>
    </div>
  </div>
</template>
