/**
 * Every colour, font, size and spacing value in the application.
 *
 * Nothing visual is hard-coded in a component. The tokens below are emitted as
 * CSS custom properties by `themeCss()` and injected once in the root layout,
 * and every stylesheet reads them through `var(--dq-*)`. Change a value here
 * and the whole interface follows.
 *
 * The direction is a hydrographic survey console, not a consumer chat product:
 * deep navy, one teal accent, neutral greys, flat surfaces, real borders
 * instead of shadows.
 */

export const theme = {
  color: {
    // Brand
    navy: '#1F3864',
    navyDeep: '#152845',
    navyTint: '#EAEEF5',
    teal: '#0E6E7A',
    tealDeep: '#0A5560',
    tealTint: '#E4F0F1',

    // Surfaces
    background: '#F6F7F9',
    surface: '#FFFFFF',
    surfaceMuted: '#F0F2F5',
    border: '#DCE0E6',
    borderStrong: '#BFC6D0',

    // Text
    text: '#1A1D21',
    textMuted: '#59616D',
    textFaint: '#868E9A',
    textInverse: '#FFFFFF',

    // Status. Desaturated on purpose: this is a warning system, and a warning
    // that shouts on every message stops being read.
    cautionText: '#7A5200',
    cautionSurface: '#FCF5E6',
    cautionBorder: '#E3D0A4',
    alertText: '#8A2E2E',
    alertSurface: '#F9EDED',
    alertBorder: '#E0BDBD',
    steadyText: '#2F5D3A',
    steadySurface: '#EEF4EF',
    steadyBorder: '#C3D6C9',
  },

  /** Severity is looked up by the backend; this only decides how it looks. */
  severity: {
    high: 'alert',
    medium: 'caution',
    low: 'steady',
    // Deliberately the same treatment as high. An unidentified object carries
    // an unknown risk, and rendering that as neutral would read as "fine".
    unknown: 'caution',
  } as const,

  font: {
    sans: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    mono: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
    size: {
      xs: '11px',
      sm: '12.5px',
      base: '14.5px',
      md: '15.5px',
      lg: '18px',
      xl: '22px',
    },
    weight: { regular: '400', medium: '500', semibold: '600' },
    lineHeight: { tight: '1.35', normal: '1.6', relaxed: '1.7' },
    letterSpacing: { label: '0.06em', normal: '0' },
  },

  space: {
    xxs: '2px',
    xs: '4px',
    sm: '8px',
    md: '12px',
    lg: '16px',
    xl: '24px',
    xxl: '32px',
    xxxl: '48px',
  },

  radius: { sm: '3px', md: '5px', lg: '8px', pill: '999px' },

  layout: {
    columnWidth: '760px',
    panelWidth: '420px',
    headerHeight: '52px',
    composerMaxHeight: '190px',
    /* Dashboard header plus page padding. The chat sizes itself below this. */
    dashboardChrome: '146px',
  },

  motion: {
    fast: '120ms ease',
    panel: '220ms cubic-bezier(0.4, 0, 0.2, 1)',
  },
} as const

export type Theme = typeof theme
export type SeverityTone = (typeof theme.severity)[keyof typeof theme.severity]

/** Flatten the tokens into the `--dq-*` custom properties the stylesheet uses. */
export function themeCss(t: Theme = theme): string {
  const lines: string[] = []
  const add = (name: string, value: string) => lines.push(`  --dq-${name}: ${value};`)

  Object.entries(t.color).forEach(([k, v]) => add(`color-${kebab(k)}`, v))
  Object.entries(t.space).forEach(([k, v]) => add(`space-${k}`, v))
  Object.entries(t.radius).forEach(([k, v]) => add(`radius-${k}`, v))
  Object.entries(t.layout).forEach(([k, v]) => add(`layout-${kebab(k)}`, v))
  Object.entries(t.motion).forEach(([k, v]) => add(`motion-${k}`, v))
  add('font-sans', t.font.sans)
  add('font-mono', t.font.mono)
  Object.entries(t.font.size).forEach(([k, v]) => add(`font-size-${k}`, v))
  Object.entries(t.font.weight).forEach(([k, v]) => add(`font-weight-${k}`, v))
  Object.entries(t.font.lineHeight).forEach(([k, v]) => add(`line-height-${k}`, v))
  Object.entries(t.font.letterSpacing).forEach(([k, v]) => add(`letter-spacing-${k}`, v))

  return `:root {\n${lines.join('\n')}\n}`
}

function kebab(value: string): string {
  return value.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)
}
