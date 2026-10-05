/**
 * The small set of building blocks every screen is made from - the React
 * Native versions of the web app's HTML and CSS classes:
 *
 *   <p>, <span>, <h2>     -> Txt
 *   <button> + .btn-*     -> Button (and HeaderButton)
 *   <section class=card>  -> Card
 *   <label> + <input>     -> Field
 *   the page itself       -> Screen (scrolls, pulls to refresh)
 *
 * Colours come from the current league's theme - by day or by night -
 * never written here.
 * Every control is at least 44 points tall - the smallest target a thumb
 * hits reliably - and says what it is to screen readers.
 */
import React, { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import Feather from '@expo/vector-icons/Feather';

import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';

// --- Text ------------------------------------------------------------

const TEXT_VARIANTS = {
  body: { fontFamily: fonts.regular, fontSize: type.body, lineHeight: 23 },
  small: { fontFamily: fonts.regular, fontSize: type.small, lineHeight: 19 },
  label: { fontFamily: fonts.semibold, fontSize: type.small, lineHeight: 19 },
  title: { fontFamily: fonts.semibold, fontSize: type.large, lineHeight: 25 },
  display: { fontFamily: fonts.display, fontSize: type.display, lineHeight: 40 },
  headline: { fontFamily: fonts.display, fontSize: type.headline, lineHeight: 46 },
};

const WEIGHTS = { regular: fonts.regular, semibold: fonts.semibold, bold: fonts.bold };

/** Text in the app's type scale. `muted` for secondary text. */
export function Txt({ variant = 'body', weight, muted, color, style, ...rest }) {
  const theme = useTheme();
  return (
    <Text
      style={[
        TEXT_VARIANTS[variant],
        { color: color ?? (muted ? theme.textMuted : theme.text) },
        weight && { fontFamily: WEIGHTS[weight] },
        style,
      ]}
      {...rest}
    />
  );
}

// --- Buttons ---------------------------------------------------------

function buttonColors(theme, variant) {
  switch (variant) {
    case 'quiet':
      return { bg: 'transparent', pressed: theme.quietPressed, border: theme.quietBorder, text: theme.quietText };
    case 'link':
      return { bg: 'transparent', pressed: 'transparent', border: 'transparent', text: theme.accentText };
    // On the status panel, the colours come from the panel's own roles:
    // on the purple billiards panel the loud button is white.
    case 'panelPrimary':
      return { bg: theme.panelCtaBg, pressed: theme.panelCtaPressed, border: theme.panelCtaBg, text: theme.panelCtaText };
    case 'panelQuiet':
      return { bg: 'transparent', pressed: theme.panelFill, border: theme.panelLine, text: theme.panelText };
    case 'panelWin':
      return { bg: theme.panelFillStrong, pressed: theme.panelFill, border: 'transparent', text: theme.panelText };
    case 'panelLoss':
      return { bg: 'transparent', pressed: theme.panelFill, border: theme.panelLine, text: theme.panelDim };
    // Red only for what can't be undone: deleting an account, and the
    // organiser taking a player off the table or out of the queue.
    case 'danger':
      return { bg: theme.dangerFill, pressed: theme.dangerPressed, border: theme.dangerFill, text: theme.onAccent };
    case 'dangerQuiet':
      return { bg: 'transparent', pressed: theme.dangerSoft, border: theme.dangerLine, text: theme.danger };
    default:
      return { bg: theme.accent, pressed: theme.accentPressed, border: theme.accent, text: theme.onAccent };
  }
}

const BUTTON_SIZES = {
  lg: { fontSize: type.large, paddingVertical: 14, paddingHorizontal: 26 },
  md: { fontSize: type.body, paddingVertical: 11, paddingHorizontal: 20 },
  sm: { fontSize: type.small, paddingVertical: 8, paddingHorizontal: 14 },
};

/**
 * variant: primary | quiet | link | panelPrimary | panelQuiet | panelWin | panelLoss
 *          | danger | dangerQuiet (deleting an account, removing a player - nothing else)
 * `waiting` keeps a disabled button fully legible with a dashed edge -
 * for a countdown the player is watching, not a dead control.
 */
export function Button({
  title,
  onPress,
  variant = 'primary',
  size = 'md',
  icon,
  disabled = false,
  busy = false,
  waiting = false,
  accessibilityLabel,
  accessibilityHint,
  style,
  children,
}) {
  const theme = useTheme();
  const colors = buttonColors(theme, variant);
  const sizing = BUTTON_SIZES[size];
  const inactive = disabled || busy;
  const isLink = variant === 'link';

  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityHint={accessibilityHint}
      // busy only when true: Android announces "busy" whenever the key
      // is present, even set to false.
      accessibilityState={busy ? { disabled: true, busy: true } : { disabled: inactive }}
      hitSlop={isLink ? 8 : undefined}
      style={({ pressed }) => [
        styles.button,
        !isLink && {
          paddingVertical: sizing.paddingVertical,
          paddingHorizontal: sizing.paddingHorizontal,
          borderColor: colors.border,
          backgroundColor: pressed ? colors.pressed : colors.bg,
        },
        isLink && styles.linkButton,
        waiting && styles.waiting,
        inactive && !waiting && styles.disabled,
        style,
      ]}
    >
      {busy ? <ActivityIndicator size="small" color={colors.text} /> : null}
      {!busy && icon ? <Feather name={icon} size={sizing.fontSize} color={colors.text} /> : null}
      {children ?? (
        <Text
          style={[
            styles.buttonText,
            { fontSize: sizing.fontSize, color: waiting ? theme.panelFaint : colors.text },
            isLink && styles.linkText,
          ]}
        >
          {title}
        </Text>
      )}
    </Pressable>
  );
}

