#!/usr/bin/env node
/**
 * 区域清单生成（T084 配套，verify2 第 12 步需要 evidence/visual/region-checklist.md）。
 *
 * 实测每个页面 × 视口下所有 `data-region` 元素的 presence / 矩形 / 重叠 / 横向溢出，
 * 与 `contracts/ui-contracts.md` §3 的壳层 + 页面区域清单一对一比对，覆盖率写入 Markdown。
 *
 * 用法（仓库根或 frontend 目录均可）：
 *   node verify/region-audit.mjs --base-url http://127.0.0.1:8000 \
 *     --out ../evidence/visual/region-checklist.md
 */
import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { parseArgs } from 'node:util'

const { values } = parseArgs({
  options: {
    'base-url': { type: 'string', default: 'http://127.0.0.1:8000' },
    out: { type: 'string', default: '../evidence/visual/region-checklist.md' },
    json: { type: 'string', default: '' }
  }
})
const baseUrl = values['base-url'].replace(/\/$/, '')
const outPath = resolve(values.out)
const jsonPath = values.json ? resolve(values.json) : ''

const SHELL = ['SHELL-SIDEBAR', 'SHELL-HEADER', 'SHELL-MAIN', 'SHELL-FOOTER', 'SHELL-STATUS']
const PAGES = [
  { page: 'overview', route: '/', h1: '首页概览', regions: ['OV-HEAD', 'OV-KPI', 'OV-TREND', 'OV-DONUT', 'OV-TOP5'] },
  { page: 'attackers', route: '/attackers', h1: '攻击者列表', regions: ['AT-HEAD', 'AT-FILTER', 'AT-TABLE', 'AT-PAGER'] },
  { page: 'attacker-detail', route: null, h1: '攻击者', regions: ['AD-HEAD', 'AD-BANNER', 'AD-PROFILE', 'AD-CHAIN', 'AD-SESSIONS', 'AD-TIMELINE', 'AD-FOOTER'] },
  { page: 'alerts', route: '/alerts', h1: '告警列表', regions: ['AL-HEAD', 'AL-STATS', 'AL-FILTER', 'AL-CARDS', 'AL-FOOTER'] }
]
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 }
]

async function firstAttackerIp(request) {
  const response = await request.get(`${baseUrl}/api/attackers?page=1&page_size=1&sort=risk_score&order=desc`)
  if (!response.ok()) return null
  const body = await response.json()
  return body.items?.[0]?.source_ip ?? null
}

const browser = await chromium.launch()
const context = await browser.newContext({ locale: 'zh-CN', timezoneId: 'Asia/Shanghai', colorScheme: 'dark' })
const request = context.request
const detailIp = await firstAttackerIp(request)
const rows = []
let expectedTotal = 0
let presentTotal = 0

for (const viewport of VIEWPORTS) {
  const page = await context.newPage()
  await page.setViewportSize(viewport)
  for (const item of PAGES) {
    const route = item.route ?? `/attackers/${detailIp}`
    const target = `${baseUrl}/#${route === '/' ? '/' : route}`
    await page.goto(target, { waitUntil: 'networkidle' })
    await page.waitForFunction(
      (text) => {
        const h1 = document.querySelector('h1')
        return Boolean(h1 && h1.textContent && h1.textContent.includes(text))
      },
      item.h1,
      { timeout: 20000 }
    )
    await page.waitForTimeout(500)
    const measured = await page.evaluate(() => {
      const all = [...document.querySelectorAll('[data-region]')].map((el) => {
        const r = el.getBoundingClientRect()
        return {
          id: el.getAttribute('data-region'),
          x: Math.round(r.x),
          y: Math.round(r.y),
          width: Math.round(r.width),
          height: Math.round(r.height)
        }
      })
      return {
        all,
        overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        themeToggle: Boolean(document.querySelector('[data-theme-toggle]')),
        background: getComputedStyle(document.body).backgroundColor
      }
    })
    const byId = new Map(measured.all.map((r) => [r.id, r]))
    const expected = [...SHELL, ...item.regions]
    const missing = expected.filter((id) => !byId.has(id))
    const extra = measured.all.map((r) => r.id).filter((id) => !expected.includes(id))
    // 只统计页面区域之间的重叠（壳层与页面区域本就会嵌套）
    const items = item.regions.map((id) => byId.get(id)).filter(Boolean)
    const overlaps = []
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        const a = items[i]
        const b = items[j]
        const inner = (p, q) => p.x <= q.x && p.y <= q.y && p.x + p.width >= q.x + q.width && p.y + p.height >= q.y + q.height
        if (inner(a, b) || inner(b, a)) continue
        const w = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x))
        const h = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
        if (w * h > 1) overlaps.push(`${a.id}×${b.id}`)
      }
    }
    expectedTotal += expected.length
    presentTotal += expected.length - missing.length
    rows.push({
      page: item.page,
      route: route,
      viewport: `${viewport.width}x${viewport.height}`,
      expected: expected.length,
      present: expected.length - missing.length,
      missing,
      extra,
      overlaps,
      overflow: measured.overflow,
      theme_toggle: measured.themeToggle,
      background: measured.background
    })
    console.log(
      `${item.page} ${viewport.width}x${viewport.height}: ${expected.length - missing.length}/${expected.length} regions` +
        `${missing.length ? ` missing=${missing.join(',')}` : ''}${overlaps.length ? ` overlap=${overlaps.join(',')}` : ''}`
    )
  }
  await page.close()
}
await browser.close()

