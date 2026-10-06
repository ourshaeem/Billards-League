/**
 * A league's whole colour scheme, built from its two colours (the
 * league's primary_color and secondary_color, from the server).
 *
 * Every league is dressed the same way:
 *   - the status panel is the primary colour, with the secondary as the
 *     band along its top and its main button;
 *   - on the page, the primary marks what you can act on - buttons,
 *     links, headings.
 * Contrast is worked out, never assumed. Text on a colour is whichever of
 * near-white or near-black reads better on it; a colour used as text on
 * the page is darkened (by day) or lightened (in the dark) until it
 * reaches 4.5:1. That is what keeps CCNY's lavender, John Jay's navy and
 * Brooklyn's gold all readable without anyone checking each by hand.
 *
 * Plain JavaScript, no DOM or React Native: the web app turns the result
 * into CSS custom properties (theme.js), the phone app into its theme
 * object. This file is copied between the two apps - a change to one is a
 * change to both.
 */

const WHITE = '#ffffff';
const BLACK = '#000000';
const INK = '#111014';
const PAPER = '#ffffff';

// The page and card behind accent text, in each mode (index.css's
// --surface).
const SURFACES = { light: '#ffffff', dark: '#1a1622' };
const PAGES = { light: '#ffffff', dark: '#110e17' };

