#!/usr/bin/env node
// 部署验收浏览器检查：四页 × 两视口，覆盖控制台错误、失败请求、外网请求、横向溢出、
// 区域重叠、字体、标题/favicon、导航、已读 PATCH 与截图（contracts/deployment-verify.md §4）。
// 用法: node verify/run-check.mjs --base-url URL --out DIR [--only pages] [--skip-write]
import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'

const args = process.argv.slice(2)
function arg(name, fallback) {
  const index = args.indexOf(name)
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback
}
const flag = (name) => args.includes(name)

const baseUrl = arg('--base-url', process.env.BASE_URL || 'http://127.0.0.1:8000')
const outDir = resolve(arg('--out', 'evidence/deploy/run-1'))
const only = arg('--only', '')
const baseHost = new URL(baseUrl).host

const PAGES = [
  {
    page: 'overview', route: '/#/', title: '首页概览 · DB Honeypot', favicon: '/favicon-overview.svg', h1: '首页概览',
    regions: ['OV-HEAD', 'OV-KPI', 'OV-TREND', 'OV-DONUT', 'OV-TOP5']
  },
  {
    page: 'attackers', route: '/#/attackers', title: '攻击者列表 · DB Honeypot', favicon: '/favicon-attackers.svg', h1: '攻击者列表',
    regions: ['AT-HEAD', 'AT-FILTER', 'AT-TABLE', 'AT-PAGER']
  },
  {
    page: 'attacker-detail', route: '', title: '', favicon: '/favicon-detail.svg', h1: '攻击者详情',
    regions: ['AD-HEAD', 'AD-BANNER', 'AD-PROFILE', 'AD-CHAIN', 'AD-SESSIONS', 'AD-TIMELINE', 'AD-FOOTER']
  },
  {
    page: 'alerts', route: '/#/alerts', title: '告警列表 · DB Honeypot', favicon: '/favicon-alerts.svg', h1: '告警列表',
    regions: ['AL-HEAD', 'AL-STATS', 'AL-FILTER', 'AL-CARDS', 'AL-FOOTER']
  }
].filter((item) => !only || only.split(',').includes(item.page))
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 }
]

async function waitForPage(page, expectedH1, timeout = 20000) {
  await page.waitForFunction(
    (text) => {
      const h1 = document.querySelector('h1')
      return Boolean(h1 && h1.textContent && h1.textContent.includes(text))
    },
    expectedH1,
    { timeout }
  )
}

async function firstAttackerIp(request) {
  const response = await request.get(`${baseUrl}/api/attackers?page=1&page_size=1&sort=risk_score&order=desc`)
  if (!response.ok()) return null
  const body = await response.json()
  return body.items?.[0]?.source_ip ?? null
}

function normalizeHtml(html) {
  return html
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '#')
    .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?/g, '#')
    .replace(/\b\d+\b/g, '#')
    .replace(/\s+/g, ' ')
}

async function overlapPairs(page, regions) {
  const rects = await page.evaluate((ids) => ids.map((id) => {
    const el = document.querySelector(`[data-region="${id}"]`)
    if (!el) return { id, missing: true }
    const r = el.getBoundingClientRect()
    return { id, x: r.x, y: r.y, width: r.width, height: r.height }
  }), regions)
  const missing = rects.filter((item) => item.missing).map((item) => item.id)
  const overlaps = []
  for (let i = 0; i < rects.length; i += 1) {
    for (let j = i + 1; j < rects.length; j += 1) {
      const a = rects[i]
      const b = rects[j]
      if (a.missing || b.missing) continue
      const inner = (p, q) => p.x <= q.x && p.y <= q.y && p.x + p.width >= q.x + q.width && p.y + p.height >= q.y + q.height
      if (inner(a, b) || inner(b, a)) continue
      const overlapW = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x))
      const overlapH = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
      if (overlapW * overlapH > 1) overlaps.push({ a: a.id, b: b.id, area: Math.round(overlapW * overlapH) })
    }
  }
  return { missing, overlaps }
}

