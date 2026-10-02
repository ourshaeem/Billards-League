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

// Not the league's theme (useTheme): ToastContext draws these, and the
// league's context needs ToastContext - importing it here would make a
// circle. Nothing here differs between the leagues anyway.
import { useAppearance } from '../state/AppearanceContext';
import { fonts, palette, radius, themeFor, type } from '../theme';

const TOAST_MS = { info: 4000, success: 4000, error: 8000 };

const EDGE = {
  error: palette.dangerOnDark,
  success: palette.purple300,
  info: palette.onDarkMuted,
};

export function ToastStack({ toasts, onDismiss }) {
  const insets = useSafeAreaInsets();
  // Toasts sit above the league's theme in the app, so they take their
  // colours - the same in both leagues - straight from the scheme.
  const { scheme } = useAppearance();
  const colors = themeFor(null, scheme);
  if (!toasts.length) return null;

  return (
    <View pointerEvents="box-none" style={[styles.stack, { top: insets.top + 8 }]}>
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} colors={colors} />
      ))}
    </View>
  );
}

function Toast({ toast, onDismiss, colors }) {
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
      style={[
        styles.toast,
        { backgroundColor: colors.toastBg, borderLeftColor: EDGE[toast.tone] ?? EDGE.info },
      ]}
    >
      <Text style={[styles.message, { color: colors.toastText }]}>
        {toast.message}
        {toast.count > 1 ? (
          <Text style={[styles.count, { color: colors.toastMuted }]}> ×{toast.count}</Text>
        ) : null}
      </Text>
      <Pressable
        onPress={() => onDismiss(toast.id)}
        accessibilityRole="button"
        accessibilityLabel="Dismiss message"
        hitSlop={8}
        style={({ pressed }) => [styles.close, pressed && styles.closePressed]}
      >
        <Feather name="x" size={16} color={colors.toastMuted} />
      </Pressable>
    </View>
  );
}

/**
 * Shown when requests can't reach the server. Without it the screen
 * quietly stops updating, which looks identical to "nothing is happening".
 */
export function ConnectionBanner({ offline }) {
  const theme = themeFor(null, useAppearance().scheme);
  if (!offline) return null;
  return (
    <View
      accessibilityRole="alert"
      style={[styles.banner, { borderColor: theme.warnLine, backgroundColor: theme.warnSoft }]}
    >
      <Feather name="wifi-off" size={16} color={theme.warn} />
      <Text style={[styles.bannerText, { color: theme.warn }]}>
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
    boxShadow: '0px 12px 32px rgba(0, 0, 0, 0.3)',
  },
  message: {
    flex: 1,
    paddingTop: 5,
    fontFamily: fonts.regular,
    fontSize: type.small,
    lineHeight: 19,
  },
  count: { fontVariant: ['tabular-nums'] },
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
  },
  bannerText: { flex: 1, fontFamily: fonts.regular, fontSize: type.small, lineHeight: 19 },
});
