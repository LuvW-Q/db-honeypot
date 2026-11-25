#!/usr/bin/env node
// 令牌审计：class/style 只能使用 tailwind 配置中的令牌，CSS/内联样式不得出现裸颜色字面量。
// 用法: node verify/token-audit.mjs [--out DIR] [--json]
import { readFile, readdir, writeFile, mkdir } from 'node:fs/promises'
import { extname, join, resolve, relative } from 'node:path'
import config from '../tailwind.config.js'

const args = process.argv.slice(2)
function arg(name, fallback) {
  const index = args.indexOf(name)
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback
}
const outDir = resolve(arg('--out', 'evidence/deploy/run-1'))
const root = resolve('.')

const theme = config.theme?.extend ?? {}
const colors = new Set(Object.keys(theme.colors ?? {}))
const fontSizes = new Set(Object.keys(theme.fontSize ?? {}))
const fonts = new Set([...Object.keys(theme.fontFamily ?? {}), 'sans', 'mono'])
const spacing = new Set([...Object.keys(theme.spacing ?? {}), '0', '0.5', '1', '1.5', '2', '2.5', '3', '3.5', '4', '5', '6', '7', '8', '9', '10', '11', '12', '14', '16', '20', '24', '28', '32', '36', '40', '44', '48', '52', '56', '60', '64', '72', '80', '96', 'px', 'auto'])
const radii = new Set([...Object.keys(theme.borderRadius ?? {}), 'none', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', 'full'])
const specialColors = new Set(['transparent', 'current', 'inherit', 'white', 'black'])
const allowedColorValues = new Set(Object.values(theme.colors ?? {}).map((value) => String(value).toLowerCase()))

const VARIANTS = /^(?:(?:sm|md|lg|xl|2xl|hover|focus|active|focus-visible|disabled|dark|group-hover|group-focus|peer-checked|peer-focus|aria-\[[^\]]+\]|data-\[[^\]]+\]):)*/
const CLASS_PREFIXES = [
  ['bg', (suffix) => colors.has(suffix) || specialColors.has(suffix)],
  ['text', (suffix) => fontSizes.has(suffix) || colors.has(suffix) || specialColors.has(suffix) || ['center', 'left', 'right', 'justify', 'start', 'end', 'ellipsis', 'clip', 'wrap', 'nowrap', 'balance', 'pretty', 'wrap'].includes(suffix)],
  ['border', (suffix) => {
    const axis = /^[trblxy]-(.+)$/.exec(suffix)
    if (axis) {
      const rest = axis[1]
      return rest === '' || colors.has(rest) || specialColors.has(rest) || /^\d+$/.test(rest)
    }
    if (suffix === '' || colors.has(suffix) || specialColors.has(suffix)) return true
    if (/^(?:\d|b|t|l|r|x|y|dashed|dotted|solid|none|double|collapse|separate)$/.test(suffix)) return true
    return radii.has(suffix)
  }],
  ['ring', (suffix) => colors.has(suffix) || /^\d$/.test(suffix) || suffix === 'inset'],
  ['fill', (suffix) => colors.has(suffix) || suffix === 'none' || specialColors.has(suffix)],
  ['stroke', (suffix) => colors.has(suffix) || suffix === 'none' || specialColors.has(suffix)],
  ['font', (suffix) => fonts.has(suffix) || ['thin', 'light', 'normal', 'medium', 'semibold', 'bold', 'extrabold', 'black'].includes(suffix)],
  ['p', (suffix) => spacing.has(suffix)],
  ['m', (suffix) => spacing.has(suffix)],
  ['gap', (suffix) => spacing.has(suffix)],
  ['space', (suffix) => spacing.has(suffix)],
  ['rounded', (suffix) => radii.has(suffix) || suffix === '']
]

function classify(token) {
  const withoutVariants = token.replace(VARIANTS, '')
  if (!withoutVariants) return null
  const arbitrary = /-\[[^\]]+\]/.test(withoutVariants)
  const base = withoutVariants.replace(/^-/, '')
  if (arbitrary) return { kind: 'arbitrary', base }
  for (const [prefix, allowed] of CLASS_PREFIXES) {
    let suffix = null
    if (base === prefix) suffix = ''
    else if (base.startsWith(`${prefix}-`)) suffix = base.slice(prefix.length + 1)
    if (suffix === null) continue
    if (prefix === 'p' || prefix === 'm' || prefix === 'gap' || prefix === 'space') {
      const axis = /^(p|m|gap|space)-([trblxy])-/.exec(base)
      if (axis) suffix = base.slice(axis[0].length)
    }
    suffix = suffix.split('/')[0]
    if (allowed(suffix)) return null
    return { kind: 'token', base, prefix }
  }
  if (/(?:^|:)(?:w|h|min-w|min-h|max-w|max-h|z)-\[/.test(withoutVariants)) {
    return { kind: 'arbitrary', base }
  }
  return null
}

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name.startsWith('.')) continue
    const path = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...(await walk(path)))
    else if (['.vue', '.ts', '.css', '.html'].includes(extname(entry.name))) files.push(path)
  }
  return files
}

