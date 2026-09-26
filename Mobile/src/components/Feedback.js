/**
 * What a person sees when something happens or goes wrong: toasts, and
 * the banner shown when the server can't be reached.
 *
 * Toasts sit at the top, over the header, where phones put their own
 * notifications. Anywhere lower they'd cover controls in the middle of
 * being used, and at the bottom the keyboard would hide them on the
 * sign-in screen - exactly where "wrong password" appears. Each goes
 * away by itself (errors stay longer: there is usually more to read) or
 * with its close button.
 */
import React, { useEffect, useRef } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Feather from '@expo/vector-icons/Feather';

import { fonts, palette, radius, type } from '../theme';

const TOAST_MS = { info: 4000, success: 4000, error: 8000 };

const EDGE = {
  error: palette.dangerOnDark,
  success: palette.purple300,
  info: palette.onDarkMuted,
};

export function ToastStack({ toasts, onDismiss }) {
  const insets = useSafeAreaInsets();
  if (!toasts.length) return null;

  return (
    <View pointerEvents="box-none" style={[styles.stack, { top: insets.top + 8 }]}>
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </View>
  );
}

function Toast({ toast, onDismiss }) {
  const fullTime = TOAST_MS[toast.tone] ?? TOAST_MS.info;
  const onDismissRef = useRef(onDismiss);
  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  // The same message raised again (count goes up) gets its full time back.
  useEffect(() => {
    const timer = setTimeout(() => onDismissRef.current(toast.id), fullTime);
    return () => clearTimeout(timer);
  }, [toast.id, toast.count, fullTime]);

  return (
    <View
      accessibilityRole={toast.tone === 'error' ? 'alert' : undefined}
      accessibilityLiveRegion="polite"
      style={[styles.toast, { borderLeftColor: EDGE[toast.tone] ?? EDGE.info }]}
    >
      <Text style={styles.message}>
        {toast.message}
        {toast.count > 1 ? <Text style={styles.count}> ×{toast.count}</Text> : null}
      </Text>
      <Pressable
        onPress={() => onDismiss(toast.id)}
        accessibilityRole="button"
        accessibilityLabel="Dismiss message"
        hitSlop={8}
        style={({ pressed }) => [styles.close, pressed && styles.closePressed]}
      >
        <Feather name="x" size={16} color={palette.onDarkMuted} />
      </Pressable>
    </View>
  );
}

/**
 * Shown when requests can't reach the server. Without it the screen
 * quietly stops updating, which looks identical to "nothing is happening".
 */
export function ConnectionBanner({ offline }) {
  if (!offline) return null;
  return (
    <View accessibilityRole="alert" style={styles.banner}>
      <Feather name="wifi-off" size={16} color={palette.warn} />
      <Text style={styles.bannerText}>
        Can't reach the server, so what you see may be out of date. The free server can take up
        to a minute to wake up - retrying automatically.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { position: 'absolute', left: 12, right: 12, gap: 8, zIndex: 100 },
  toast: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    paddingVertical: 10,
    paddingLeft: 14,
    paddingRight: 6,
    borderRadius: radius.md,
    borderLeftWidth: 4,
    backgroundColor: palette.gray900,
    boxShadow: '0px 12px 32px rgba(27, 26, 34, 0.28)',
  },
  message: {
    flex: 1,
    paddingTop: 5,
    color: palette.white,
    fontFamily: fonts.regular,
    fontSize: type.small,
    lineHeight: 19,
  },
  count: { color: palette.onDarkMuted, fontVariant: ['tabular-nums'] },
  close: { width: 32, height: 32, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  closePressed: { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
  banner: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'flex-start',
    padding: 12,
    marginBottom: 14,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: palette.warnLine,
    backgroundColor: palette.warnSoft,
  },
  bannerText: { flex: 1, color: palette.warn, fontFamily: fonts.regular, fontSize: type.small, lineHeight: 19 },
});
