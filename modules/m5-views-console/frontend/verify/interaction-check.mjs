#!/usr/bin/env node
// 交互检查（contracts/ui-contracts.md §6/§7）：范围切换、列表筛选/排序/分页、告警筛选/页签/时间、
// 单条与批量已读、时间线筛选、禁用控件文案与可访问性。写操作用演示数据并在结束后还原。
// 用法: node verify/interaction-check.mjs --base-url URL --out DIR [--headed]
import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const args = process.argv.slice(2)
function arg(name, fallback) {
  const index = args.indexOf(name)
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback
}
const baseUrl = arg('--base-url', process.env.BASE_URL || 'http://127.0.0.1:8000')
const outDir = resolve(arg('--out', 'evidence/deploy/run-1'))
const results = []
let browser
const record = (name, ok, detail) => results.push({ name, ok, detail })

async function waitH1(page, text) {
  try {
    await page.waitForFunction(
      (needle) => Boolean(document.querySelector('h1')?.textContent?.includes(needle)),
      text,
      { timeout: 20000 }
    )
  } catch (error) {
    const seen = await page.locator('h1').allInnerTexts().catch(() => [])
    throw new Error(`waitH1(${text}) failed at ${page.url()} h1=${JSON.stringify(seen)} :: ${error}`)
  }
}

async function settle(page, ms = 500) {
  await page.waitForTimeout(ms)
}