/** A compact icon-and-word button for navigation headers. */
export function HeaderButton({ icon, label, onPress }) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={8}
      style={({ pressed }) => [
        styles.headerButton,
        { borderColor: theme.quietBorder, backgroundColor: pressed ? theme.quietPressed : 'transparent' },
      ]}
    >
      <Feather name={icon} size={15} color={theme.quietText} />
      <Text style={[styles.headerButtonText, { color: theme.quietText }]}>{label}</Text>
    </Pressable>
  );
}

// --- Card ------------------------------------------------------------

/** A white card with a titled header - the web app's .card. */
export function Card({ title, icon, right, children, style, footer }) {
  const theme = useTheme();
  return (
    <View
      style={[
        styles.card,
        { backgroundColor: theme.surface, borderColor: theme.line, boxShadow: theme.shadowCard },
        style,
      ]}
    >
      {title ? (
        <View style={[styles.cardHead, { borderBottomColor: theme.line }]}>
          <View style={styles.cardTitleRow}>
            {icon ? <Feather name={icon} size={18} color={theme.accent} /> : null}
            <Txt variant="title" accessibilityRole="header">
              {title}
            </Txt>
          </View>
          {right}
        </View>
      ) : null}
      {children}
      {footer ? (
        <Txt variant="small" muted style={styles.cardFoot}>
          {footer}
        </Txt>
      ) : null}
    </View>
  );
}

/** A small rounded count or state badge, as in a card header. */
export function Pill({ children }) {
  const theme = useTheme();
  return (
    <View style={[styles.pill, { backgroundColor: theme.accentSoft }]}>
      <Text style={[styles.pillText, { color: theme.accentText }]}>{children}</Text>
    </View>
  );
}

// --- Form field ------------------------------------------------------

/**
 * A labelled text input. `error` appears beside the field it concerns,
 * and is announced to screen readers as it appears. `onPanel` switches
 * to the status panel's colours.
 */
