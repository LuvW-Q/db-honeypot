#!/usr/bin/env node
// 基线截图采集：固定种子后对四页 × 两视口截图，产出 PNG 与 metadata JSON。
// 用法: node verify/capture-baseline.mjs [--base-url URL] [--out DIR] [--only page,page] [--theme dark|light]
// 约定：文件名 {page}-{viewport}.png（深色）/ {page}-{viewport}-light.png（浅色放进同目录时）；只读接口，不修改数据。
import { chromium } from '@playwright/test'
import { mkdir, writeFile, stat } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'

const args = process.argv.slice(2)
function arg(name, fallback) {
  const index = args.indexOf(name)
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback
}

const baseUrl = arg('--base-url', process.env.BASE_URL || 'http://127.0.0.1:8000')
const outDir = resolve(arg('--out', 'evidence/visual/baseline'))
const only = arg('--only', '')
const theme = arg('--theme', 'dark')
if (theme !== 'dark' && theme !== 'light') {
  console.error('--theme 只支持 dark / light')
  process.exit(2)
}
const PAGES = [
  { page: 'overview', route: '#/', h1: '首页概览' },
  { page: 'attackers', route: '#/attackers', h1: '攻击者列表' },
  { page: 'attacker-detail', route: '', h1: '攻击者详情' }, // 由列表首行 IP 动态构造
  { page: 'alerts', route: '#/alerts', h1: '告警列表' }
].filter((item) => !only || only.split(',').includes(item.page))
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 }
]

async function firstAttackerIp(page) {
  await page.goto(`${baseUrl}/#/attackers`, { waitUntil: 'networkidle' })
  const href = await page.locator('a[href*="#/attackers/"]').first().getAttribute('href').catch(() => null)
  if (!href) return null
  return href.split('#/attackers/')[1].split('?')[0]
}

const browser = await chromium.launch()
const records = []
const startedAt = new Date().toISOString()
try {
  for (const viewport of VIEWPORTS) {
    const context = await browser.newContext({
      viewport,
      locale: 'zh-CN',
      timezoneId: 'Asia/Shanghai',
      deviceScaleFactor: 1,
      colorScheme: theme
    })
    // 手动指定主题时写 localStorage（覆盖系统的唯一入口），避免依赖系统偏好。
    await context.addInitScript((value) => {
      try {
        localStorage.setItem('dbh-theme', value)
      } catch {}
    }, theme)
    const page = await context.newPage()
    const detailIp = await firstAttackerIp(page)
    for (const item of PAGES) {
      let route = item.route
      let expectedH1 = item.h1
      if (item.page === 'attacker-detail') {
        if (!detailIp) continue
        route = `#/attackers/${detailIp}`
        expectedH1 = detailIp
      }
      await page.goto(`${baseUrl}/${route}`, { waitUntil: 'domcontentloaded' })
      try {
        await page.waitForFunction(
          (text) => {
            const h1 = document.querySelector('h1')
            return Boolean(h1 && h1.textContent && h1.textContent.includes(text))
          },
          expectedH1,
          { timeout: 20000 }
        )
      } catch {
        await page.reload({ waitUntil: 'domcontentloaded' })
        await page.waitForFunction(
          (text) => {
            const h1 = document.querySelector('h1')
            return Boolean(h1 && h1.textContent && h1.textContent.includes(text))
          },
          expectedH1,
          { timeout: 30000 }
        )
      }
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(700)
      const file = theme === 'light' ? `${item.page}-${viewport.width}x${viewport.height}-light.png` : `${item.page}-${viewport.width}x${viewport.height}.png`
      await mkdir(outDir, { recursive: true })
      await page.screenshot({ path: resolve(outDir, file), fullPage: true })
      const title = await page.title()
      const themeState = await page.evaluate(() => ({
        resolved: document.documentElement.dataset.theme ?? '',
        classes: document.documentElement.className,
        colorScheme: getComputedStyle(document.documentElement).colorScheme,
        background: getComputedStyle(document.body).backgroundColor
      }))
      const fonts = await page.evaluate(() => ({
        inter: document.fonts.check('14px "Inter Variable"'),
        jetbrains: document.fonts.check('11px "JetBrains Mono Variable"'),
        symbols: document.fonts.check('20px "Material Symbols Outlined"')
      }))
      records.push({
        page: item.page,
        route: route.startsWith('#') ? route : `#/${route.replace(/^#\//, '')}`,
        source_ip: item.page === 'attacker-detail' ? detailIp : undefined,
        viewport: `${viewport.width}x${viewport.height}`,
        file,
        title,
        fonts_ready: Object.values(fonts).every(Boolean),
        fonts
      })
      console.log(`captured ${file}`)
    }
    await context.close()
  }
  const pkg = JSON.parse(await (await import('node:fs/promises')).readFile(new URL('../package.json', import.meta.url), 'utf8'))
  let distMtime = null
  try {
    distMtime = (await stat(new URL('../dist/index.html', import.meta.url))).mtime.toISOString()
  } catch {
    distMtime = null
  }
  const metadata = {
    generated_at: new Date().toISOString(),
    started_at: startedAt,
    base_url: baseUrl,
    viewports: VIEWPORTS.map((item) => `${item.width}x${item.height}`),
    seed_command: 'reset_demo --yes && gen_demo_data --sessions 200 --events 2400 && import_samples --group demo_basic',
    build: { name: pkg.name, version: pkg.version, dist_index_mtime: distMtime },
    timezone: 'Asia/Shanghai (UTC+8)',
    screenshots: records
  }
  await mkdir(outDir, { recursive: true })
  await writeFile(resolve(outDir, 'metadata.json'), `${JSON.stringify(metadata, null, 2)}\n`, 'utf8')
  console.log(`metadata -> ${resolve(outDir, 'metadata.json')}`)
} finally {
  await browser.close()
}
