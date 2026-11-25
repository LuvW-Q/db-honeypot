<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import ToastHost from './components/ToastHost.vue'
import { fetchHealth, honeypotApi } from './api'
import { provideRefreshBus } from './composables/refresh'
import { useTheme, type ThemeMode } from './composables/theme'
import { formatClock } from './utils/format'
import type { HealthResponse } from './types'

const route = useRoute()
const bus = provideRefreshBus()
const { mode: themeMode, resolved: resolvedTheme, cycleMode } = useTheme()

// 顶栏圆角矩形主题按钮：点击循环 跟随系统 → 浅色 → 深色（ui-contracts §9）。
const THEME_META: Record<ThemeMode, { label: string; icon: string; hint: string }> = {
  system: { label: '跟随系统', icon: 'brightness_auto', hint: '当前跟随系统外观，点击切换为浅色' },
  light: { label: '浅色', icon: 'light_mode', hint: '当前浅色外观，点击切换为深色' },
  dark: { label: '深色', icon: 'dark_mode', hint: '当前深色外观，点击恢复跟随系统' }
}
const themeMeta = computed(() => THEME_META[themeMode.value])
const themeButtonLabel = computed(() => `主题：${themeMeta.value.label}（${resolvedTheme.value === 'light' ? '浅色' : '深色'}）`)
const themeButtonTitle = computed(() => `${themeButtonLabel.value} · ${themeMeta.value.hint}`)

const health = ref<HealthResponse | null>(null)
const healthError = ref(false)
const unread = ref(0)
const now = ref(new Date())
const lastAttackerIp = ref<string | null>(null)
let clockTimer: number | undefined

const nav = [
  { to: '/', index: '01', label: '首页概览', icon: 'grid_view', match: (path: string) => path === '/' },
  { to: '/attackers', index: '02', label: '攻击者列表', icon: 'person_alert', match: (path: string) => path.startsWith('/attackers') && path !== '/attackers/detail' },
  { to: '', index: '03', label: '攻击者详情与时间线', icon: 'troubleshoot', match: (path: string) => /^\/attackers\/[^/]+$/.test(path) },
  { to: '/alerts', index: '04', label: '告警列表', icon: 'notifications_active', match: (path: string) => path.startsWith('/alerts') }
]

const activePath = computed(() => route.path)
const detailLink = computed(() => (lastAttackerIp.value ? `/attackers/${lastAttackerIp.value}` : ''))

const dbOk = computed(() => health.value?.status === 'ok')
const listenText = computed(() => {
  if (healthError.value) return '诱饵库状态不可用'
  const listenter = health.value?.honeypot
  if (!listenter) return '诱饵库监听中: PORT 3306'
  const status = listenter.status === 'ok' ? '监听中' : listenter.status === 'disabled' ? '已停用' : '离线'
  return `诱饵库${status}: ${listenter.listen ?? 'PORT 3306'}`
})
const dbText = computed(() => {
  if (healthError.value) return 'DB 状态未知'
  return dbOk.value ? '演示库就绪' : '数据库降级'
})
const version = computed(() => health.value?.version ?? 'v1.1.0')
const clockText = computed(() => `LIVE UTC+8 · ${formatClock(now.value.toISOString())}`)

function readLastIp(): void {
  try {
    lastAttackerIp.value = sessionStorage.getItem('lastAttackerIp')
  } catch {
    lastAttackerIp.value = null
  }
}

async function loadChrome(): Promise<void> {
  healthError.value = false
  try {
    health.value = await fetchHealth()
    healthError.value = !health.value
    const summary = await honeypotApi.getAlertsSummary()
    unread.value = summary.unread
  } catch {
    healthError.value = true
  }
}

function refresh(): void {
  if (bus.refreshing.value) return
  bus.trigger()
}

watch(
  () => route.fullPath,
  () => {
    readLastIp()
    if (/^\/attackers\/[^/]+$/.test(route.path)) {
      try {
        sessionStorage.setItem('lastAttackerIp', String(route.params.ip))
      } catch {
        /* sessionStorage 不可用时导航 03 保持禁用 */
      }
      readLastIp()
    }
  }
)

onMounted(() => {
  readLastIp()
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
  void loadChrome()
})

onBeforeUnmount(() => {
  if (clockTimer) window.clearInterval(clockTimer)
})
</script>

