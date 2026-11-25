import { createRouter, createWebHashHistory } from 'vue-router'

// 四页固定（FR-061），hash 模式：生产由 FastAPI 静态托管 dist/，深层路径刷新不 404。
// meta.title / meta.favicon 由 afterEach 统一写入 <title> 与 <link rel="icon">（ui-contracts §2）。
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: () => import('../pages/OverviewPage.vue'),
      meta: { title: '首页概览', favicon: '/favicon-overview.svg' }
    },
    {
      path: '/attackers',
      name: 'attackers',
      component: () => import('../pages/AttackersPage.vue'),
      meta: { title: '攻击者列表', favicon: '/favicon-attackers.svg' }
    },
    {
      path: '/attackers/:ip',
      name: 'attacker-detail',
      component: () => import('../pages/AttackerDetailPage.vue'),
      meta: { title: '攻击者详情与时间线', favicon: '/favicon-detail.svg' }
    },
    {
      path: '/alerts',
      name: 'alerts',
      component: () => import('../pages/AlertsPage.vue'),
      meta: { title: '告警列表', favicon: '/favicon-alerts.svg' }
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/'
    }
  ]
})

function ensureFavicon(href: string): void {
  let link = document.getElementById('page-favicon') as HTMLLinkElement | null
  if (!link) {
    link = document.createElement('link')
    link.id = 'page-favicon'
    link.rel = 'icon'
    link.type = 'image/svg+xml'
    document.head.appendChild(link)
  }
  if (link.getAttribute('href') !== href) link.setAttribute('href', href)
}

router.afterEach((to) => {
  const baseTitle = typeof to.meta.title === 'string' ? to.meta.title : '控制台'
  // 详情页 title 以 IP 开头（ui-contracts §2）：`<ip> 攻击者详情 · DB Honeypot`
  const title =
    to.name === 'attacker-detail' && typeof to.params.ip === 'string'
      ? `${to.params.ip} 攻击者详情`
      : baseTitle
  document.title = `${title} · DB Honeypot`
  const favicon = typeof to.meta.favicon === 'string' ? to.meta.favicon : '/favicon-overview.svg'
  ensureFavicon(favicon)
  window.scrollTo({ top: 0 })
})

export default router