function parse(hex) {
  const clean = String(hex || '').replace('#', '').trim();
  const full = clean.length === 3 ? clean.replace(/(.)/g, '$1$1') : clean.padEnd(6, '0').slice(0, 6);
  const n = Number.parseInt(full, 16);
  if (Number.isNaN(n)) return { r: 109, g: 40, b: 217 };
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function toHex({ r, g, b }) {
  const part = (v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0');
  return `#${part(r)}${part(g)}${part(b)}`;
}

/** a blended toward b by t (0 = a, 1 = b). */
export function mix(a, b, t) {
  const x = parse(a);
  const y = parse(b);
  return toHex({ r: x.r + (y.r - x.r) * t, g: x.g + (y.g - x.g) * t, b: x.b + (y.b - x.b) * t });
}

/** A colour with transparency, as rgba(). */
export function alpha(hex, opacity) {
  const { r, g, b } = parse(hex);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function channel(v) {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance, 0 (black) to 1 (white). */
export function luminance(hex) {
  const { r, g, b } = parse(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio between two colours, 1 to 21. */
export function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** Near-white or near-black: whichever reads better on bg. */
export function textOn(bg) {
  return contrast(PAPER, bg) >= contrast(INK, bg) ? PAPER : INK;
}

/** colour, moved toward `target` until it has `ratio` against `against`. */
function untilReadable(colour, target, against, ratio) {
  for (let t = 0; t <= 1; t += 0.04) {
    const candidate = mix(colour, target, t);
    if (contrast(candidate, against) >= ratio) return candidate;
  }
  return target;
}

/** The first colour with at least `ratio` against bg, else whichever text reads on it. */
function firstReadable(candidates, bg, ratio) {
  return candidates.find((c) => c && contrast(c, bg) >= ratio) ?? textOn(bg);
}

/**
 * Every colour role, for one league in one mode ("light" or "dark"), as
 * { token: value } - the names index.css uses, without the leading "--".
 * Missing colours fall back to the app's own purple.
 */
export function leagueColors(primaryColor, secondaryColor, mode = 'light') {
  const primary = primaryColor || '#6d28d9';
  const secondary = secondaryColor || primary;
  const dark = mode === 'dark';
  const surface = SURFACES[dark ? 'dark' : 'light'];
  const page = PAGES[dark ? 'dark' : 'light'];
  const away = dark ? WHITE : BLACK; // the way "more readable" lies on this page

  // --- The page: the primary marks what you can act on ---
  const accent = contrast(primary, surface) >= 3 ? primary : untilReadable(primary, away, surface, 3);
  const accentText = untilReadable(primary, away, surface, 4.5);
  const tokens = {
    accent,
    'accent-hover': mix(accent, dark ? WHITE : BLACK, 0.14),
    'accent-strong': untilReadable(primary, away, surface, 9),
    'accent-soft': mix(primary, surface, dark ? 0.8 : 0.86),
    'accent-wash': mix(primary, surface, dark ? 0.89 : 0.94),
    'on-accent': textOn(accent),
    heading: untilReadable(primary, away, surface, 8),
    'accent-text': accentText,
    'accent-line': mix(accent, surface, 0.5),
    'avatar-text': untilReadable(primary, away, mix(primary, surface, 0.86), 6),
    focus: accentText,
    'selection-bg': mix(primary, surface, dark ? 0.55 : 0.7),
    'page-glow': mix(primary, page, dark ? 0.84 : 0.88),
    'shadow-button': dark ? '0 2px 10px rgba(0, 0, 0, 0.45)' : `0 2px 8px ${alpha(accent, 0.3)}`,
  };
  tokens['selection-text'] = textOn(tokens['selection-bg']);

  // --- The status panel: the primary, with the secondary along its top ---
  // In the dark a light primary is deepened, so the panel isn't a
  // floodlight at night.
  const base = dark && luminance(primary) > 0.18 ? mix(primary, BLACK, 0.55) : primary;
  const lightPanel = textOn(base) === INK;
  const stops = lightPanel
    ? [mix(base, WHITE, 0.12), base, mix(base, BLACK, 0.08)]
    : [base, mix(base, BLACK, 0.18), mix(base, BLACK, 0.32)];
  const playing = lightPanel
    ? [base, mix(base, BLACK, 0.06), mix(base, BLACK, 0.14)]
    : [mix(base, BLACK, 0.08), mix(base, BLACK, 0.28), mix(base, BLACK, 0.42)];
  const middle = stops[1];
  const text = textOn(middle);
  const band = firstReadable([secondary, primary, accentText], middle, 2);
  const cta = firstReadable([secondary, primary, text], middle, 3);

  Object.assign(tokens, {
    'panel-bg': `linear-gradient(155deg, ${stops[0]} 0%, ${stops[1]} 60%, ${stops[2]} 100%)`,
    'panel-bg-playing': `linear-gradient(155deg, ${playing[0]} 0%, ${playing[1]} 55%, ${playing[2]} 100%)`,
    'panel-border': dark ? mix(base, WHITE, 0.14) : 'transparent',
    'panel-edge': `linear-gradient(90deg, ${band}, ${mix(band, middle, 0.35)})`,
    'panel-edge-size': '4px',
    'panel-shadow': dark ? '0 20px 44px rgba(0, 0, 0, 0.5)' : `0 20px 44px ${alpha(mix(base, BLACK, 0.5), 0.26)}`,
    'panel-text': text,
    'panel-dim': alpha(text, 0.84),
    'panel-faint': alpha(text, 0.66),
    'panel-line': alpha(text, 0.28),
    'panel-fill': alpha(text, 0.12),
    'panel-fill-hover': alpha(text, 0.2),
    'panel-fill-strong': alpha(text, 0.3),
    'panel-icon': firstReadable([secondary, primary], middle, 3),
    'panel-focus': text,
    'panel-cta-bg': cta,
    'panel-cta-text': textOn(cta),
    'panel-cta-hover': mix(cta, textOn(cta), 0.14),
    'panel-cta-shadow': '0 2px 10px rgba(0, 0, 0, 0.3)',
    'panel-error-edge': text === PAPER ? '#fda29b' : '#b42318',
    // The same panel as single colours, for the phone app, which draws
    // no gradients: its main colour, while playing, and its top band.
    'panel-solid': middle,
    'panel-solid-playing': playing[1],
    'panel-band': band,
  });
  return tokens;
}

/** The colour phones paint their browser toolbar for a league. */
export function toolbarColor(primaryColor, mode = 'light') {
  return mode === 'dark' ? '#15121d' : primaryColor || '#6d28d9';
}
