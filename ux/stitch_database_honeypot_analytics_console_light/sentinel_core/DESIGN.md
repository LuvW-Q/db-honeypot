---
name: Sentinel Core
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#3f4850'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#707881'
  outline-variant: '#bfc7d2'
  surface-tint: '#006398'
  primary: '#006194'
  on-primary: '#ffffff'
  primary-container: '#007bb9'
  on-primary-container: '#fdfcff'
  inverse-primary: '#93ccff'
  secondary: '#565e74'
  on-secondary: '#ffffff'
  secondary-container: '#dae2fd'
  on-secondary-container: '#5c647a'
  tertiary: '#00685f'
  on-tertiary: '#ffffff'
  tertiary-container: '#008378'
  on-tertiary-container: '#f4fffc'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#cce5ff'
  primary-fixed-dim: '#93ccff'
  on-primary-fixed: '#001d31'
  on-primary-fixed-variant: '#004b73'
  secondary-fixed: '#dae2fd'
  secondary-fixed-dim: '#bec6e0'
  on-secondary-fixed: '#131b2e'
  on-secondary-fixed-variant: '#3f465c'
  tertiary-fixed: '#89f5e7'
  tertiary-fixed-dim: '#6bd8cb'
  on-tertiary-fixed: '#00201d'
  on-tertiary-fixed-variant: '#005049'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  display-lg:
    fontFamily: Hanken Grotesk
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 30px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  title-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.005em
  title-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.01em
  code-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0em
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.06em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 12px
    letterSpacing: 0.08em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.25rem
  margin: 1rem
  margin-desktop: 1.5rem
  space-2xs: 0.125rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
  space-2xl: 2rem
  space-3xl: 3rem
---

## Brand & Style

This design system establishes an ultra-precise, authoritative operational environment tailored for SecOps engineers, incident response leads, and database administrators. Moving away from the cliché dark-mode "hacker" visual vernacular, it introduces an exacting, clinical light workspace engineered for sustained mental focus, immediate threat recognition, and low cognitive fatigue over 12-hour operational shifts.

The aesthetic philosophy balances **Clinical Precision** with **Architectural Modernism**. It prioritizes high legibility, strict structural alignment, subtle tactile cues, and unmistakable visual hierarchy:
- **Authority & Analytical Poise:** Clean white and light slate canvases establish a calm, organized command center backdrop.
- **Immediate Threat Triage:** Deliberate, high-contrast semantic indicators ensure critical telemetry anomalies stand out instantaneously without visual clutter.
- **Utilitarian Elegance:** Fine micro-borders, razor-sharp typography, and dense, structured data grids project industrial-grade reliability.

## Colors

The palette is engineered around high information density and strict chromatic discipline. Neutral surfaces isolate visual noise, allowing signal alerts to convey immediate risk tiers.

### Structural Neutrals
- **Canvas Base:** `#F8FAFC` (Slate 50) — High-clarity, non-reflective workbench surface.
- **Surface Elevation / Containers:** `#FFFFFF` — Pure white card layers providing sharp separation.
- **Hairline Dividers & Outlines:** `#E2E8F0` (Slate 200) — Low-noise structural borders; active borders scale to `#CBD5E1` (Slate 300).
- **Text & Telemetry Primary:** `#0F172A` (Slate 900) — Maximum contrast for critical metrics, attack vectors, and SQL statements.
- **Text Secondary / Metadata:** `#334155` (Slate 700) — High-legibility tier for labels, timestamps, and schemas.
- **Text Tertiary / Muted:** `#64748B` (Slate 500) — De-emphasized data points, table column headers, and breadcrumbs.

### Brand & Interactive Tones
- **Primary Operational Cyan/Sky:** `#0284C7` (Sky 600) — Navigational anchors, interactive states, honeypot node identifiers, and primary actions.
- **Secondary Structural Navy:** `#0F172A` (Slate 900) — Authoritative headers, active tab indicators, and system shell landmarks.
- **Tertiary Teal:** `#0D9488` (Teal 600) — Sensor health, benign traffic telemetry, and synchronized node clusters.

### Threat Severity Hierarchy
- **Low Risk / Safe Traffic:** `#059669` (Emerald 600) — Normal query behavior, synthetic baseline heartbeats.
- **Medium Risk / Anomalous Access:** `#D97706` (Amber 600) — Unauthorized probe, slow port scan, payload mismatch.
- **High Risk / Weaponized Exploit:** `#EA580C` (Orange 600) — Known CVE signature execution, SQL injection pattern detected.
- **Critical / Honeypot Breach:** `#DC2626` (Red 600) — Decoy schema breach, active privilege escalation, exfiltration trigger.

## Typography

The typographic system utilizes a triple-stack hierarchy optimized for forensic clarity, continuous reading, and fast parsing of raw telemetry:

1. **Primary Structural Display (Hanken Grotesk):** Provides architectural precision for dashboard headers, module panels, and high-level analytical KPI counters.
2. **Body & Interface Workhorse (Inter):** High x-height, neutral letterforms, and optimized kerning for enterprise dashboards, complex forms, and multi-row threat tables.
3. **Data & Forensic Layer (JetBrains Mono):** Dedicated to IP addresses, payload dumps, SQL syntaxes, CVE tokens, threat tags, and tabular numerical figures.

All numerical tables must apply font tabular figures (`font-variant-numeric: tabular-nums`) to prevent jitter during real-time telemetry streaming.

## Layout & Spacing

The layout is built upon an adaptive 12-column analytical grid with strict density preservation.

