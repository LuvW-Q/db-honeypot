---
name: Cyber Threat Defense Terminal
colors:
  surface: '#051424'
  surface-dim: '#051424'
  surface-bright: '#2c3a4c'
  surface-container-lowest: '#010f1f'
  surface-container-low: '#0d1c2d'
  surface-container: '#122131'
  surface-container-high: '#1c2b3c'
  surface-container-highest: '#273647'
  on-surface: '#d4e4fa'
  on-surface-variant: '#bcc9cd'
  inverse-surface: '#d4e4fa'
  inverse-on-surface: '#233143'
  outline: '#869397'
  outline-variant: '#3d494c'
  surface-tint: '#4cd7f6'
  primary: '#4cd7f6'
  on-primary: '#003640'
  primary-container: '#06b6d4'
  on-primary-container: '#00424f'
  inverse-primary: '#00687a'
  secondary: '#4edea3'
  on-secondary: '#003824'
  secondary-container: '#00a572'
  on-secondary-container: '#00311f'
  tertiary: '#c0c1ff'
  on-tertiary: '#1000a9'
  tertiary-container: '#9a9dff'
  on-tertiary-container: '#211cb4'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#acedff'
  primary-fixed-dim: '#4cd7f6'
  on-primary-fixed: '#001f26'
  on-primary-fixed-variant: '#004e5c'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#e1e0ff'
  tertiary-fixed-dim: '#c0c1ff'
  on-tertiary-fixed: '#07006c'
  on-tertiary-fixed-variant: '#2f2ebe'
  background: '#051424'
  on-background: '#d4e4fa'
  surface-variant: '#273647'
typography:
  display-hero:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 26px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  code-lg:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 22px
    letterSpacing: '0'
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: '0'
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-badge:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-lg: 1.5rem
  margin: 1.25rem
  margin-lg: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style
The design system serves mission-critical cybersecurity operations, threat intelligence reporting, and defense review contexts. It balances the tactical visual density of a security command center with the instant legibility demanded by high-stakes thesis defense and project demonstrations under high-lumen projection environments.

The visual style unites **Technical Precision Minimalism** with controlled **Cyber Glassmorphism**:
- **Atmosphere:** Deep obsidian and slate depths that eliminate visual fatigue during sustained audit analysis while ensuring projection-ready contrast ratios exceeding WCAG AAA standards.
- **Tone:** Authoritative, vigilant, forensic, and rigorously structured. Every accent color maps strictly to security telemetry states, eliminating decorative noise.
- **Presentation Readiness:** Clear typographic hierarchy, sharp metric cards, high-contrast semantic risk badges, and structural glow treatments that highlight critical attack vectors without visual blooming.

## Colors
The palette is built upon a calibrated dark foundation specifically engineered to prevent washed-out visuals on lecture hall and conference room projectors.

### Core Canvas & Surfaces
- **Canvas Base:** `#0B0F19` (Obsidian Void — primary viewport background)
- **Surface Elevation 1 (Cards/Panels):** `#111827` (Deep Charcoal Slate)
- **Surface Elevation 2 (Raised Modals/Popovers):** `#1F2937` (Layered Slate)
- **Surface Stroke / Division:** `#374151` with focus/active edge tinting at `#1E293B`

### Brand & Operational Telemetry
- **Primary Interactive / Active Stream (`#06B6D4` - Cyber Cyan):** Used for primary actions, active telemetry nodes, connected database honeypot sessions, and focus indicators.
- **Secondary / Benign Verification (`#10B981` - Emerald Shield):** Used for authorized authentications, safe protocol handshakes, and healthy cluster states.
- **Tertiary / Forensic Trace (`#6366F1` - Deep Indigo):** Used for session isolation, synthetic sandbox markers, and system metadata tags.

### Semantic Attack Severity System
- **Low Risk:** `#10B981` (Emerald) — Background: `rgba(16, 185, 129, 0.12)`, Border: `rgba(16, 185, 129, 0.35)`
- **Medium Risk:** `#F59E0B` (Amber) — Background: `rgba(245, 158, 11, 0.12)`, Border: `rgba(245, 158, 11, 0.35)`
- **High Risk:** `#F97316` (Orange) — Background: `rgba(249, 115, 22, 0.15)`, Border: `rgba(249, 115, 22, 0.45)`
- **Critical Exploit / Breach:** `#EF4444` (Crimson Pulse) — Background: `rgba(239, 68, 68, 0.18)`, Border: `rgba(239, 68, 68, 0.55)`

### Text & Projection Legibility
- **Text High Emphasis:** `#F8FAFC` (Pure Titanium, 98% contrast against surfaces)
- **Text Medium Emphasis:** `#CBD5E1` (Cool Silver, primary body and table metadata)
- **Text Low / Disabled:** `#64748B` (Muted Slate, column headers and inactive cues)

## Typography
The system enforces a dual-type engine:
1. **Interface & Analytics (`Inter`):** Handles UI chrome, high-level dashboards, executive metric counters, and qualitative threat descriptions. Tightened tracking on headlines maintains optical density without crowding.
2. **Forensic & Data Trace (`JetBrains Mono`):** Dedicated exclusively to telemetry artifacts: SQL payloads, attacker IPv4/IPv6 coordinates, Session UUIDs, MAC traces, timestamps (ISO-8601), and semantic risk tags.

Monospace elements utilize proportional line height to maintain exact vertical grid alignment across log comparison tables and split-payload diff views.

## Layout & Spacing
The layout adheres to a 12-column dynamic fluid grid system engineered for tactical monitoring consoles (1920x1080 and 1440x900 standard projection resolutions) while reflowing gracefully to tablets and laptops:

