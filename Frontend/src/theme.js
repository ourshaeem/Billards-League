/**
 * Light or dark: the player's choice, remembered on this device.
 *
 * "system" (the default) follows the device's own setting, and keeps
 * following it if that changes - many phones and laptops switch to dark
 * in the evening. "light" or "dark" pins it.
 *
 * The chosen theme is set as <html data-theme>, and index.css redefines
 * its colour tokens for dark - the same way the league themes work, so no
 * component knows which theme it's drawn in. index.html applies the
 * stored choice before the first paint (keep THEME_KEY in step with it),
 * so a dark page doesn't flash white while the app loads.
 */
export const THEME_KEY = 'theme';
export const THEME_CHOICES = [
  { key: 'system', label: 'Automatic' },
  { key: 'light', label: 'Light' },
  { key: 'dark', label: 'Dark' },
];

const DARK_QUERY = '(prefers-color-scheme: dark)';
// The browser's own toolbar colour on phones, per theme.
const TOOLBAR_COLOURS = { light: '#6d28d9', dark: '#15121d' };

export function getThemeChoice() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    // Storage can be off (private browsing); follow the device.
    return 'system';
  }
}

export function setThemeChoice(choice) {
  try {
    if (choice === 'light' || choice === 'dark') localStorage.setItem(THEME_KEY, choice);
    else localStorage.removeItem(THEME_KEY);
  } catch {
    // Not fatal - the choice just won't survive a refresh.
  }
}

function systemPrefersDark() {
  return typeof window !== 'undefined' && window.matchMedia?.(DARK_QUERY).matches === true;
}

/** "light" or "dark": what a choice means on this device right now. */
export function resolveTheme(choice) {
  if (choice === 'light' || choice === 'dark') return choice;
  return systemPrefersDark() ? 'dark' : 'light';
}

export function applyTheme(theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  const toolbar = document.querySelector('meta[name="theme-color"]');
  if (toolbar) toolbar.setAttribute('content', TOOLBAR_COLOURS[theme] ?? TOOLBAR_COLOURS.light);
}

/** Calls onChange when the device switches between light and dark. */
export function watchSystemTheme(onChange) {
  const media = window.matchMedia?.(DARK_QUERY);
  if (!media) return () => {};
  const listener = () => onChange();
  media.addEventListener('change', listener);
  return () => media.removeEventListener('change', listener);
}