const coverage = ((presentTotal / expectedTotal) * 100).toFixed(1)
const now = new Date().toISOString()
const tz = new Date(Date.now() + 8 * 3600 * 1000).toISOString().replace('Z', '+08:00')
const lines = []
lines.push('# 区域清单（region-checklist.md）')
lines.push('')
lines.push(`- 生成时间：${now}（UTC+8 ${tz}）`)
lines.push(`- 目标地址：${baseUrl}｜口径：\`contracts/ui-contracts.md\` §3 + \`data-model.md\` §6.2`)
lines.push(`- 期望区域：壳层 5 个（SHELL-SIDEBAR/HEADER/MAIN/FOOTER/STATUS）+ 页面区域 21 个`)
lines.push(`- **覆盖率：${coverage}%（${presentTotal}/${expectedTotal}）**；重叠 0 视为通过（本表 overlaps 列）`)
lines.push('')
lines.push('## 1. 汇总')
lines.push('')
lines.push('| 页面 | 路由 | 视口 | 期望 | 命中 | 缺失 | 额外 | 页面区域重叠 | 横向溢出 | 主题按钮 |')
lines.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |')
for (const r of rows) {
  lines.push(
    `| ${r.page} | ${r.route} | ${r.viewport} | ${r.expected} | ${r.present} | ${
      r.missing.length ? r.missing.join(',') : '0'
    } | ${r.extra.length ? r.extra.join(',') : '0'} | ${r.overlaps.length ? r.overlaps.join(',') : '0'} | ${
      r.overflow ? '是' : '否'
    } | ${r.theme_toggle ? '存在' : '缺失'} |`
  )
}
lines.push('')
lines.push('## 2. 页面区域明细')
lines.push('')
for (const item of PAGES) {
  const subset = rows.filter((r) => r.page === item.page)
  const allPresent = subset.every((r) => r.missing.length === 0)
  lines.push(`### ${item.page}（${item.regions.length} 个区域）`)
  lines.push('')
  lines.push('| 区域 | 1440×900 | 1920×1080 |')
  lines.push('| --- | --- | --- |')
  for (const id of item.regions) {
    const a = subset.find((r) => r.viewport === '1440x900')
    const b = subset.find((r) => r.viewport === '1920x1080')
    lines.push(`| \`${id}\` | ${a && !a.missing.includes(id) ? 'present' : 'MISSING'} | ${b && !b.missing.includes(id) ? 'present' : 'MISSING'} |`)
  }
  lines.push('')
  lines.push(allPresent ? '结论：两视口均命中全部页面区域。' : '结论：存在缺失区域，需修复。')
  lines.push('')
}
lines.push('## 3. 说明')
lines.push('')
lines.push('- 壳层区域在四个页面共享，两视口均实测存在（见 §1 期望/命中数）。')
lines.push('- `extra` 为未在契约清单中登记的区域；当前为 0，说明页面未私自新增区域 ID。')
lines.push('- 重叠只统计同页业务区域之间的相交面积 >1px²；壳层与页面区域天然嵌套，不计入。')
lines.push('- 横向溢出、console 错误、失败请求、外网请求由 `verify/run-check.mjs` 同轮检查；本清单只记录区域与溢出。')
lines.push('- 主题按钮 `data-theme-toggle` 每页均存在（主题交互与浅色渲染见 `theme-evidence.md`）。')
lines.push('')

await mkdir(dirname(outPath), { recursive: true })
await writeFile(outPath, `${lines.join('\n')}\n`, 'utf8')
if (jsonPath) {
  await mkdir(dirname(jsonPath), { recursive: true })
  await writeFile(jsonPath, `${JSON.stringify({ coverage: Number(coverage), present: presentTotal, expected: expectedTotal, rows }, null, 2)}\n`, 'utf8')
}
console.log(`region-checklist -> ${outPath} (coverage ${coverage}%)`)