<template>
  <div class="min-h-screen bg-background text-on-surface">
    <!-- 侧栏：固定 288px（w-72），品牌 + 监听状态 + 四项导航 + 底部状态块 -->
    <aside data-region="SHELL-SIDEBAR" class="fixed left-0 top-0 z-50 flex h-full w-72 flex-col justify-between bg-surface-container-low shadow-panel">
      <div class="flex flex-col">
        <div class="px-space-xl pb-space-md pt-space-lg">
          <div class="flex items-center gap-space-sm">
            <svg class="h-8 w-8 shrink-0" viewBox="0 0 32 32" aria-hidden="true">
              <rect width="32" height="32" rx="6" class="fill-surface-container-low" />
              <path d="M6 10h20M6 16h20M6 22h20" class="stroke-primary" stroke-width="2.5" stroke-linecap="round" />
              <circle cx="10" cy="10" r="2" class="fill-secondary" />
              <circle cx="22" cy="16" r="2" class="fill-secondary" />
              <circle cx="14" cy="22" r="2" class="fill-secondary" />
            </svg>
            <div class="flex flex-col">
              <span class="text-headline-sm font-bold tracking-tight text-primary">DB Honeypot</span>
              <span class="text-body-sm font-medium text-on-surface-variant">攻击行为分析系统</span>
            </div>
          </div>
          <div class="mt-space-md flex items-center gap-space-xs rounded bg-surface-container-lowest p-space-sm">
            <span class="relative flex h-2 w-2">
              <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-secondary opacity-70" />
              <span class="relative inline-flex h-2 w-2 rounded-full bg-secondary" />
            </span>
            <span class="truncate font-code-sm text-code-sm font-medium tracking-tight text-secondary">{{ listenText }}</span>
          </div>
          <p class="mt-1 font-code-sm text-code-sm text-outline">{{ dbText }} · {{ clockText }}</p>
        </div>

        <nav class="flex flex-col gap-space-xs px-space-md pt-space-sm" aria-label="主导航">
          <template v-for="item in nav" :key="item.index">
            <router-link
              v-if="item.index !== '03'"
              :to="item.to"
              class="flex items-center justify-between rounded px-space-md py-space-sm transition-all"
              :class="item.match(activePath) ? 'border border-primary/30 bg-primary/10 font-headline-sm font-semibold text-primary' : 'text-body-md text-on-surface-variant hover:bg-surface-container hover:text-on-surface'"
              :aria-current="item.match(activePath) ? 'page' : undefined"
            >
              <div class="flex items-center gap-space-md">
                <span class="material-symbols-outlined text-icon-lg" aria-hidden="true">{{ item.icon }}</span>
                <span>{{ item.label }}</span>
              </div>
              <span v-if="item.index === '04' && unread > 0" class="rounded bg-error-container px-1.5 py-0.5 font-label-badge text-label-badge font-bold text-on-error-container">{{ unread }}</span>
              <span v-else class="font-code-sm text-code-sm text-outline">{{ item.index }}</span>
            </router-link>
            <template v-else>
              <router-link
                v-if="detailLink"
                :to="detailLink"
                class="flex items-center justify-between rounded px-space-md py-space-sm transition-all"
                :class="item.match(activePath) ? 'border border-primary/30 bg-primary/10 font-headline-sm font-semibold text-primary' : 'text-body-md text-on-surface-variant hover:bg-surface-container hover:text-on-surface'"
                :aria-current="item.match(activePath) ? 'page' : undefined"
              >
                <div class="flex items-center gap-space-md">
                  <span class="material-symbols-outlined text-icon-lg" aria-hidden="true">{{ item.icon }}</span>
                  <span>{{ item.label }}</span>
                </div>
                <span class="font-code-sm text-code-sm text-outline">{{ item.index }}</span>
              </router-link>
              <span
                v-else
                class="flex cursor-not-allowed items-center justify-between rounded px-space-md py-space-sm text-body-md text-outline opacity-60"
                aria-disabled="true"
                title="请先从攻击者列表进入"
              >
                <div class="flex items-center gap-space-md">
                  <span class="material-symbols-outlined text-icon-lg" aria-hidden="true">{{ item.icon }}</span>
                  <span>{{ item.label }}</span>
                </div>
                <span class="font-code-sm text-code-sm text-outline">{{ item.index }}</span>
              </span>
            </template>
          </template>
        </nav>
      </div>

      <div data-region="SHELL-STATUS" class="border-t border-surface-container-high px-space-xl py-space-md">
        <div class="flex flex-col gap-1 font-code-sm text-code-sm">
          <div class="flex items-center justify-between gap-space-sm">
            <span class="text-outline">内核视图</span>
            <span class="text-secondary">● core_views 同步正常</span>
          </div>
          <div class="flex items-center justify-between gap-space-sm">
            <span class="text-outline">当前权限</span>
            <span class="text-on-surface-variant">观察者（只读模式）</span>
          </div>
          <div class="flex items-center justify-between gap-space-sm">
            <span class="text-outline">规格版本</span>
            <span class="text-on-surface-variant">{{ version }}</span>
          </div>
        </div>
      </div>
    </aside>

    <div class="pl-72">
      <!-- 页头：固定 64px，左起 288px -->
      <header data-region="SHELL-HEADER" class="fixed left-72 right-0 top-0 z-40 flex h-16 items-center justify-between bg-surface/85 px-gutter-lg shadow-panel backdrop-blur-xl">
        <div class="flex items-center gap-space-md">
          <div class="flex items-center gap-space-xs rounded bg-surface-container-high px-space-sm py-1">
            <span class="material-symbols-outlined text-icon-sm text-primary" aria-hidden="true">dns</span>
            <span class="font-code-sm text-code-sm font-medium text-on-surface">Honeypot-MySQL-01 (Isolated DMZ)</span>
          </div>
          <span class="rounded bg-tertiary-container/30 px-2 py-0.5 font-label-badge text-label-badge font-semibold tracking-wide text-tertiary" title="AI 辅助分析（未启用）">AI 辅助分析</span>
        </div>
        <div class="flex items-center gap-space-lg">
          <div class="flex items-center gap-space-xs font-code-sm text-code-sm text-on-surface-variant">
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">schedule</span>
            <span>{{ clockText }}</span>
          </div>
          <button
            type="button"
            class="flex items-center gap-space-xs rounded border border-outline-variant bg-surface-container-low px-space-md py-1.5 font-body-sm text-body-sm text-on-surface-variant shadow-sm transition-all hover:bg-surface-container-high hover:text-on-surface"
            :aria-label="themeButtonLabel"
            :title="themeButtonTitle"
            :data-theme-mode="themeMode"
            data-theme-toggle
            @click="cycleMode"
          >
            <span class="material-symbols-outlined text-icon-sm" aria-hidden="true">{{ themeMeta.icon }}</span>
            <span>{{ themeMeta.label }}</span>
          </button>
          <button
            type="button"
            class="flex items-center gap-space-xs rounded bg-surface-container-high px-space-md py-1.5 font-body-sm text-body-sm text-primary shadow-glow-primary transition-all hover:bg-surface-container-highest hover:text-on-surface"
            :disabled="bus.refreshing.value"
            @click="refresh"
          >
            <span class="material-symbols-outlined text-icon-sm" :class="bus.refreshing.value ? 'animate-spin' : ''" aria-hidden="true">refresh</span>
            <span>{{ bus.refreshing.value ? '刷新中…' : '现场刷新数据' }}</span>
          </button>
          <div class="flex h-8 w-8 items-center justify-center rounded-full bg-primary">
            <span class="material-symbols-outlined text-icon-md text-on-primary" aria-hidden="true">person</span>
          </div>
        </div>
      </header>

      <main data-region="SHELL-MAIN" class="flex min-h-screen flex-col px-gutter-lg pb-margin-lg pt-16">
        <div v-if="healthError" class="mt-space-md">
          <div class="rounded-lg border border-sev-critical/40 bg-sev-critical/10 px-space-lg py-space-md text-body-sm text-sev-critical" role="alert">
            数据库不可用或健康检查失败，以下为最近一次成功数据。
            <button type="button" class="ml-2 underline" @click="loadChrome">重试</button>
          </div>
        </div>
        <div class="flex-1 pt-space-lg">
          <router-view />
        </div>
        <footer data-region="SHELL-FOOTER" class="mt-space-lg border-t border-surface-container-high pt-space-md font-code-sm text-code-sm text-outline">
          数据来自核心分析视图 · 时间按 UTC+8 展示 · 不展示完整口令
        </footer>
      </main>
    </div>

    <ToastHost />
  </div>
</template>