function readThemeFor(target) {
  return target.evaluate(() => ({
    resolved: document.documentElement.dataset.theme ?? '',
    classes: document.documentElement.className,
    colorScheme: getComputedStyle(document.documentElement).colorScheme,
    background: getComputedStyle(document.body).backgroundColor
  }))
}

const browser = await chromium.launch()
const report = {
  base_url: baseUrl,
  viewports: VIEWPORTS,
  started_at: new Date().toISOString(),
  pages: [],
  interactions: {},
  stable: true,
  result: 'pass'
}

try {
  const request = await browser.newContext().then((context) => context.request)
  const detailIp = await firstAttackerIp(request)
  let patchedAlert = null
  if (!flag('--skip-write')) {
    const list = await request.get(`${baseUrl}/api/alerts?page=1&page_size=1&is_read=false&sort=created_at&order=desc`)
    if (list.ok()) {
      const body = await list.json()
      const alert = body.items?.[0]
      if (alert) {
        const before = await request.get(`${baseUrl}/api/alerts/summary`)
        const beforeBody = before.ok() ? await before.json() : null
        const patch = await request.patch(`${baseUrl}/api/alerts/${alert.alert_id}`, { data: { is_read: true } })
        const after = await request.get(`${baseUrl}/api/alerts/summary`)
        const afterBody = after.ok() ? await after.json() : null
        const restore = await request.patch(`${baseUrl}/api/alerts/${alert.alert_id}`, { data: { is_read: false } })
        patchedAlert = {
          alert_id: alert.alert_id,
          patch_status: patch.status(),
          patch_result_is_read: patch.ok() ? (await patch.json()).is_read : null,
          unread_before: beforeBody?.unread ?? null,
          unread_after: afterBody?.unread ?? null,
          restore_status: restore.status()
        }
        const deltaOk = patchedAlert.unread_before !== null && patchedAlert.unread_after !== null
          ? patchedAlert.unread_after === patchedAlert.unread_before - 1
          : patchedAlert.patch_status === 200
        report.interactions.mark_read_patch = { ...patchedAlert, ok: patch.status() === 200 && deltaOk && restore.status() === 200 }
      }
    }
  }

  for (const viewport of VIEWPORTS) {
    const context = await browser.newContext({
      viewport,
      locale: 'zh-CN',
      timezoneId: 'Asia/Shanghai',
      deviceScaleFactor: 1,
      // 主检查固定深色系统偏好：主题默认「跟随系统」，避免运行时报告依赖跑测机器的外观。
      colorScheme: 'dark'
    })
    const page = await context.newPage()
    for (const item of PAGES) {
      const consoleErrors = []
      const pageErrors = []
      const failedRequests = []
      const httpErrors = []
      const externalRequests = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300))
      })
      page.on('pageerror', (error) => pageErrors.push(String(error).slice(0, 300)))
      page.on('requestfailed', (request_) => failedRequests.push(`${request_.url()} :: ${request_.failure()?.errorText ?? ''}`.slice(0, 300)))
      page.on('response', (response) => {
        const url = response.url()
        if (response.status() >= 400) httpErrors.push(`${response.status()} ${url}`.slice(0, 300))
      })
      page.on('request', (request_) => {
        try {
          const host = new URL(request_.url()).host
          if (host && host !== baseHost) externalRequests.push(request_.url().slice(0, 300))
        } catch {
          /* data: 等非绝对 URL 忽略 */
        }
      })

      let route = item.route
      let expectedTitle = item.title
      let expectedH1 = item.h1
      if (item.page === 'attacker-detail') {
        if (!detailIp) {
          report.pages.push({ route: '#/attackers', page: 'attacker-detail', viewport: `${viewport.width}x${viewport.height}`, skipped: 'no attacker data' })
          continue
        }
        route = `/#/attackers/${detailIp}`
        expectedH1 = detailIp
        expectedTitle = `${detailIp} 攻击者详情 · DB Honeypot`
      }
      await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded' })
      try {
        await waitForPage(page, expectedH1)
      } catch {
        await page.reload({ waitUntil: 'domcontentloaded' })
        await waitForPage(page, expectedH1, 30000)
      }
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(700)

      const title = await page.title()
      const favicon = await page.evaluate(() => {
        const link = document.getElementById('page-favicon') || document.querySelector('link[rel="icon"]')
        return link ? (link.getAttribute('href') || '') : ''
      })
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
      const fonts = await page.evaluate(() => ({
        inter: document.fonts.check('14px "Inter Variable"'),
        jetbrains: document.fonts.check('11px "JetBrains Mono Variable"'),
        symbols: document.fonts.check('20px "Material Symbols Outlined"')
      }))
      const nav = await page.evaluate(() => {
        const links = [...document.querySelectorAll('nav a')].map((el) => ({
          href: el.getAttribute('href'),
          current: el.getAttribute('aria-current'),
          text: (el.textContent || '').trim().slice(0, 40)
        }))
        const disabled = [...document.querySelectorAll('nav [aria-disabled="true"]')].map((el) => (el.textContent || '').trim().slice(0, 40))
        return { links, disabled }
      })
      const regions = await overlapPairs(page, item.regions)
      const skeleton = normalizeHtml(await page.evaluate(() => document.body.outerHTML))
      const screenshot = `screenshots/${item.page}-${viewport.width}x${viewport.height}.png`
      await mkdir(resolve(outDir, 'screenshots'), { recursive: true })
      await page.screenshot({ path: resolve(outDir, screenshot), fullPage: true })

      const record = {
        route: item.page === 'attacker-detail' ? `#/attackers/${detailIp}` : item.route.replace(/^\/#/, '#').replace(/^#/, '#'),
        page: item.page,
        viewport: `${viewport.width}x${viewport.height}`,
        console_errors: consoleErrors,
        page_errors: pageErrors,
        failed_requests: failedRequests,
        http_errors: httpErrors,
        external_requests: externalRequests,
        overflow,
        overlaps: regions.overlaps,
        missing_regions: regions.missing,
        fonts_ready: Object.values(fonts).every(Boolean),
        fonts,
        title,
        favicon,
        nav,
        screenshot,
        skeleton_sha256: createHash('sha256').update(skeleton).digest('hex')
      }
      report.pages.push(record)
      await page.waitForTimeout(50)
    }
    await context.close()
  }

  // ---------- 主题：跟随系统实时切换 + 手动覆盖 + 浅色渲染 ----------
  const themeContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    deviceScaleFactor: 1,
    colorScheme: 'dark'
  })
  await themeContext.addInitScript(() => {
    try {
      localStorage.setItem('dbh-theme', 'system')
    } catch {}
  })
  const themePage = await themeContext.newPage()
  const themeErrors = []
  themePage.on('console', (message) => {
    if (message.type() === 'error') themeErrors.push(message.text().slice(0, 300))
  })
  themePage.on('pageerror', (error) => themeErrors.push(String(error).slice(0, 300)))
  const readTheme = () =>
    themePage.evaluate(() => ({
      resolved: document.documentElement.dataset.theme ?? '',
      classes: document.documentElement.className,
      colorScheme: getComputedStyle(document.documentElement).colorScheme,
      buttonMode: document.querySelector('[data-theme-toggle]')?.getAttribute('data-theme-mode') ?? '',
      buttonLabel: document.querySelector('[data-theme-toggle]')?.getAttribute('aria-label') ?? '',
      stored: (() => {
        try {
          return localStorage.getItem('dbh-theme')
        } catch {
          return null
        }
      })(),
      background: getComputedStyle(document.body).backgroundColor
    }))
  await themePage.goto(`${baseUrl}/#/`, { waitUntil: 'domcontentloaded' })
  await waitForPage(themePage, '首页概览')
  await themePage.waitForTimeout(600)
  const themeSteps = []
  const darkStep = await readTheme()
  themeSteps.push({ step: 'system-dark', ...darkStep })
  // 系统外观切换：模式为 system 时必须实时跟随，无需刷新
  await themePage.emulateMedia({ colorScheme: 'light' })
  await themePage.waitForFunction(() => document.documentElement.dataset.theme === 'light', null, { timeout: 5000 }).catch(() => {})
  // 等待 body 主题过渡（200ms）完成后再取样背景色，避免记录到过渡中间值
  await themePage.waitForTimeout(350)
  const followedStep = await readTheme()
  themeSteps.push({ step: 'system-follows-light', ...followedStep })
  // 手动覆盖：跟随系统 → 浅色 → 深色 → 跟随系统
  await themePage.click('[data-theme-toggle]')
  await themePage.waitForTimeout(250)
  const lightStep = await readTheme()
  themeSteps.push({ step: 'override-light', ...lightStep })
  await themePage.click('[data-theme-toggle]')
  await themePage.waitForTimeout(250)
  const darkOverrideStep = await readTheme()
  themeSteps.push({ step: 'override-dark', ...darkOverrideStep })
  await themePage.click('[data-theme-toggle]')
  await themePage.waitForTimeout(250)
  const systemStep = await readTheme()
  themeSteps.push({ step: 'override-system', ...systemStep })
  await themePage.reload({ waitUntil: 'domcontentloaded' })
  await waitForPage(themePage, '首页概览')
  await themePage.waitForTimeout(400)
  const persistedStep = await readTheme()
  themeSteps.push({ step: 'persisted-after-reload', ...persistedStep })
  const themeOk =
    themeErrors.length === 0 &&
    darkStep.resolved === 'dark' &&
    darkStep.colorScheme === 'dark' &&
    darkStep.stored === 'system' &&
    followedStep.resolved === 'light' &&
    followedStep.colorScheme === 'light' &&
    lightStep.buttonMode === 'light' &&
    lightStep.stored === 'light' &&
    lightStep.resolved === 'light' &&
    darkOverrideStep.buttonMode === 'dark' &&
    darkOverrideStep.stored === 'dark' &&
    darkOverrideStep.resolved === 'dark' &&
    systemStep.buttonMode === 'system' &&
    systemStep.stored === 'system' &&
    persistedStep.resolved === 'light' &&
    persistedStep.stored === 'system' &&
    darkStep.background !== lightStep.background
  report.interactions.theme = { ok: themeOk, steps: themeSteps, errors: themeErrors }
  await themeContext.close()

  // 浅色渲染：四页 × 1440 视口，检查区域/标题/溢出/资源错误并截图（证据 visual/baseline-light）
  const lightContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    deviceScaleFactor: 1,
    colorScheme: 'light'
  })
  await lightContext.addInitScript(() => {
    try {
      localStorage.setItem('dbh-theme', 'system')
    } catch {}
  })
  const lightPage = await lightContext.newPage()
  const lightRecords = []
  for (const item of PAGES) {
    const consoleErrors = []
    const httpErrors = []
    lightPage.removeAllListeners('console')
    lightPage.removeAllListeners('pageerror')
    lightPage.removeAllListeners('response')
    lightPage.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300))
    })
    lightPage.on('pageerror', (error) => consoleErrors.push(String(error).slice(0, 300)))
    lightPage.on('response', (response) => {
      if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`.slice(0, 300))
    })
    let route = item.route
    let expectedH1 = item.h1
    let expectedTitle = item.title
    if (item.page === 'attacker-detail') {
      if (!detailIp) {
        lightRecords.push({ page: 'attacker-detail', skipped: 'no attacker data' })
        continue
      }
      route = `/#/attackers/${detailIp}`
      expectedH1 = detailIp
      expectedTitle = `${detailIp} 攻击者详情 · DB Honeypot`
    }
    await lightPage.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded' })
    await waitForPage(lightPage, expectedH1)
    await lightPage.evaluate(() => document.fonts.ready)
    await lightPage.waitForTimeout(600)
    const themeState = await readThemeFor(lightPage)
    const regions = await overlapPairs(lightPage, item.regions)
    const title = await lightPage.title()
    const overflow = await lightPage.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
    const screenshot = `screenshots/${item.page}-1440x900-light.png`
    await mkdir(resolve(outDir, 'screenshots'), { recursive: true })
    await lightPage.screenshot({ path: resolve(outDir, screenshot), fullPage: true })
    lightRecords.push({
      page: item.page,
      route,
      theme: themeState,
      console_errors: consoleErrors,
      http_errors: httpErrors,
      missing_regions: regions.missing,
      overflow,
      title,
      expected_title: expectedTitle,
      screenshot
    })
  }
  report.light_pages = lightRecords
  await lightContext.close()

  const navPage = report.pages.find((item) => item.page === 'attackers')
  report.interactions.nav = navPage
    ? {
        // 详情入口在攻击者页为 disabled 状态（设计如此）：4 项 = 3 个 <a> + 1 个 disabled 入口。
        ok:
          navPage.nav.links.length + navPage.nav.disabled.length === 4 &&
          navPage.nav.links.some((link) => link.current === 'page'),
        links: navPage.nav.links,
        disabled: navPage.nav.disabled
      }
    : { ok: false, reason: 'attackers page missing' }

  const failures = []
  for (const record of report.pages) {
    if (record.skipped) continue
    if (record.console_errors.length) failures.push(`${record.page}/${record.viewport}: console_errors=${record.console_errors.length}`)
    if (record.page_errors.length) failures.push(`${record.page}/${record.viewport}: page_errors=${record.page_errors.length}`)
    if (record.failed_requests.length) failures.push(`${record.page}/${record.viewport}: failed_requests=${record.failed_requests.length}`)
    if (record.http_errors.length) failures.push(`${record.page}/${record.viewport}: http_errors=${record.http_errors.length}`)
    if (record.external_requests.length) failures.push(`${record.page}/${record.viewport}: external_requests=${record.external_requests.length}`)
    if (record.overflow) failures.push(`${record.page}/${record.viewport}: horizontal overflow`)
    if (record.overlaps.length) failures.push(`${record.page}/${record.viewport}: overlaps=${JSON.stringify(record.overlaps)}`)
    if (record.missing_regions.length) failures.push(`${record.page}/${record.viewport}: missing_regions=${record.missing_regions.join(',')}`)
    if (!record.fonts_ready) failures.push(`${record.page}/${record.viewport}: fonts not ready`)
    if (record.title !== (record.page === 'attacker-detail' ? `${detailIp} 攻击者详情 · DB Honeypot` : PAGES.find((item) => item.page === record.page)?.title)) {
      failures.push(`${record.page}/${record.viewport}: title='${record.title}'`)
    }
    const expectedFavicon = PAGES.find((item) => item.page === record.page)?.favicon
    if (expectedFavicon && !record.favicon.endsWith(expectedFavicon)) failures.push(`${record.page}/${record.viewport}: favicon='${record.favicon}'`)
  }
  if (report.interactions.nav && !report.interactions.nav.ok) failures.push('nav check failed')
  if (!report.interactions.theme?.ok) failures.push(`theme switch failed: ${JSON.stringify(report.interactions.theme?.steps ?? [])}`)
  for (const record of report.light_pages ?? []) {
    if (record.skipped) continue
    if (record.theme?.resolved !== 'light' || record.theme?.colorScheme !== 'light') failures.push(`light/${record.page}: theme=${JSON.stringify(record.theme)}`)
    if (record.console_errors.length) failures.push(`light/${record.page}: console_errors=${record.console_errors.length}`)
    if (record.http_errors.length) failures.push(`light/${record.page}: http_errors=${record.http_errors.length}`)
    if (record.missing_regions.length) failures.push(`light/${record.page}: missing_regions=${record.missing_regions.join(',')}`)
    if (record.overflow) failures.push(`light/${record.page}: horizontal overflow`)
    if (record.title !== record.expected_title) failures.push(`light/${record.page}: title='${record.title}'`)
  }
  if (report.interactions.mark_read_patch && !report.interactions.mark_read_patch.ok) failures.push('mark-read PATCH check failed')

  report.failures = failures
  report.result = failures.length === 0 ? 'pass' : 'fail'
  report.finished_at = new Date().toISOString()
  await mkdir(outDir, { recursive: true })
  await writeFile(resolve(outDir, 'browser.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  console.log(JSON.stringify({ result: report.result, failures, out: resolve(outDir, 'browser.json') }, null, 2))
  if (report.result !== 'pass') process.exitCode = 1
} finally {
  await browser.close()
}