// 主题令牌对账：深色 :root 与浅色 html.light 必须定义同一组颜色变量（缺失会导致切换后掉回浏览器默认色）。
const requiredThemeTokens = [...colors].map((name) => `--c-${name}`).filter((name) => name !== '--c-undefined')
const REQUIRED_CHART_TOKENS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-track', '--chart-tooltip-bg']
let themeReport = { dark_tokens: 0, light_tokens: 0, missing: [] }
try {
  const css = await readFile(resolve('src/assets/main.css'), 'utf8')
  const darkBlock = /:root\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  const lightBlock = /html\.light\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  const declared = (block) => new Set([...block.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]))
  const darkTokens = declared(darkBlock)
  const lightTokens = declared(lightBlock)
  themeReport = { dark_tokens: darkTokens.size, light_tokens: lightTokens.size, missing: [] }
  if (!darkBlock) themeReport.missing.push(':root')
  if (!lightBlock) themeReport.missing.push('html.light')
  for (const token of [...requiredThemeTokens, ...REQUIRED_CHART_TOKENS]) {
    if (darkBlock && !darkTokens.has(token)) themeReport.missing.push(`dark:${token}`)
    if (lightBlock && !lightTokens.has(token)) themeReport.missing.push(`light:${token}`)
  }
  for (const token of themeReport.missing) {
    violations.push({ file: 'src/assets/main.css', line: 0, match: token, reason: '主题令牌缺失：深/浅两套必须定义同一组变量' })
  }
} catch (error) {
  violations.push({ file: 'src/assets/main.css', line: 0, match: String(error), reason: '无法读取主题令牌文件' })
}

const files = await walk(resolve('src'))
const violations = []
const usage = {}
let checkedLines = 0

for (const file of files) {
  const rel = relative(root, file)
  const text = await readFile(file, 'utf8')
  const lines = text.split('\n')
  lines.forEach((line, index) => {
    checkedLines += 1
    if (extname(file) === '.css') {
      const noComments = line.replace(/\/\*.*?\*\//g, '')
      // 令牌定义行（--token: ...）是主题变量源头，允许 rgb()/rgba() 字面量；
      // 其余 CSS 只允许 rgb(var(--c-*)) 这类变量引用，裸颜色一律拦截。
      const isTokenDefinition = /^\s*--[\w-]+\s*:/.test(noComments)
      const withoutVarRgb = noComments.replace(/rgba?\(\s*var\(--[\w-]+\)[^)]*\)/g, 'VAR_COLOR')
      const colorMatch = isTokenDefinition ? null : /#[0-9a-fA-F]{3,8}\b|(?:rgb|hsl)a?\(/.exec(withoutVarRgb)
      if (colorMatch) {
        violations.push({ file: rel, line: index + 1, match: colorMatch[0], reason: 'CSS 中出现裸颜色字面量，必须使用令牌变量/配置色' })
      }
    }
    if (extname(file) === '.html' || extname(file) === '.vue') {
      const styleMatch = /style="([^"]*)"/.exec(line)
      if (styleMatch) {
        const colorMatch = /#[0-9a-fA-F]{3,8}\b|(?:rgb|hsl)a?\(/.exec(styleMatch[1])
        if (colorMatch && !allowedColorValues.has(colorMatch[0].toLowerCase())) {
          violations.push({ file: rel, line: index + 1, match: colorMatch[0], reason: '内联 style 中出现非令牌颜色' })
        }
      }
      const hexes = line.match(/#[0-9a-fA-F]{6}\b/g) ?? []
      for (const hex of hexes) {
        if (!allowedColorValues.has(hex.toLowerCase())) {
          // SVG 渐变/滤镜允许引用配置色；其它颜色必须来自配置。
          violations.push({ file: rel, line: index + 1, match: hex, reason: '颜色字面量不在 tailwind 配置令牌中' })
        }
      }
    }
    const classAttrs = [...line.matchAll(/(?:class|:class)="([^"]*)"/g)].map((match) => match[1])
    for (const attr of classAttrs) {
      const tokens = attr.match(/[a-z0-9:/[\]_.,-]+/gi) ?? []
      for (const token of tokens) {
        const verdict = classify(token)
        if (!verdict) continue
        usage[verdict.base] = (usage[verdict.base] ?? 0) + 1
        violations.push({
          file: rel,
          line: index + 1,
          match: token,
          reason: verdict.kind === 'arbitrary' ? '禁止任意值语法，必须使用配置令牌' : `令牌 ${verdict.base} 不在 tailwind 配置允许集合`
        })
      }
    }
  })
}

const result = {
  checked_files: files.length,
  checked_lines: checkedLines,
  token_usage: Object.fromEntries(Object.entries(usage).sort((a, b) => b[1] - a[1]).slice(0, 80)),
  themes: themeReport,
  violations,
  result: violations.length === 0 ? 'pass' : 'fail'
}
await mkdir(outDir, { recursive: true })
await writeFile(resolve(outDir, 'token-audit.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
console.log(JSON.stringify({ result: result.result, violations: violations.length, checked_files: files.length, out: resolve(outDir, 'token-audit.json') }, null, 2))
if (violations.length) {
  for (const item of violations.slice(0, 20)) console.error(`${item.file}:${item.line} ${item.match} :: ${item.reason}`)
  process.exitCode = 1
}
