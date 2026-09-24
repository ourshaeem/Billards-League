/**
 * Small shared presentation pieces.
 *
 * These live apart from App so the screens read as layout rather than a
 * mix of layout and plumbing, and so the React Native port has an obvious
 * list of what needs a native equivalent.
 */
import React, { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

// How long a message stays up. Errors get longer - there's usually more
// to read - but they do go: an error that stays until dismissed is only
// fine until the dismiss button ends up off-screen, which is exactly what
// happened when a long server error filled the page.
const TOAST_MS = { info: 4000, success: 4000, error: 8000 };

// Beyond this, the oldest messages give way. A stack of toasts taller
// than the screen is how the close buttons became unreachable.
const MAX_VISIBLE_TOASTS = 3;

/**
 * Replaces alert(). alert() blocks the whole tab, can't be styled, and on
 * a phone it's a jarring system dialog for something as minor as "joined
 * the queue" - which this app would have fired on every single action.
 *
 * Every toast can be closed three ways: its own button, the Escape key
 * (closes them all), or simply waiting.
 */
export function ToastStack({ toasts, onDismiss }) {
  const hasToasts = toasts.length > 0;

  // Read through a ref so the key listener is attached once per burst of
  // messages, not re-attached on every render.
  const toastsRef = useRef(toasts);
  useEffect(() => {
    toastsRef.current = toasts;
  }, [toasts]);

  useEffect(() => {
    if (!hasToasts) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') toastsRef.current.forEach((t) => onDismiss(t.id));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [hasToasts, onDismiss]);

  if (!hasToasts) return null;
  const visible = toasts.slice(-MAX_VISIBLE_TOASTS);

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {visible.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function Toast({ toast, onDismiss }) {
  // Hovering or focusing a toast holds it open, so nobody loses a message
  // halfway through reading it.
  const [held, setHeld] = useState(false);
  const fullTime = TOAST_MS[toast.tone] ?? TOAST_MS.info;
  const remainingRef = useRef(fullTime);

  // The same message raised again (toast.count goes up) gets its full
  // time back, so the repeat is actually seen. Declared before the timer
  // effect so it runs first.
  useEffect(() => {
    remainingRef.current = fullTime;
  }, [toast.count, fullTime]);

  useEffect(() => {
    if (held) return undefined;
    const started = Date.now();
    const timer = setTimeout(() => onDismiss(toast.id), remainingRef.current);
    return () => {
      clearTimeout(timer);
      remainingRef.current = Math.max(1000, remainingRef.current - (Date.now() - started));
    };
  }, [held, toast.id, toast.count, onDismiss]);

  return (
    <div
      className="toast"
      data-tone={toast.tone}
      role={toast.tone === 'error' ? 'alert' : undefined}
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
    >
      <p className="toast-message">
        {toast.message}
        {toast.count > 1 && <span className="toast-count"> &times;{toast.count}</span>}
      </p>
      <button
        type="button"
        className="toast-close"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss message"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * Shown when polling can't reach the backend. Without this the screen
 * just quietly stops updating and the numbers slowly go stale, which
 * looks identical to "nothing is happening right now".
 */
export function ConnectionBanner({ offline }) {
  if (!offline) return null;

  return (
    <div className="banner banner-offline" role="status">
      Can't reach the server, so the queue and ladder below may be out of date.
      Reconnecting automatically.
    </div>
  );
}

/** Inline form error, tied to its input for screen readers. */
export function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <span className="field-error" id={id} role="alert">
      {message}
    </span>
  );
}
