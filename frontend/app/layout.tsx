import type { Metadata } from 'next'

import { copy } from '../config/copy'
import { theme, themeCss } from '../config/theme'
import './globals.css'

export const metadata: Metadata = {
  title: `${copy.app.name} — ${copy.app.subtitle}`,
  description: copy.empty.body,
}

/**
 * The design tokens are injected once, here, as CSS custom properties. Every
 * stylesheet reads them, so config/theme.ts is the only place a colour, size or
 * spacing value is written down.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <style dangerouslySetInnerHTML={{ __html: themeCss(theme) }} />
        {children}
      </body>
    </html>
  )
}
