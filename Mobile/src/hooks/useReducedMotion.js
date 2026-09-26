/**
 * Whether the person has asked their phone to reduce motion. Anything
 * that slides or fades checks this first - the same promise the web app
 * keeps with prefers-reduced-motion.
 */
import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled?.()
      .then((value) => mounted && setReduced(Boolean(value)))
      .catch(() => {});
    const subscription = AccessibilityInfo.addEventListener?.('reduceMotionChanged', (value) =>
      setReduced(Boolean(value)),
    );
    return () => {
      mounted = false;
      subscription?.remove?.();
    };
  }, []);

  return reduced;
}
