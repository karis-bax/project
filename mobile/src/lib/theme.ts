/** Shared visual tokens. Dark-first: this app is used in shops and car parks. */

export const theme = {
  bg: '#0C0F15',
  surface: '#151922',
  surfaceAlt: '#1C212B',
  line: '#252B37',
  ink: '#E7EAF0',
  inkMuted: '#A3ACBB',
  inkFaint: '#727D8E',
  accent: '#3FD09A',
  accentSoft: '#0F3227',
  warn: '#E0A54F',
  warnSoft: '#2E2312',
  danger: '#F0736A',
  radius: 12,
  space: (n: number) => n * 4,
} as const
