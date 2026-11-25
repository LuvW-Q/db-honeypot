#!/usr/bin/env node
/**
 * 令牌抽样（T065）：每页实测 20 处计算样式，与 `src/assets/main.css` 中
 * `:root`（深色）/`html.light`（浅色）的令牌值做反查匹配，命中率写入
 * `evidence/visual/token-sampling.md`。
 *
 * 用法：node verify/token-sampling.mjs --base-url URL --out ../evidence/visual/token-sampling.md
 */
import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { parseArgs } from 'node:util'

const { values } = parseArgs({
  options: {
    'base-url': { type: 'string', default: 'http://127.0.0.1:8000' },
    out: { type: 'string', default: '../evidence/visual/token-sampling.md' },
    json: { type: 'string', default: '../evidence/visual/token-sampling.json' }
  }
})
const baseUrl = values['base-url'].replace(/\/$/, '')
const outPath = resolve(values.out)
const jsonPath = resolve(values.json)

// ---------- 解析 main.css 令牌表 ----------
const css = await readFile(resolve('src/assets/main.css'), 'utf8')
function parseBlock(source, selector) {
  const start = source.indexOf(selector)
  if (start < 0) return {}
  const open = source.indexOf('{', start)
  const close = source.indexOf('}', open)
  const body = source.slice(open + 1, close)
  const map = {}
  for (const match of body.matchAll(/--(c-[a-z-]+):\s*(\d+)\s+(\d+)\s+(\d+);/g)) {
    map[match[1]] = `rgb(${Number(match[2])}, ${Number(match[3])}, ${Number(match[4])})`
  }
  return map
}
const darkTokens = parseBlock(css, ':root {')
const lightTokens = parseBlock(css, 'html.light {')
const byValue = (tokens) => {
  const index = new Map()
  for (const [name, value] of Object.entries(tokens)) {
    if (!index.has(value)) index.set(value, [])
    index.get(value).push(name)
  }
  return index
}
const darkIndex = byValue(darkTokens)
const lightIndex = byValue(lightTokens)

const PAGES = [
  { page: 'overview', route: '/#/' },
  { page: 'attackers', route: '/#/attackers' },
  { page: 'attacker-detail', route: null },
  { page: 'alerts', route: '/#/alerts' }
]
const SELECTORS = [
  'body', 'aside', 'header', 'main', 'footer', 'h1', 'h2',
  '[data-region$="-HEAD"]', '[data-region$="-KPI"]', 'table th'
]
const PROPS = ['backgroundColor', 'color']

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' })
const request = context.request
const response = await request.get(`${baseUrl}/api/attackers?page=1&page_size=1&sort=risk_score&order=desc`)
const detailIp = (await response.json()).items?.[0]?.source_ip

const results = []
for (const theme of ['dark', 'light']) {
  const page = await context.newPage()
  await page.emulateMedia({ colorScheme: theme })
  for (const item of PAGES) {
    const route = item.route ?? `/#/attackers/${detailIp}`
    await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(600)
    const mode = await page.evaluate(() => document.documentElement.dataset.theme)
    const samples = await page.evaluate(
      ({ selectors, props, mode }) => {
        const out = []
        for (const selector of selectors) {
          const el = document.querySelector(selector)
          if (!el) continue
          const style = getComputedStyle(el)
          for (const prop of props) {
            const value = style[prop]
            if (!value || value === 'rgba(0, 0, 0, 0)') continue
            out.push({ selector, property: prop, value })
          }
        }
        return { out, mode, expected: document.documentElement.dataset.theme }
      },
      { selectors: SELECTORS, props: PROPS, mode }
    )
    const index = mode === 'light' ? lightIndex : darkIndex
    const tokens = mode === 'light' ? lightTokens : darkTokens
    const rows = samples.out.map((sample) => {
      // 允许令牌 + 透明度：rgba(r, g, b, a) 的 RGB 部分命中令牌即通过（如 bg-surface/85）
      const rgba = sample.value.match(/^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/)
      const base = rgba ? `rgb(${rgba[1]}, ${rgba[2]}, ${rgba[3]})` : sample.value
      const names = index.get(base) ?? []
      const suffix = rgba ? ` @${Math.round(Number(rgba[4]) * 100)}%` : ''
      return { ...sample, tokens: names.map((n) => `${n}${suffix}`), ok: names.length > 0 }
    })
    results.push({ theme: mode, page: item.page, route, rows })
  }
  await page.close()
}
await browser.close()

const total = results.reduce((n, r) => n + r.rows.length, 0)
const hit = results.reduce((n, r) => n + r.rows.filter((x) => x.ok).length, 0)
const rate = ((hit / total) * 100).toFixed(1)
const now = new Date().toISOString()
const lines = []
lines.push('# 令牌抽样记录（token-sampling.md，T065）')
lines.push('')
lines.push(`- 生成时间：${now}｜目标：${baseUrl}｜口径：\`contracts/ui-contracts.md\` §11 + \`data-model.md\` §5`)
lines.push(`- 方法：每页抽取 10 个元素 × 2 个属性（背景色/文字色）= 20 处计算样式，与 \`src/assets/main.css\` 的 \`--c-*\` 值反查；命中率 **${rate}%（${hit}/${total}）**`)
lines.push('- 判定：命中任意已定义令牌即通过（同值多令牌时全部列出）；未命中视为裸色值违规。')
lines.push('')
lines.push('| 主题 | 页面 | 选择器 | 属性 | 计算值 | 命中令牌 | 判定 |')
lines.push('| --- | --- | --- | --- | --- | --- | --- |')
for (const r of results) {
  for (const row of r.rows) {
    lines.push(`| ${r.theme} | ${r.page} | \`${row.selector}\` | ${row.property} | \`${row.value}\` | ${row.tokens.map((t) => `--${t}`).join(', ') || '—'} | ${row.ok ? 'PASS' : 'FAIL'} |`)
  }
}
lines.push('')
lines.push('## 结论')
lines.push('')
lines.push(`- 深色/浅色两轮共 ${total} 处抽样，命中 ${hit} 处，**命中率 ${rate}%**；未命中 ${total - hit} 处。`)
lines.push('- 未命中项若出现，应回到 `main.css` 补令牌或改组件为令牌类，而不是放行裸色值。')
lines.push('- 与 `token-audit.mjs` 互补：前者查源码字面量，本表查浏览器最终计算值。')
lines.push('')
await mkdir(dirname(outPath), { recursive: true })
await writeFile(outPath, `${lines.join('\n')}\n`, 'utf8')
await mkdir(dirname(jsonPath), { recursive: true })
await writeFile(jsonPath, `${JSON.stringify({ rate: Number(rate), hit, total, results }, null, 2)}\n`, 'utf8')
console.log(`token-sampling -> ${outPath} hit ${hit}/${total} (${rate}%)`)
