/**
 * How a player appears wherever other people can see them: picture (or
 * initial), name and flag - and their standing in the league on show.
 *
 * On the web that standing appeared on hover. Phones have no hover, so
 * here a tap on the player opens the same card. Everything on it comes
 * from the "player card" the backend sends with the data (Player.to_card
 * in Backend/models.py), so opening it never waits on a request.
 */
import React, { useState } from 'react';
import { Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { flagEmoji } from '../flags';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { leagueInfo } from '../leagues';
import { useTheme } from '../state/LeagueContext';
import { fonts, palette, radius, type } from '../theme';

const AVATAR_SIZES = { sm: 28, md: 36, lg: 48, xl: 72 };

function initialOf(name) {
  const first = Array.from((name || '').trim())[0];
  return first ? first.toUpperCase() : '?';
}

/**
 * The player's picture, or their initial when there isn't one - or when
 * the link turns out to be broken, which a pasted link often is.
 * Decorative unless given a `label`, because a name sits beside it.
 */
export function Avatar({ player, size = 'md', label }) {
  const src = player?.profile_picture || null;
  // Keyed on the link, so a new link gets a fresh try after an old one failed.
  return (
    <AvatarImage key={src || 'none'} src={src} name={player?.username} size={size} label={label} />
  );
}

function AvatarImage({ src, name, size, label }) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  const px = AVATAR_SIZES[size] ?? AVATAR_SIZES.md;

  return (
    <View
      accessible={Boolean(label)}
      accessibilityRole={label ? 'image' : undefined}
      accessibilityLabel={label}
      importantForAccessibility={label ? 'yes' : 'no-hide-descendants'}
      style={[
        styles.avatar,
        { width: px, height: px, borderRadius: px / 2, backgroundColor: theme.accentSoft },
      ]}
    >
      {src && !failed ? (
        <Image
          source={{ uri: src }}
          style={{ width: px, height: px }}
          resizeMode="cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <Text style={[styles.initial, { fontSize: px * 0.42, color: theme.accentStrong }]}>
          {initialOf(name)}
        </Text>
      )}
    </View>
  );
}

/**
 * Avatar, name and flag. Tapping opens a card with the player's rank,
 * rating and record in `league`.
 */
export function PlayerChip({ player, league, size = 'md', align = 'start', isYou = false }) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  if (!player) return null;

  const flag = flagEmoji(player.country_flag);
  const end = align === 'end';

  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        accessibilityLabel={`${player.username}${isYou ? ', you' : ''}`}
        accessibilityHint="Shows their rank and rating"
        hitSlop={6}
        style={({ pressed }) => [
          styles.chip,
          end && styles.chipEnd,
          pressed && { backgroundColor: theme.accentWash },
        ]}
      >
        <Avatar player={player} size={size} />
        <Text
          numberOfLines={1}
          style={[styles.name, { color: isYou ? theme.accentPressed : theme.text }, end && styles.nameEnd]}
        >
          {player.username}
        </Text>
        {flag ? <Text style={styles.flag}>{flag}</Text> : null}
      </Pressable>
      <PlayerCard player={player} league={league} visible={open} onClose={() => setOpen(false)} />
    </>
  );
}

function PlayerCard({ player, league, visible, onClose }) {
  const reducedMotion = useReducedMotion();
  const flag = flagEmoji(player.country_flag);

  return (
    <Modal
      visible={visible}
      transparent
      animationType={reducedMotion ? 'none' : 'fade'}
      onRequestClose={onClose}
    >
      <Pressable
        style={styles.backdrop}
        onPress={onClose}
        accessibilityRole="button"
        accessibilityLabel="Close"
      >
        {/* Taps on the card itself don't close it. */}
        <Pressable style={styles.card} onPress={() => {}} accessible={false}>
          <Text style={styles.cardLeague}>{leagueInfo(league).name.toUpperCase()}</Text>
          <View style={styles.cardHead}>
            <Avatar player={player} size="lg" />
            <Text style={styles.cardName} numberOfLines={2}>
              {player.username} {flag}
            </Text>
          </View>
          <Text style={styles.cardRank}>{player.rank_name || 'Unranked'}</Text>
          <Text style={styles.cardElo}>
            <Text style={styles.cardEloNumber}>{player.elo ?? 0}</Text> points
          </Text>
          <Text style={styles.cardRecord}>
            {player.wins ?? 0} won · {player.losses ?? 0} lost
          </Text>
          <Pressable
            onPress={onClose}
            accessibilityRole="button"
            style={({ pressed }) => [styles.cardClose, pressed && styles.cardClosePressed]}
          >
            <Text style={styles.cardCloseText}>Close</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  avatar: { overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  initial: { fontFamily: fonts.bold },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    minHeight: 40,
    maxWidth: '100%',
    paddingVertical: 2,
    paddingLeft: 2,
    paddingRight: 8,
    borderRadius: radius.pill,
    flexShrink: 1,
  },
  chipEnd: { flexDirection: 'row-reverse', paddingLeft: 8, paddingRight: 2 },
  name: { fontFamily: fonts.semibold, fontSize: type.body, flexShrink: 1 },
  nameEnd: { textAlign: 'right' },
  flag: { fontSize: type.body },
  backdrop: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    backgroundColor: 'rgba(27, 26, 34, 0.45)',
  },
  card: {
    width: '100%',
    maxWidth: 300,
    padding: 18,
    gap: 4,
    borderRadius: radius.md,
    backgroundColor: palette.gray900,
    boxShadow: '0px 10px 28px rgba(27, 26, 34, 0.3)',
  },
  cardLeague: {
    color: palette.onDarkMuted,
    fontFamily: fonts.semibold,
    fontSize: 11.5,
    letterSpacing: 0.6,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 12, marginVertical: 8 },
  cardName: { flex: 1, color: palette.white, fontFamily: fonts.semibold, fontSize: type.large },
  cardRank: { color: palette.white, fontFamily: fonts.display, fontSize: 28, lineHeight: 32 },
  cardElo: { color: palette.white, fontFamily: fonts.regular, fontSize: type.body },
  cardEloNumber: { fontFamily: fonts.bold, fontVariant: ['tabular-nums'] },
  cardRecord: { color: palette.onDarkMuted, fontFamily: fonts.regular, fontSize: type.small, fontVariant: ['tabular-nums'] },
  cardClose: {
    marginTop: 12,
    minHeight: 44,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.25)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cardClosePressed: { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
  cardCloseText: { color: palette.white, fontFamily: fonts.semibold, fontSize: type.body },
});
