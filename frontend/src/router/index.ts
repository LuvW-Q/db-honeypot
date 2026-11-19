import { createRouter, createWebHashHistory } from 'vue-router'

// 四页范围固定（FR-061）：概览、攻击者列表、攻击者详情、告警列表。
// 使用 hash 模式：生产环境由 FastAPI StaticFiles(html=True) 托管 dist/，不会对
// /attackers/xxx 这类深层路径做 SPA 回退；hash 模式可保证刷新与直接访问不会 404。
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: () => import('../views/OverviewView.vue'),
      meta: { title: '概览' }
    },
    {
      path: '/attackers',
      name: 'attackers',
      component: () => import('../views/AttackersView.vue'),
      meta: { title: '攻击者列表' }
    },
    {
      path: '/attackers/:ip',
      name: 'attacker-detail',
      component: () => import('../views/AttackerDetailView.vue'),
      meta: { title: '攻击者详情' }
    },
    {
      path: '/alerts',
      name: 'alerts',
      component: () => import('../views/AlertsView.vue'),
      meta: { title: '告警列表' }
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/'
    }
  ]
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · 数据库蜜罐分析控制台` : '数据库蜜罐分析控制台'
})

export default router
