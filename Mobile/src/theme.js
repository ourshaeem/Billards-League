/**
 * The design system, as React Native style values - the same colours and
 * roles as :root in Frontend/src/index.css.
 *
 * Purple and white, with gray as the quiet secondary. Purple marks what
 * you can act on; white carries the screen; gray does the supporting
 * work. Red and amber are for things going wrong, and nothing else.
 *
 * Two themes, one per league:
 *   Billiards (the default): purple, white, gray. The status panel is a
 *     solid block of deep purple.
 *   Ping pong: white, purple, gray. The status panel turns white with a
 *     purple band - a ball on a bright table.
 * A theme only swaps token values; no component asks which league it's
 * drawn in. Components get the current theme from useTheme().
 */

export const palette = {
  purple950: '#1e0b3d',
  purple900: '#2e1065',
  purple800: '#3b1582',
  purple700: '#5b21b6',
  purple600: '#6d28d9',
  purple500: '#7c3aed',
  purple300: '#c4b5fd',
  purple200: '#ddd6fe',
  purple100: '#ede9fe',
  purple50: '#f6f3ff',

  white: '#ffffff',
  gray50: '#f8f8fa',
  gray100: '#efeff3',
  gray200: '#e3e3e9',
  gray300: '#cdcdd6',
  gray500: '#676775',
  gray700: '#3d3d48',
  gray900: '#1b1a22',

  danger: '#b42318',
  dangerPressed: '#912018',
  dangerSoft: '#fef3f2',
  dangerLine: '#fecdca',
  dangerOnDark: '#fda29b',
  warn: '#93370d',
  warnSoft: '#fffaeb',
  warnLine: '#fedf89',

  // Secondary text on the dark toasts and player cards.
  onDarkMuted: '#b4b4c0',
};

const p = palette;

// Instrument Serif carries the league name and the status headline;
// Archivo does everything functional, including score numerals. With
// custom fonts, weight is chosen by family - fontWeight isn't used.
export const fonts = {
  display: 'InstrumentSerif_400Regular',
  regular: 'Archivo_400Regular',
  semibold: 'Archivo_600SemiBold',
  bold: 'Archivo_700Bold',
};

export const type = {
  small: 13.5,
  body: 16,
  large: 19.5,
  title: 25.5,
  display: 35,
  headline: 42,
};

export const radius = { sm: 8, md: 12, lg: 20, pill: 999 };

// Roles shared by both leagues.
const shared = {
  page: p.white,
  surface: p.white,
  line: p.gray200,
  lineSoft: p.gray100,
  text: p.gray900,
  textMuted: p.gray500,
  textStrong: p.purple900,
  accent: p.purple600,
  accentPressed: p.purple700,
  accentStrong: p.purple800,
  accentSoft: p.purple100,
  accentWash: p.purple50,
  onAccent: p.white,
  quietBorder: p.gray300,
  quietText: p.gray700,
  quietPressed: p.gray100,
  inputBorder: p.gray300,
  inputFocus: p.purple500,

  danger: p.danger,
  dangerPressed: p.dangerPressed,
  dangerSoft: p.dangerSoft,
  dangerLine: p.dangerLine,
  warn: p.warn,
  warnSoft: p.warnSoft,
  warnLine: p.warnLine,

  // Toasts and player cards sit on dark gray, readable on any screen.
  toastBg: p.gray900,
  toastText: p.white,
  toastMuted: p.onDarkMuted,

  shadowCard: '0px 1px 2px rgba(30, 11, 61, 0.05), 0px 4px 16px rgba(30, 11, 61, 0.04)',
};

const billiards = {
  ...shared,
  pageGlow: p.purple50,

  // The 4-ball: solid purple with a white spot.
  ballFill: p.purple600,
  ballRing: 'transparent',
  ballSpot: p.white,

  panelBg: p.purple700,
  panelBgPlaying: p.purple900,
  panelBorder: p.purple700,
  panelEdge: 'rgba(255, 255, 255, 0.45)',
  panelEdgeSize: 1,
  panelShadow: '0px 16px 36px rgba(46, 16, 101, 0.26)',
  panelText: p.white,
  panelDim: 'rgba(255, 255, 255, 0.82)',
  panelFaint: 'rgba(255, 255, 255, 0.64)',
  panelLine: 'rgba(255, 255, 255, 0.3)',
  panelFill: 'rgba(255, 255, 255, 0.14)',
  panelFillStrong: 'rgba(255, 255, 255, 0.24)',
  panelIcon: p.purple200,
  panelCtaBg: p.white,
  panelCtaText: p.purple800,
  panelCtaPressed: p.purple50,
  panelErrorEdge: p.dangerOnDark,
  panelInputBorder: 'rgba(255, 255, 255, 0.4)',
};

const pingPong = {
  ...shared,
  pageGlow: p.gray50,

  // The ping pong ball: white, ringed in purple.
  ballFill: p.white,
  ballRing: p.purple500,
  ballSpot: null,

  panelBg: p.white,
  panelBgPlaying: p.purple50,
  panelBorder: p.purple200,
  panelEdge: p.purple600,
  panelEdgeSize: 4,
  panelShadow: '0px 16px 36px rgba(46, 16, 101, 0.1)',
  panelText: p.purple950,
  panelDim: p.gray700,
  panelFaint: p.gray500,
  panelLine: p.gray300,
  panelFill: p.purple50,
  panelFillStrong: p.purple100,
  panelIcon: p.purple500,
  panelCtaBg: p.purple600,
  panelCtaText: p.white,
  panelCtaPressed: p.purple700,
  panelErrorEdge: p.danger,
  panelInputBorder: p.gray300,
};

const THEMES = { billiards, ping_pong: pingPong };

/** The theme for a league; billiards for anything else (including none). */
export function themeFor(league) {
  return THEMES[league] || billiards;
}