### Responsive Breakpoints & Columns
- **Desktop (≥ 1440px):** 12-column grid, fluid expansion capped at 1920px. Side-by-side honeypot architecture topology and attack timeline panels. 20px gutters, 24px canvas margins.
- **Laptop / Dense SOC Screen (1024px – 1439px):** 12-column compact grid, 16px gutters, 16px margins. Filter sidebars collapse to slide-out drawers.
- **Tablet / Field Investigation (768px – 1023px):** 6-column grid; single-metric cards wrap into dual-column sets.
- **Mobile (≤ 767px):** 4-column single-stack stream. Heavy table columns dynamically truncate into swipeable or expandable list rows.

### Spacing Philosophy
Rhythm follows an exact 4px/8px micro-grid. Spacing within data-dense components (tables, attack vector timelines, log entries) uses `space-xs` and `space-sm` to maintain maximum above-the-fold situational awareness. Generous outer margins (`space-xl` to `space-2xl`) frame individual functional zones, eliminating perceptual clutter.

## Elevation & Depth

This design system avoids dark skeuomorphic drops, instead employing **Tonal Layering** accompanied by **Subtle Micro-Shadows** and **Hairline Outlines**. This keeps the visual hierarchy lightweight, crisp, and clean.

### Elevation Layers
- **Level 0 (Canvas Base):** Background color `#F8FAFC`. Zero elevation, non-interactive ground level.
- **Level 1 (Structural Cards / Panel Containers):** Background `#FFFFFF`, border `1px solid #E2E8F0`, shadow `0 1px 2px 0 rgba(15, 23, 42, 0.04)`.
- **Level 2 (Hovered Cards / Active Telemetry Drawers):** Background `#FFFFFF`, border `1px solid #CBD5E1`, shadow `0 4px 6px -1px rgba(15, 23, 42, 0.07), 0 2px 4px -2px rgba(15, 23, 42, 0.04)`.
- **Level 3 (Modals / Threat Drilldown Overlays / Context Menus):** Background `#FFFFFF`, border `1px solid #94A3B8`, shadow `0 12px 24px -4px rgba(15, 23, 42, 0.12), 0 4px 8px -2px rgba(15, 23, 42, 0.06)`.

### Threat Isolation Lighting
Critical alert badges and honeypot trigger notifications do not use heavy shadows. Instead, they rely on a soft 1px border combined with a 10% opacity tinted background wash (e.g., `#DC2626` text on `#FEF2F2` background with a `#FCA5A5` boundary).

## Shapes

The design system embraces an engineering-grade, structured geometry:
- **Base Geometry (`roundedness: 1`):** Default radius is `0.25rem` (4px). Applied to input fields, buttons, data grid chips, code snippets, and drop-down selectors.
- **Containers & Panels (`rounded-lg`):** Cards, attack graphs, and honeypot topology visualizers use `0.5rem` (8px) for a contemporary, precise frame.
- **Modal Windows & Drawers (`rounded-xl`):** Flyout investigation panels use `0.75rem` (12px).
- **Pill Exceptions:** Rounded pills (`9999px`) are strictly reserved for low-level threat status indicators and node live-heartbeat beacons to signify status rather than interaction.

## Components

### Buttons
- **Primary Action (Execute Query, Deploy Honeypot):** Solid fill `#0284C7`, text `#FFFFFF`, radius `4px`. Hover: `#0369A1`. Focus: `2px` ring `#38BDF8` with `2px` offset.
- **Secondary (Export Logs, Trace Path):** Background `#FFFFFF`, border `1px solid #E2E8F0`, text `#334155`. Hover: Background `#F1F5F9`, border `#CBD5E1`.
- **Critical / Quarantine (Sever Connection, Flush DB Decoy):** Solid fill `#DC2626`, text `#FFFFFF`. Hover: `#B91C1C`. Focus: `2px` ring `#F87171`.

### Threat & Status Badges (Chips)
Badges utilize a tinted-fill formula with uppercase monospace micro-labels:
- **Critical:** Background `#FEF2F2`, border `#FCA5A5`, text `#DC2626`.
- **High:** Background `#FFF7ED`, border `#FDBA74`, text `#EA580C`.
- **Medium:** Background `#FFFBEB`, border `#FDE68A`, text `#D97706`.
- **Low / Healthy:** Background `#ECFDF5`, border `#A7F3D0`, text `#059669`.
- **Neutral / Protocol Identifier (e.g., `TDS`, `MySQL`, `SSH`):** Background `#F1F5F9`, border `#E2E8F0`, text `#475569`.

### Data Tables & Log Streamers
- **Headers:** Background `#F8FAFC`, text `#64748B`, font `JetBrains Mono 11px`, border-bottom `1px solid #E2E8F0`.
- **Rows:** Alternating striping is avoided in favor of crisp horizontal dividers (`1px solid #F1F5F9`). Row hover transitions cleanly to `#F8FAFC`.
- **Active Trap Interaction:** Row highlights with a 3px vertical border strip of `#DC2626` (Red) or `#0284C7` (Sky) on the left margin.

### Input Fields & SQL Playgrounds
- **Inputs:** Crisp white background `#FFFFFF`, text `#0F172A`, placeholder `#94A3B8`, border `1px solid #CBD5E1`, radius `4px`, padding `0.5rem 0.75rem`. Focus: border `#0284C7`, ring `1px solid #0284C7`.
- **Forensic Query Area:** Fixed-width `JetBrains Mono 13px` editor canvas with `#F8FAFC` background, subtle `#E2E8F0` border, and embedded line counters.

### Analytical Cards
- Standard modules feature a unified header bar containing the component title (`title-md`), a live node counter badge, and an action slot (filter or expand). No heavy gradients; boundaries rely on hairline outlines (`#E2E8F0`).

### Checkboxes & Radio Buttons
- Square `16px` with `3px` corner radius. Unchecked: Border `1.5px solid #CBD5E1`, background `#FFFFFF`. Checked: Solid `#0284C7` with sharp white checkmark glyph.