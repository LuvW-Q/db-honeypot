<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const isDetailRoute = computed(() => route.name === 'attacker-detail')
const detailMenuIndex = computed(() => (isDetailRoute.value ? route.path : '/attackers/detail'))

const activeMenu = computed(() => {
  if (isDetailRoute.value) return route.path
  if (route.path.startsWith('/attackers')) return '/attackers'
  if (route.path.startsWith('/alerts')) return '/alerts'
  return '/'
})
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-header" height="64px">
      <div class="app-brand">
        <span class="app-brand__title">数据库蜜罐分析控制台</span>
        <span class="app-brand__subtitle">隔离实验环境 · 只读分析视图 · 告警处置</span>
      </div>

      <el-menu
        class="top-nav"
        mode="horizontal"
        :default-active="activeMenu"
        :ellipsis="false"
        router
      >
        <el-menu-item index="/">概览</el-menu-item>
        <el-menu-item index="/attackers">攻击者列表</el-menu-item>
        <el-menu-item :index="detailMenuIndex" :disabled="!isDetailRoute">攻击者详情</el-menu-item>
        <el-menu-item index="/alerts">告警列表</el-menu-item>
      </el-menu>
    </el-header>

    <el-main class="app-main">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </el-main>

    <el-footer class="app-footer" height="40px">
      数据来自核心分析视图 · 时间按浏览器本地时区展示 · 页面不展示任何完整口令
    </el-footer>
  </el-container>
</template>