- **Desktop (1440px+):** 12-column grid, `margin-lg` (32px), `gutter-lg` (24px). Sidebar collapsed or fixed at 240px; threat timeline and telemetry inspect panes split into a balanced 8:4 or 7:5 structural ratio.
- **Laptop / Projection Standard (1024px – 1439px):** 12-column grid, `margin` (20px), `gutter` (16px). Secondary analytics collapse into tabbed cards.
- **Mobile / Tactical Tablet (<1024px):** Single to 4-column reflow, `margin` (16px), `gutter` (12px). Log inspectors convert to full-bleed modal drawers.

Padding within analytical containers scales strictly on the `space-*` scale to maintain high information density without visual crowding.

## Elevation & Depth
Depth is produced through disciplined tonal layering combined with deliberate cyber luminescence rather than heavy drop shadows:

- **Surface Layer 0 (`#0B0F19`):** Outer application substrate, dark canvas.
- **Surface Layer 1 (`#111827`):** Primary card modules, data grid canvas, audit tables. Border: 1px solid `#1F2937`.
- **Surface Layer 2 (`#1E293B`):** Raised interactive dropdowns, inspect flyouts, modal overlays.
- **Active Tactical Glow:**
  - Standard focus / active monitoring: `0 0 0 1px #06B6D4, 0 0 12px rgba(6, 182, 212, 0.22)`
  - Critical threat capture: `0 0 0 1px #EF4444, 0 0 16px rgba(239, 68, 68, 0.28)`
- **Glass Panel Treatment:** Headers, fixed navigation strips, and filter bars utilize background blur (`backdrop-filter: blur(12px)`) with `rgba(17, 24, 39, 0.85)` surface fill, maintaining legibility when scrolling extensive event lists beneath.

## Shapes
The system utilizes a compact, precise shape profile (Level 1 - Soft) to reinforce technical and architectural rigor:
- **Standard Controls & Badges (`rounded`):** 4px border radius for tags, inputs, metric chips, and terminal windows.
- **Containers & Panels (`rounded-lg`):** 8px border radius for major analytical cards, modals, and forensic split-views.
- **Pill Badges (`rounded-xl`):** Reserved exclusively for live session connection status markers (e.g., `● LISTENING`) and honeypot active pulse indicators.

## Components

### Buttons & Action Bars
- **Primary Cyber Action:** Background `#06B6D4`, text `#0B0F19`, font-weight 600, border radius 4px. Hover: `#22D3EE` with `0 0 12px rgba(6, 182, 212, 0.4)`.
- **Destructive / Containment Action (e.g., "Isolate Session"):** Background `rgba(239, 68, 68, 0.15)`, text `#EF4444`, border `1px solid #EF4444`. Hover: Background `#EF4444`, text `#FFFFFF`.
- **Tactical Secondary:** Background `#1F2937`, text `#F8FAFC`, border `1px solid #374151`.

### Semantic Risk Badges & Intent Tags
- **Micro Badges:** Monospace `label-badge` styling, uppercase, 4px corner radius, padding `2px 8px`.
  - `CRITICAL`: Text `#EF4444`, Border `rgba(239, 68, 68, 0.4)`, Background `rgba(239, 68, 68, 0.12)`.
  - `HIGH`: Text `#F97316`, Border `rgba(249, 115, 22, 0.4)`, Background `rgba(249, 115, 22, 0.12)`.
  - `MEDIUM`: Text `#F59E0B`, Border `rgba(245, 158, 11, 0.4)`, Background `rgba(245, 158, 11, 0.12)`.
  - `LOW`: Text `#10B981`, Border `rgba(16, 185, 129, 0.4)`, Background `rgba(16, 185, 129, 0.12)`.
- **Attack Intent Tags (e.g., `SQLi: Blind Timing`, `Privilege Escalation`, `Schema Enum`):** Monospace font, muted slate fill `rgba(99, 102, 241, 0.15)`, border `1px solid rgba(99, 102, 241, 0.35)`, text `#A5B4FC`.

### Audit-Ready Desensitized Badges
- For public presentation or thesis defense mode: Masked IPs (e.g., `192.168.***.42`) and obfuscated hashes display with a secondary lock glyph, text `#94A3B8`, and background `rgba(51, 65, 85, 0.5)`.

### Attack Log & Telemetry Data Tables
- **Header:** Sticky, background `#0F172A`, text `#64748B`, uppercase tracking 0.05em, height 36px.
- **Rows:** Border-bottom `1px solid #1E293B`, alternating striping with `rgba(255, 255, 255, 0.01)`. Row height 44px for compact telemetry scan.
- **Hover State:** Background `rgba(6, 182, 212, 0.05)` with an instant left border accent (`2px solid #06B6D4`).

### Input Fields & SQL Playback Consoles
- **Filters & Search Inputs:** Background `#0B0F19`, border `1px solid #374151`, text `#F8FAFC`, placeholder `#64748B`. Focused: Border `#06B6D4`, glow `0 0 8px rgba(6, 182, 212, 0.25)`.
- **SQL Replay Console:** Monospace `code-md` typography, deep inset canvas `#060911`, syntax highlighted (`Keywords: #06B6D4`, `Tables: #A5B4FC`, `Payload Injections: #F87171`, `Comments: #64748B`).

### Checkboxes & Toggle Controls
- Custom squared controls (4px radius). Checked state displays `#06B6D4` fill with obsidian checkmark. Critical alert triggers use `#EF4444` fill.