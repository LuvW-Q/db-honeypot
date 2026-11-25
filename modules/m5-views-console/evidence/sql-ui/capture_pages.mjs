// 抓取四页 DOM 显示值（M5 sql-ui 证据，只读）。
//
// 前置：API 服务已在 BASE_URL 运行并托管 frontend/dist；Playwright 浏览器可用
// （若本机缓存版本与 @playwright/test 不匹配，用 PLAYWRIGHT_CHROMIUM 指定可执行文件）。
//
// 复现（仓库根）：
//   cd modules/m5-views-console/frontend
//   BASE_URL=http://127.0.0.1:8000 \
//   PLAYWRIGHT_CHROMIUM="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-mac-arm64/chrome-headless-shell" \
//     node --input-type=module -e "$(cat ../evidence/sql-ui/capture_pages.mjs)" \
//     > ../evidence/sql-ui/page-dom-capture.json
//
// 输出：四页的标题、data-region 文本、KPI/统计卡数值、首行表格文本与 /api/* 请求状态。
import { chromium } from '@playwright/test'

const base = process.env.BASE_URL || 'http://127.0.0.1:8000'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM
const browser = await chromium.launch(executablePath ? { executablePath } : {})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const apiCalls = []
page.on('response', (response) => {
  if (response.url().includes('/api/')) {
    apiCalls.push({ status: response.status(), url: response.url().replace(base, '') })
  }
})
const out = {
  base_url: base,
  captured_at: new Date().toISOString(),
  tool: 'playwright chromium (headless)',
  pages: {}
}

async function settle(hash, waitFor) {
  apiCalls.length = 0
  await page.goto(`${base}/#${hash}`, { waitUntil: 'networkidle' })
  await page.waitForSelector(waitFor, { timeout: 20000 })
  await page.waitForTimeout(1200)
}

try {
  // 1. 首页概览：KPI 卡
  await settle('/', '[data-region="OV-KPI"]')
  out.pages.overview = {
    title: await page.title(),
    url: page.url(),
    kpis: await page.$$eval('[data-region="OV-KPI"] > *', (els) =>
      els.map((el) => ({
        label: el.querySelector('span.text-body-sm')?.innerText.trim() ?? '',
        value: el.querySelector('.text-display-hero')?.innerText.trim() ?? '',
        text: el.innerText.replace(/\s+/g, ' ').trim()
      }))
    ),
    api_calls: [...apiCalls]
  }

  // 2. 告警列表：顶部统计卡（当前 dist 可能存在请求参数问题，一并记录）
  await settle('/alerts', '[data-region="AL-STATS"]')
  out.pages.alerts = {
    title: await page.title(),
    url: page.url(),
    stats: await page.$$eval('[data-region="AL-STATS"] > div', (els) =>
      els.map((el) => ({
        label: el.querySelector('span.font-code-sm')?.innerText.trim() ?? '',
        value: el.querySelector('.text-headline-lg')?.innerText.trim() ?? '',
        text: el.innerText.replace(/\s+/g, ' ').trim()
      }))
    ),
    error_banner: (await page.locator('[role="alert"]').allInnerTexts()).map((text) =>
      text.replace(/\s+/g, ' ').trim()
    ),
    api_calls: [...apiCalls]
  }

  // 3. 攻击者列表：头部统计与首行
  await settle('/attackers', '[data-region="AT-HEAD"]')
  out.pages.attackers = {
    title: await page.title(),
    url: page.url(),
    head: (await page.locator('[data-region="AT-HEAD"]').innerText()).replace(/\s+/g, ' ').trim(),
    summary_line: (await page.locator('text=/筛选结果/').first().innerText()).replace(/\s+/g, ' ').trim(),
    first_rows: await page.$$eval('[data-region="AT-TABLE"] tbody tr', (rows) =>
      rows.slice(0, 3).map((row) => row.innerText.replace(/\s+/g, ' ').trim())
    ),
    api_calls: [...apiCalls]
  }

  // 4. 攻击者详情：取列表第一名的 IP
  const listResponse = await page.request.get(`${base}/api/attackers?page_size=1`)
  const listBody = await listResponse.json()
  const ip = listBody.items?.[0]?.source_ip ?? '198.51.100.17'
  await settle(`/attackers/${ip}`, '[data-region="AD-HEAD"]')
  out.pages.attacker_detail = {
    ip,
    title: await page.title(),
    url: page.url(),
    head: (await page.locator('[data-region="AD-HEAD"]').innerText()).replace(/\s+/g, ' ').trim(),
    profile: (await page.locator('[data-region="AD-PROFILE"]').innerText()).replace(/\s+/g, ' ').trim(),
    api_calls: [...apiCalls]
  }
} finally {
  await browser.close()
}

console.log(JSON.stringify(out, null, 2))
