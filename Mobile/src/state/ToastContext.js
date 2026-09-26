/**
 * Short messages that appear over whatever screen is showing - "Match
 * found", "Profile saved", a refusal from the server.
 *
 * The mobile counterpart of the web app's toasts, for the same reason:
 * a blocking system alert for something as minor as "joined the queue"
 * interrupts the player, so nothing here uses Alert.alert. Each message
 * is also read out by the screen reader.
 */
import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

import { ToastStack } from '../components/Feedback';

// Beyond this, the oldest messages give way.
const MAX_VISIBLE_TOASTS = 3;

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const clear = useCallback(() => setToasts([]), []);

  const push = useCallback((message, tone = 'info') => {
    if (!message) return;
    AccessibilityInfo.announceForAccessibility?.(message);
    setToasts((current) => {
      // A button that keeps failing shouldn't build a tower of identical
      // messages - the existing one counts up instead.
      const same = current.find((t) => t.message === message && t.tone === tone);
      if (same) {
        return current.map((t) => (t === same ? { ...t, count: t.count + 1 } : t));
      }
      const next = [...current, { id: `${Date.now()}-${Math.random()}`, message, tone, count: 1 }];
      return next.slice(-MAX_VISIBLE_TOASTS);
    });
  }, []);

  const value = useMemo(() => ({ push, dismiss, clear }), [push, dismiss, clear]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/** { push(message, tone), dismiss(id), clear() }. tone: info, success or error. */
export function useToast() {
  return useContext(ToastContext);
}
