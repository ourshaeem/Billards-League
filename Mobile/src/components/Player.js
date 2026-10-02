/**
 * How a player appears wherever other people can see them: picture (or
 * initial), name and flag. Tapping one opens their profile - their
 * standing in both leagues, their games, and their record against you
 * (screens/PlayerScreen.js).
 *
 * On the web a player's standing also shows on hover. Phones have no
 * hover, and the profile shows all of that and more, so a tap goes
 * straight there.
 */
import React, { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { StackActions, useNavigation } from '@react-navigation/native';

import { flagEmoji } from '../flags';
import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';

/**
 * Opens a player's profile on top of whatever is showing. A push, not a
 * navigate: from one profile you can open another, and Back retraces
 * the steps.
 */
export function useOpenPlayer() {
  const navigation = useNavigation();
  return (userId) => {
    if (userId) navigation.dispatch(StackActions.push('Player', { userId }));
  };
}

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
 * Avatar, name and flag. Tapping opens the player's profile.
 */
export function PlayerChip({ player, league, size = 'md', align = 'start', isYou = false }) {
  const theme = useTheme();
  const openPlayer = useOpenPlayer();
  if (!player) return null;

  const flag = flagEmoji(player.country_flag);
  const end = align === 'end';

  return (
    <Pressable
      onPress={() => openPlayer(player.user_id)}
      accessibilityRole="button"
      accessibilityLabel={`${player.username}${isYou ? ', you' : ''}`}
      accessibilityHint="Opens their profile and games"
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
        style={[styles.name, { color: isYou ? theme.accentText : theme.text }, end && styles.nameEnd]}
      >
        {player.username}
      </Text>
      {flag ? <Text style={styles.flag}>{flag}</Text> : null}
    </Pressable>
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
});
