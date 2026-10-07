/**
 * The design system, as React Native style values - the same colours and
 * roles as :root in Frontend/src/index.css.
 *
 * Out of a league (signing in, choosing one) the app is its own purple and
 * white, with gray as the quiet secondary. Inside one, it wears that
 * league's colours - CCNY's lavender and black, John Jay's navy and blue,
 * Brooklyn's maroon and gold - built from the league's primary_color and
 * secondary_color by leagueColors.js, the same file the web app uses:
 *   - the status panel is the primary colour, with the secondary as the
 *     band along its top and its main button;
 *   - on the screen, the primary marks what you can act on.
 * Contrast is worked out there, not assumed. Red and amber are for things
 * going wrong, and nothing else, in every league.
 *
 * Each comes dark too (Profile > Appearance, or the phone's own setting):
 * the same roles on a near-black screen. A theme only swaps token values;
 * no component asks which league or scheme it's drawn in. Components get
 * the current theme from useTheme().
 */
import { alpha, leagueColors, mix } from './leagueColors';

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

// Roles shared by both leagues, by day.
const shared = {
  scheme: 'light',
  // The phone's status bar text: dark on a light screen.
  statusBar: 'dark',

  page: p.white,
  surface: p.white,
  line: p.gray200,
  lineSoft: p.gray100,
  fillSoft: p.gray100,
  text: p.gray900,
  textMuted: p.gray500,
  textStrong: p.purple900,
  accent: p.purple600,
  accentPressed: p.purple700,
  // Purple as text - wins, links, your own name. Its own token because
  // in the dark it has to be lighter, where a pressed button gets darker.
  accentText: p.purple700,
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
  // A red button's fill; white text sits on it.
  dangerFill: p.danger,
  dangerPressed: p.dangerPressed,
  dangerSoft: p.dangerSoft,
  dangerLine: p.dangerLine,
  warn: p.warn,
  warnSoft: p.warnSoft,
  warnLine: p.warnLine,

  // Toasts sit on dark gray, readable on any screen.
  toastBg: p.gray900,
  toastText: p.white,
  toastMuted: p.onDarkMuted,

  shadowCard: '0px 1px 2px rgba(30, 11, 61, 0.05), 0px 4px 16px rgba(30, 11, 61, 0.04)',
  shadowRaised: '0px 1px 3px rgba(30, 11, 61, 0.12)',
};

// The same roles at night: a near-black screen with a touch of purple in
// it, text at 7:1 or better against its card, and purple a step lighter
// wherever it is text. The values match the web app's dark tokens.
const sharedDark = {
  ...shared,
  scheme: 'dark',
  statusBar: 'light',

  page: '#110e17',
  surface: '#1a1622',
  line: '#2d2838',
  lineSoft: '#231f2c',
  fillSoft: '#27222f',
  text: '#ecebf3',
  textMuted: '#a5a2b5',
  textStrong: p.purple200,
  accent: p.purple500,
  accentPressed: p.purple600,
  accentText: p.purple300,
  accentStrong: p.purple100,
  accentSoft: '#2e2249',
  accentWash: '#211a31',
  quietBorder: '#3f394c',
  quietText: '#d5d3df',
  quietPressed: '#27222f',
  inputBorder: '#3f394c',
  inputFocus: '#a78bfa',

  danger: '#f97066',
  dangerFill: '#d92d20',
  dangerPressed: p.danger,
  dangerSoft: '#2c1517',
  dangerLine: '#7a271a',
  warn: '#fec84b',
  warnSoft: '#2b2112',
  warnLine: '#7a5214',

  // Lifted off the dark screen instead of sinking into it.
  toastBg: '#2c2839',
  toastMuted: '#bcb9cb',

  shadowCard: '0px 1px 2px rgba(0, 0, 0, 0.4), 0px 4px 16px rgba(0, 0, 0, 0.25)',
  shadowRaised: '0px 1px 3px rgba(0, 0, 0, 0.5)',
};

// The app's own look, outside any league: the 8-ball ringed in purple, and
// a purple status panel, the same by day and night.
const billiardsTable = {
  // The 8-ball (Wordmark.js): ballSpot says to draw it, ballFill is its ring.
  ballFill: p.purple600,
  ballRing: 'transparent',
  ballSpot: p.white,

  panelBg: p.purple700,
  panelBgPlaying: p.purple900,
  panelBorder: p.purple700,
  panelEdge: 'rgba(255, 255, 255, 0.45)',
  panelEdgeSize: 1,
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

const billiardsDark = {
  ...sharedDark,
  ...billiardsTable,
  pageGlow: '#261c40',
  panelShadow: '0px 16px 36px rgba(0, 0, 0, 0.5)',
};

const billiards = {
  ...shared,
  ...billiardsTable,
  pageGlow: p.purple50,
  panelShadow: '0px 16px 36px rgba(46, 16, 101, 0.26)',
};

const APP_THEMES = { light: billiards, dark: billiardsDark };

/**
 * One league's theme: the shared roles for the scheme, with the accent and
 * the status panel in the league's colours. The ball by its name is the
 * game's - an 8-ball in billiards, a ringed white ball in ping pong.
 */
function buildLeagueTheme(league, scheme) {
  const dark = scheme === 'dark';
  const c = leagueColors(league.primary_color, league.secondary_color, scheme);
  const pingPong = league.game === 'ping_pong';
  const panel = c['panel-solid'];
  const text = c['panel-text'];

  return {
    ...(dark ? sharedDark : shared),
    pageGlow: c['page-glow'],

    textStrong: c.heading,
    accent: c.accent,
    accentPressed: c['accent-hover'],
    accentText: c['accent-text'],
    accentStrong: c['accent-strong'],
    accentSoft: c['accent-soft'],
    accentWash: c['accent-wash'],
    onAccent: c['on-accent'],
    inputFocus: c.focus,

    ballFill: pingPong ? p.white : c.accent,
    ballRing: pingPong ? c.accent : 'transparent',
    ballSpot: pingPong ? null : p.white,

    panelBg: panel,
    panelBgPlaying: c['panel-solid-playing'],
    panelBorder: dark ? c['panel-border'] : panel,
    panelEdge: c['panel-band'],
    panelEdgeSize: 4,
    panelShadow: dark
      ? '0px 16px 36px rgba(0, 0, 0, 0.5)'
      : `0px 16px 36px ${alpha(mix(panel, '#000000', 0.5), 0.26)}`,
    panelText: text,
    panelDim: c['panel-dim'],
    panelFaint: c['panel-faint'],
    panelLine: c['panel-line'],
    panelFill: c['panel-fill'],
    panelFillStrong: c['panel-fill-strong'],
    panelIcon: c['panel-icon'],
    panelCtaBg: c['panel-cta-bg'],
    panelCtaText: c['panel-cta-text'],
    panelCtaPressed: c['panel-cta-hover'],
    panelErrorEdge: c['panel-error-edge'],
    panelInputBorder: alpha(text, 0.4),
  };
}

// Built once per league, colours and scheme, so screens that ask for the
// theme on every render get the same object back.
const built = new Map();

/**
 * The theme for a league (an entry from GET /leagues/directory), by day
 * ("light") or night ("dark"). With no league - signed out, choosing one -
 * the app's own purple.
 */
export function themeFor(league, scheme = 'light') {
  const mode = scheme === 'dark' ? 'dark' : 'light';
  if (!league?.primary_color) return APP_THEMES[mode];
  const key = [league.primary_color, league.secondary_color, league.game, mode].join('|');
  if (!built.has(key)) built.set(key, buildLeagueTheme(league, mode));
  return built.get(key);
}
