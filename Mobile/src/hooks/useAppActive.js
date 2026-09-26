/**
 * Whether the app is on screen. Polling stops when it isn't: a phone in
 * a pocket shouldn't spend its battery asking about the queue every
 * 2.5 seconds, and everything refreshes the moment the app comes back.
 */
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

function isActive(state) {
  // 'unknown' is what some platforms report before the first change.
  return state !== 'background' && state !== 'inactive';
}

export function useAppActive() {
  const [active, setActive] = useState(() => isActive(AppState.currentState));

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => setActive(isActive(state)));
    return () => subscription.remove();
  }, []);

  return active;
}