export function Field({ label, error, hint, onPanel = false, style, inputStyle, ...inputProps }) {
  const theme = useTheme();
  const [focused, setFocused] = useState(false);

  const borderColor = error
    ? theme.danger
    : focused
      ? onPanel
        ? theme.panelText
        : theme.inputFocus
      : onPanel
        ? theme.panelInputBorder
        : theme.inputBorder;

  return (
    <View style={[styles.field, style]}>
      <Text style={[styles.label, { color: onPanel ? theme.panelDim : theme.quietText }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        accessibilityHint={error || hint}
        placeholderTextColor={theme.textMuted}
        {...inputProps}
        onFocus={(e) => {
          setFocused(true);
          inputProps.onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          inputProps.onBlur?.(e);
        }}
        style={[
          styles.input,
          { borderColor, color: theme.text, backgroundColor: theme.surface },
          focused && { boxShadow: `0px 0px 0px 3px ${onPanel ? theme.panelLine : theme.accentSoft}` },
          inputStyle,
        ]}
      />
      {hint && !error ? (
        <Txt variant="small" muted style={styles.fieldNote}>
          {hint}
        </Txt>
      ) : null}
      <FieldError message={error} onPanel={onPanel} />
    </View>
  );
}

export function FieldError({ message, onPanel = false }) {
  const theme = useTheme();
  if (!message) return null;
  return (
    <Text
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[styles.fieldNote, styles.fieldError, { color: onPanel ? theme.panelText : theme.danger }]}
    >
      {message}
    </Text>
  );
}

// --- Screen ----------------------------------------------------------

/**
 * A scrolling screen with the page background and side padding. Pass
 * onRefresh for pull-to-refresh. Moves out of the keyboard's way, and
 * lets a tap on a button land while the keyboard is still up.
 */
export function Screen({ children, onRefresh, refreshing = false, contentStyle, scrollRef }) {
  const theme = useTheme();
  return (
    <KeyboardAvoidingView
      style={[styles.flex, { backgroundColor: theme.page }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        ref={scrollRef}
        style={styles.flex}
        contentContainerStyle={[styles.screenContent, contentStyle]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? (
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.accent} colors={[theme.accent]} />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

/** Two or more options side by side, one selected - e.g. Everyone / Your games. */
export function Segmented({ options, value, onChange, accessibilityLabel }) {
  const theme = useTheme();
  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
      style={[styles.segmented, { backgroundColor: theme.fillSoft }]}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            accessibilityRole="radio"
            accessibilityState={{ selected, checked: selected }}
            style={[
              styles.segment,
              selected && { backgroundColor: theme.surface, boxShadow: theme.shadowRaised },
            ]}
          >
            <Text
              style={[styles.segmentText, { color: selected ? theme.accentText : theme.textMuted }]}
            >
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  button: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderRadius: radius.md,
    borderWidth: 1,
  },
  buttonText: { fontFamily: fonts.semibold, textAlign: 'center' },
  linkButton: { minHeight: 32, paddingHorizontal: 4, borderWidth: 0 },
  linkText: { textDecorationLine: 'underline' },
  disabled: { opacity: 0.5 },
  waiting: { borderStyle: 'dashed', backgroundColor: 'transparent' },
  headerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    minHeight: 36,
    paddingHorizontal: 12,
    marginRight: 12,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  headerButtonText: { fontFamily: fonts.semibold, fontSize: 13.5 },
  card: {
    borderWidth: 1,
    borderRadius: radius.md,
    padding: 18,
    marginBottom: 16,
  },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 10,
    paddingBottom: 12,
    marginBottom: 12,
    borderBottomWidth: 1,
  },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardFoot: { marginTop: 14 },
  pill: { paddingHorizontal: 11, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.semibold, fontSize: type.small, fontVariant: ['tabular-nums'] },
  field: { marginBottom: 14 },
  label: { fontFamily: fonts.semibold, fontSize: type.small, marginBottom: 6 },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderRadius: radius.sm,
    // Spelled out side by side on purpose: on Android, a text input
    // ignores the paddingHorizontal / paddingVertical shorthands and
    // falls back to the system's own padding, putting the text almost
    // against the border. (Seen on the Android emulator, API 36.)
    paddingLeft: 14,
    paddingRight: 14,
    paddingTop: 12,
    paddingBottom: 12,
    fontFamily: fonts.regular,
    fontSize: type.body,
  },
  fieldNote: { marginTop: 5 },
  fieldError: { fontFamily: fonts.regular, fontSize: type.small },
  screenContent: { padding: 16, paddingBottom: 40 },
  segmented: { flexDirection: 'row', padding: 3, borderRadius: radius.pill, alignSelf: 'flex-start' },
  segment: { minHeight: 36, paddingHorizontal: 14, justifyContent: 'center', borderRadius: radius.pill },
  segmentText: { fontFamily: fonts.semibold, fontSize: type.small },
});
