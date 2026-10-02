/**
 * Light or dark, for the whole app: the player's choice (Profile >
 * Appearance), remembered on the phone.
 *
 * "system" - the default - follows the phone's own setting, and keeps
 * following it as it changes (many phones turn dark in the evening).
 * "light" or "dark" pins it, including for the keyboard, pickers and
 * other controls the phone itself draws.
 *
 * Above every other provider: the toasts are drawn by ToastProvider,
 * which sits outside the league's theme but still needs to know which
 * scheme it's on.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Appearance, useColorScheme } from 'react-native';

import { loadAppearance, saveAppearance } from '../storage';

const AppearanceContext = createContext({ choice: 'system', scheme: 'light', setChoice: () => {} });

export const APPEARANCE_OPTIONS = [
  { value: 'system', label: 'Automatic' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

export function AppearanceProvider({ children }) {
  const [choice, setChoiceState] = useState('system');
  const device = useColorScheme();

  useEffect(() => {
    let cancelled = false;
    loadAppearance().then((stored) => {
      if (!cancelled) setChoiceState(stored);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // So the parts the phone draws itself - the keyboard, the photo
  // picker, date and share sheets - match the app. Not available in the
  // web preview, where the page's own colours are all there is.
  useEffect(() => {
    Appearance.setColorScheme?.(choice === 'system' ? 'unspecified' : choice);
  }, [choice]);

  const setChoice = useCallback((next) => {
    setChoiceState(next);
    saveAppearance(next);
  }, []);

  const scheme = choice === 'system' ? (device === 'dark' ? 'dark' : 'light') : choice;

  const value = useMemo(() => ({ choice, scheme, setChoice }), [choice, scheme, setChoice]);
  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

/** { choice: "system" | "light" | "dark", scheme: "light" | "dark", setChoice } */
export function useAppearance() {
  return useContext(AppearanceContext);
}
