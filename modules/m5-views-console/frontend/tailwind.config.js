/** Tailwind 令牌唯一来源：颜色/字体/字号/圆角/间距均来自 ux 设计稿 DESIGN.md 与 contracts/ui-contracts.md。
 *  颜色一律映射到 CSS 变量（RGB 三元组），由 `src/assets/main.css` 的 `:root`（深色）与 `html.light`（浅色）定义，
 *  `html.light`/`html.dark` 由 `src/composables/theme.ts` 统一切换（跟随系统 / 手动覆盖），禁止在组件内写裸色值。 */
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        'background': 'rgb(var(--c-background) / <alpha-value>)',
        'surface': 'rgb(var(--c-surface) / <alpha-value>)',
        'surface-dim': 'rgb(var(--c-surface-dim) / <alpha-value>)',
        'surface-bright': 'rgb(var(--c-surface-bright) / <alpha-value>)',
        'surface-container-lowest': 'rgb(var(--c-surface-container-lowest) / <alpha-value>)',
        'surface-container-low': 'rgb(var(--c-surface-container-low) / <alpha-value>)',
        'surface-container': 'rgb(var(--c-surface-container) / <alpha-value>)',
        'surface-container-high': 'rgb(var(--c-surface-container-high) / <alpha-value>)',
        'surface-container-highest': 'rgb(var(--c-surface-container-highest) / <alpha-value>)',
        'surface-variant': 'rgb(var(--c-surface-variant) / <alpha-value>)',
        'on-surface': 'rgb(var(--c-on-surface) / <alpha-value>)',
        'on-surface-variant': 'rgb(var(--c-on-surface-variant) / <alpha-value>)',
        'outline': 'rgb(var(--c-outline) / <alpha-value>)',
        'outline-variant': 'rgb(var(--c-outline-variant) / <alpha-value>)',
        'primary': 'rgb(var(--c-primary) / <alpha-value>)',
        'primary-container': 'rgb(var(--c-primary-container) / <alpha-value>)',
        'on-primary': 'rgb(var(--c-on-primary) / <alpha-value>)',
        'on-primary-container': 'rgb(var(--c-on-primary-container) / <alpha-value>)',
        'secondary': 'rgb(var(--c-secondary) / <alpha-value>)',
        'secondary-container': 'rgb(var(--c-secondary-container) / <alpha-value>)',
        'on-secondary': 'rgb(var(--c-on-secondary) / <alpha-value>)',
        'tertiary': 'rgb(var(--c-tertiary) / <alpha-value>)',
        'tertiary-container': 'rgb(var(--c-tertiary-container) / <alpha-value>)',
        'error': 'rgb(var(--c-error) / <alpha-value>)',
        'error-container': 'rgb(var(--c-error-container) / <alpha-value>)',
        'on-error-container': 'rgb(var(--c-on-error-container) / <alpha-value>)',
        'sev-critical': 'rgb(var(--c-sev-critical) / <alpha-value>)',
        'sev-high': 'rgb(var(--c-sev-high) / <alpha-value>)',
        'sev-medium': 'rgb(var(--c-sev-medium) / <alpha-value>)',
        'sev-low': 'rgb(var(--c-sev-low) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace', 'monospace'],
        // 语义别名：与字号类同名，便于 "font-code-sm text-code-sm" 组合声明字体族。
        'display-hero': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'headline-lg': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'headline-md': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'headline-sm': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'body-lg': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'body-md': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'body-sm': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        'code-lg': ['JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace', 'monospace'],
        'code-md': ['JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace', 'monospace'],
        'code-sm': ['JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace', 'monospace'],
        'label-badge': ['Inter Variable', 'Inter', 'system-ui', 'sans-serif']
      },
      fontSize: {
        'display-hero': ['36px', { lineHeight: '44px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'headline-lg': ['28px', { lineHeight: '36px', letterSpacing: '-0.015em', fontWeight: '600' }],
        'headline-md': ['20px', { lineHeight: '26px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'headline-sm': ['16px', { lineHeight: '22px', fontWeight: '600' }],
        'body-lg': ['15px', { lineHeight: '24px', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'body-sm': ['12px', { lineHeight: '18px', fontWeight: '400' }],
        'code-lg': ['14px', { lineHeight: '22px', fontWeight: '500' }],
        'code-md': ['13px', { lineHeight: '20px', fontWeight: '400' }],
        'code-sm': ['11px', { lineHeight: '16px', letterSpacing: '0.02em', fontWeight: '400' }],
        'label-badge': ['11px', { lineHeight: '14px', letterSpacing: '0.05em', fontWeight: '600' }],
        micro: ['10px', { lineHeight: '14px' }],
        'code-xs': ['11px', { lineHeight: '16px' }],
        'icon-xs': ['14px', { lineHeight: '14px' }],
        'icon-sm': ['16px', { lineHeight: '16px' }],
        'icon-md': ['18px', { lineHeight: '18px' }],
        'icon-lg': ['20px', { lineHeight: '20px' }],
        'icon-2xl': ['28px', { lineHeight: '28px' }],
        'icon-3xl': ['36px', { lineHeight: '36px' }]
      },
      borderRadius: {
        DEFAULT: '4px',
        lg: '8px',
        xl: '12px',
        full: '9999px'
      },
      spacing: {
        14: '3.5rem',
        30: '7.5rem',
        38: '9.5rem',
        40: '10rem',
        48: '12rem',
        60: '15rem',
        72: '18rem',
        90: '22.5rem',
        gutter: '1rem',
        'gutter-lg': '1.5rem',
        margin: '1.25rem',
        'margin-lg': '2rem',
        'space-xs': '0.25rem',
        'space-sm': '0.5rem',
        'space-md': '0.75rem',
        'space-lg': '1rem',
        'space-xl': '1.5rem'
      },
      boxShadow: {
        panel: 'var(--shadow-panel)',
        glow: 'var(--shadow-glow)',
        'glow-error': 'var(--shadow-glow-error)',
        'glow-primary': 'var(--shadow-glow-primary)'
      },
      zIndex: {
        toast: '60'
      },
      gridTemplateColumns: {
        profile: 'auto 1fr'
      }
    }
  },
  plugins: []
}
