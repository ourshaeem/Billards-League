/**
 * One finished game: winner, score, loser, how many points moved and
 * when. Used by the Games tab and by player profiles. Port of HistoryRow
 * in Frontend/src/components/MatchHistory.jsx.
 */
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { PlayerChip } from './Player';

/**
 * "5m ago" from a count of seconds. The server works the seconds out
 * with its own clock, so a phone whose clock or timezone is off still
 * shows the right answer.
 */
function timeAgo(seconds) {
  if (typeof seconds !== 'number') return '';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(Date.now() - seconds * 1000).toLocaleDateString();
}

/**
 * "±16 points" - or, when the loser stopped at the floor of 0 and lost
 * less, "+16 / −3 points", or just "+16 points" if they lost nothing.
 */
function pointsMoved(gain, loss) {
  if (loss === gain) return `±${gain} points`;
  if (!loss) return `+${gain} points`;
  return `+${gain} / −${loss} points`;
}

/**
 * When the entry carries a "result", it's told from one player's side:
 * yours by default ("You won"), or `subject`'s when the list is another
 * player's games ("alice won").
 */
export function GameRow({ match, league, currentUserId, last = false, subject = null }) {
  const theme = useTheme();
  const { winner, loser, winner_score: won, loser_score: lost, result } = match;
  const hasScore = typeof won === 'number' && typeof lost === 'number';
  const change = match.elo_change;
  // A loser at the floor of 0 loses less than the winner gains.
  const lossChange = match.loser_elo_change ?? change;

  return (
    <View style={[styles.row, !last && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft }]}>
      <View style={styles.players}>
        <View style={styles.side}>
          <PlayerChip player={winner} league={league} size="sm" isYou={winner?.user_id === currentUserId} />
          <ResultTag win />
        </View>

        <Text
          style={[styles.score, { color: theme.textMuted }]}
          accessibilityLabel={hasScore ? `Score ${won} to ${lost}` : 'No score recorded'}
        >
          {hasScore ? (
            <>
              <Text style={{ color: theme.accentText }}>{won}</Text>–{lost}
            </>
          ) : (
            '—'
          )}
        </Text>

        <View style={[styles.side, styles.sideEnd]}>
          <PlayerChip
            player={loser}
            league={league}
            size="sm"
            align="end"
            isYou={loser?.user_id === currentUserId}
          />
          <ResultTag />
        </View>
      </View>

      <View style={styles.meta}>
        {result ? (
          <Text
            style={[
              styles.metaText,
              styles.outcome,
              { color: result === 'won' ? theme.accentText : theme.quietText },
            ]}
          >
            {subject ?? 'You'} {result === 'won' ? 'won' : 'lost'}
            {typeof change === 'number'
              ? result === 'won'
                ? ` +${change}`
                : lossChange
                  ? ` −${lossChange}`
                  : ''
              : ''}
          </Text>
        ) : typeof change === 'number' ? (
          <Text style={[styles.metaText, { color: theme.textMuted }]}>
            {pointsMoved(change, lossChange)}
          </Text>
        ) : null}
        <Text style={[styles.metaText, { color: theme.textMuted }]}>{timeAgo(match.seconds_ago)}</Text>
      </View>
    </View>
  );
}

// Win in purple, loss in gray - the same in both leagues.
function ResultTag({ win = false }) {
  const theme = useTheme();
  return (
    <View style={[styles.tag, { backgroundColor: win ? theme.accentSoft : theme.fillSoft }]}>
      <Text style={[styles.tagText, { color: win ? theme.accentText : theme.textMuted }]}>
        {win ? 'WINNER' : 'LOSER'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingVertical: 12 },
  players: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  side: { flex: 1, minWidth: 0, alignItems: 'flex-start', gap: 4 },
  sideEnd: { alignItems: 'flex-end' },
  score: {
    fontFamily: fonts.bold,
    fontSize: type.large,
    fontVariant: ['tabular-nums'],
    paddingHorizontal: 4,
  },
  tag: { paddingHorizontal: 7, paddingVertical: 1, borderRadius: radius.pill },
  tagText: { fontFamily: fonts.bold, fontSize: 10.5, letterSpacing: 0.5 },
  meta: { flexDirection: 'row', justifyContent: 'center', flexWrap: 'wrap', gap: 12, marginTop: 6 },
  metaText: { fontFamily: fonts.regular, fontSize: 12.5, fontVariant: ['tabular-nums'] },
  outcome: { fontFamily: fonts.bold },
});