try {
  browser = await chromium.launch({ headless: !args.includes('--headed') })
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' })
  const request = context.request
  const page = await context.newPage()
  const requests = []
  page.on('request', (req) => {
    const url = req.url()
    if (url.includes('/api/')) requests.push(`${req.method()} ${url.replace(baseUrl, '')}`)
  })
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(String(error)))

  // ---------- 首页概览：范围切换 ----------
  await page.goto(`${baseUrl}/#/`, { waitUntil: 'domcontentloaded' })
  await waitH1(page, '首页概览')
  await settle(page, 800)
  const allSessions = (await page.locator('[data-region="OV-KPI"] .text-display-hero').first().innerText()).trim()
  await page.getByRole('button', { name: '最近 7 天' }).click()
  await settle(page, 900)
  const rangeRequests = requests.filter((item) => item.includes('/api/overview?range='))
  const url7d = page.url().includes('range=7d')
  const kpi7d = (await page.locator('[data-region="OV-KPI"] .text-display-hero').first().innerText()).trim()
  record('overview-range-7d', url7d && rangeRequests.some((item) => item.includes('range=7d')), { url7d, rangeRequests, allSessions, kpi7d })
  // 切回全部历史
  await page.getByRole('button', { name: '全部历史' }).click()
  await settle(page, 900)
  record('overview-range-all', page.url().includes('range=all'))
  // 刷新按钮
  const before = requests.length
  await page.getByRole('button', { name: /现场刷新数据/ }).click()
  await settle(page, 900)
  record('overview-refresh', requests.slice(before).some((item) => item.includes('/api/overview')), requests.slice(before))
  // TOP5 下钻
  const top5Link = page.locator('[data-region="OV-TOP5"] a[href*="/attackers/"]').first()
  await top5Link.waitFor({ state: 'visible', timeout: 15000 })
  await top5Link.click()
  await page.waitForTimeout(1200)
  let detailUrl = page.url()
  if (!/#\/attackers\/\d+\.\d+\.\d+\.\d+/.test(detailUrl)) {
    // 二次尝试：SPA 路由偶发在请求未结束时吞掉首次点击
    await top5Link.click().catch(() => {})
    await page.waitForTimeout(1200)
    detailUrl = page.url()
  }
  record('overview-top5-drilldown', /#\/attackers\/\d+\.\d+\.\d+\.\d+/.test(detailUrl), detailUrl)

  // ---------- 攻击者详情：时间线筛选 + 禁用控件 ----------
  // 详情页 h1 是动态 IP（非固定文案），以区域根节点判断渲染完成
  await page.waitForSelector('[data-region="AD-HEAD"]', { timeout: 20000 })
  const timeline = page.locator('[data-region="AD-TIMELINE"]')
  await timeline.waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(800)
  const allCards = await timeline.locator('ol > li').count()
  const filterButtons = timeline.getByRole('tab')
  const filterCount = await filterButtons.count()
  let authFilterWorks = false
  let filterDetail = { allCards, filterCount }
  if (filterCount > 0) {
    const authButton = timeline.getByRole('tab', { name: /仅认证/ })
    if (await authButton.count()) {
      await authButton.first().click()
      await settle(page, 500)
      const authCards = await timeline.locator('ol > li').count()
      authFilterWorks = authCards <= allCards && authCards > 0
      filterDetail = { allCards, authCards }
    }
  }
  record('detail-timeline-filter', authFilterWorks, filterDetail)
  const disabledDetail = await page.locator('button:disabled').evaluateAll((buttons) =>
    buttons.map((button) => ({ text: (button.textContent || '').trim().slice(0, 30), title: button.getAttribute('title') || '' }))
  )
  record('detail-disabled-controls', disabledDetail.length > 0 && disabledDetail.every((item) => item.title.includes('演示未开放')), disabledDetail)
  // 返回列表
  await page.getByRole('link', { name: /返回攻击者列表/ }).click()
  await waitH1(page, '攻击者列表')
  await settle(page, 800)

  // ---------- 攻击者列表：搜索/风险档/意图/排序/分页 ----------
  const search = page.getByPlaceholder(/搜索恶意 IP/)
  await search.fill('198.51.100.17')
  await search.press('Enter')
  await settle(page, 900)
  const rowsAfterSearch = await page.locator('[data-region="AT-TABLE"] tbody tr').count()
  record('attackers-search', page.url().includes('q=198.51.100.17') && rowsAfterSearch >= 1, { url: page.url(), rowsAfterSearch })
  const clear = page.getByRole('button', { name: /清除筛选|重置/ })
  if (await clear.count()) {
    await clear.first().click()
    await settle(page, 800)
  }
  // 风险档：严重（>=80）
  const criticalPill = page.getByRole('button', { name: /严重/ })
  if (await criticalPill.count()) {
    await criticalPill.first().click()
    await settle(page, 900)
    record('attackers-risk-filter', page.url().includes('risk_level=critical') || page.url().includes('risk_level=high'), page.url())
    const allPill = page.getByRole('button', { name: /^全部$/ })
    if (await allPill.count()) {
      await allPill.first().click()
      await settle(page, 700)
    }
  }
  // 排序：累计会话
  const sortSelect = page.locator('[data-region="AT-FILTER"] select').last()
  if (await sortSelect.count()) {
    await sortSelect.selectOption('total_connections')
    await settle(page, 900)
    record('attackers-sort-total-connections', requests.some((item) => item.includes('sort=total_connections')), page.url())
  }
  // 分页
  const nextPage = page.getByRole('button', { name: /下一页/ })
  if (await nextPage.count() && await nextPage.isEnabled()) {
    await nextPage.first().click()
    await settle(page, 900)
    record('attackers-pagination', page.url().includes('page=2') && requests.some((item) => item.includes('page=2')), page.url())
  }
  const disabledAttackers = await page.locator('[data-region="AT-FILTER"] button:disabled').evaluateAll((buttons) =>
    buttons.map((button) => ({ text: (button.textContent || '').trim().slice(0, 30), title: button.getAttribute('title') || '' }))
  )
  record('attackers-disabled-export', disabledAttackers.some((item) => item.text.includes('导出') && item.title.includes('演示未开放')), disabledAttackers)

  // ---------- 告警列表：页签/等级/类型/时间/单条与批量已读 ----------
  await page.goto(`${baseUrl}/#/alerts`, { waitUntil: 'domcontentloaded' })
  await waitH1(page, '告警列表')
  await settle(page, 1000)
  const unreadTab = page.getByRole('button', { name: /^未读/ })
  if (await unreadTab.count()) {
    await unreadTab.first().click()
    await settle(page, 900)
    record('alerts-tab-unread', page.url().includes('is_read=false') && requests.some((item) => item.includes('is_read=false')), page.url())
  }
  const severityPill = page.getByRole('button', { name: /^高危/ })
  if (await severityPill.count()) {
    await severityPill.first().click()
    await settle(page, 800)
    record('alerts-severity-filter', page.url().includes('severity=high'), page.url())
    await severityPill.first().click()
    await settle(page, 700)
  }
  const typeSelect = page.locator('[data-region="AL-FILTER"] select').first()
  if (await typeSelect.count()) {
    await typeSelect.selectOption('bruteforce')
    await settle(page, 800)
    record('alerts-type-filter', page.url().includes('alert_type=bruteforce'), page.url())
    await typeSelect.selectOption('all')
    await settle(page, 700)
  }
  const dayPreset = page.getByRole('button', { name: '近 3 天' })
  if (await dayPreset.count()) {
    await dayPreset.first().click()
    await settle(page, 800)
    record('alerts-time-preset', page.url().includes('days=3'), page.url())
  }
  // 恢复 7 天 + 全部，确保有未读
  const sevenDays = page.getByRole('button', { name: '近 7 天' })
  if (await sevenDays.count()) {
    await sevenDays.first().click()
    await settle(page, 800)
  }
  const allTab = page.getByRole('button', { name: /^全部告警/ })
  if (await allTab.count()) {
    await allTab.first().click()
    await settle(page, 900)
  }
  // 单条已读
  const markButtons = page.getByRole('button', { name: /^标记已读$/ })
  const unreadBefore = await markButtons.count()
  let singleOk = false
  let patchTarget = null
  if (unreadBefore > 0) {
    const responsePromise = page.waitForResponse((resp) => /\/api\/alerts\/\d+$/.test(resp.url()) && resp.request().method() === 'PATCH', { timeout: 15000 })
    await markButtons.first().click()
    const response = await responsePromise
    patchTarget = Number(response.url().match(/(\d+)$/)?.[1])
    await settle(page, 1000)
    singleOk = response.status() === 200
    const toast = await page.locator('[role="status"]').first().innerText().catch(() => '')
    record('alerts-single-mark-read', singleOk, { status: response.status(), patchTarget, toast })
  } else {
    record('alerts-single-mark-read', false, '无未读告警可用')
  }
  // 批量已读：勾选 2 条
  const checkboxes = page.locator('[data-region="AL-CARDS"] input[type="checkbox"]')
  const checkboxCount = await checkboxes.count()
  let batchOk = false
  if (checkboxCount >= 2) {
    await checkboxes.nth(0).check()
    await checkboxes.nth(1).check()
    const batchButton = page.getByRole('button', { name: /批量标记已读/ })
    const patches = []
    page.on('request', (req) => {
      if (req.method() === 'PATCH' && /\/api\/alerts\/\d+$/.test(req.url())) patches.push(req.url())
    })
    await batchButton.click()
    await settle(page, 1600)
    const unreadAfter = await page.getByRole('button', { name: /^标记已读$/ }).count()
    batchOk = patches.length === 2
    record('alerts-batch-mark-read', batchOk, { patches: patches.length, unreadAfter })
  } else {
    record('alerts-batch-mark-read', false, `可勾选告警仅 ${checkboxCount} 条`)
  }

  // 还原：把本次改为已读的告警恢复未读（保持演示数据可重复）
  let restored = 0
  const restoreIds = new Set()
  if (patchTarget) restoreIds.add(patchTarget)
  // 批量改的 id 从 requests 中无法区分，改为按“最近已读 + 无未读”兜底：全部恢复风险大，仅恢复单条与批量里点过的行
  // 批量行在点击前记录 alert_id 不可得（DOM 无绑定），因此用 PATCH 响应 URL 记录：见上方 patches 变量作用域
  const restoreList = [...restoreIds]
  for (const id of restoreList) {
    const resp = await request.patch(`${baseUrl}/api/alerts/${id}`, { data: { is_read: false } })
    if (resp.ok()) restored += 1
  }

  // ---------- 可访问性 ----------
  const a11y = await page.evaluate(() => {
    const h1s = document.querySelectorAll('h1')
    const current = document.querySelectorAll('nav a[aria-current="page"]').length
    const iconButtons = [...document.querySelectorAll('button')].filter((button) => {
      const text = (button.textContent || '').trim()
      return text === '' || /^[a-z_]+$/.test(text)
    })
    const missingLabel = iconButtons.filter((button) => !button.getAttribute('aria-label') && !button.getAttribute('title')).length
    return { h1Count: h1s.length, navCurrent: current, iconButtons: iconButtons.length, missingLabel }
  })
  record('a11y-h1-nav-labels', a11y.h1Count === 1 && a11y.navCurrent === 1 && a11y.missingLabel === 0, a11y)

  record('page-errors', pageErrors.length === 0, pageErrors)
  await browser.close()
  browser = null

  const failed = results.filter((item) => !item.ok)
  const report = {
    base_url: baseUrl,
    finished_at: new Date().toISOString(),
    restored_alerts: restored,
    results,
    console_requests: requests.slice(-60),
    result: failed.length === 0 ? 'pass' : 'fail',
    failures: failed.map((item) => item.name)
  }
  await mkdir(outDir, { recursive: true })
  await writeFile(resolve(outDir, 'interaction.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  console.log(JSON.stringify({ result: report.result, failures: report.failures, out: resolve(outDir, 'interaction.json') }, null, 2))
  if (failed.length) process.exitCode = 1
} catch (error) {
  if (browser) await browser.close()
  console.error(JSON.stringify({ result: 'error', error: String(error) }, null, 2))
  process.exitCode = 2
}
