/**
 * The two reference panels: who's waiting, and who's on top. Any name in
 * either opens that player's profile.
 *
 * Both distinguish "still loading" from "genuinely empty". The old
 * version showed "Loading leaderboard..." forever when the request had
 * actually failed, which reads as a hang rather than a problem.
 */
import React, { useState } from 'react';
import { Trophy, Users } from 'lucide-react';

import { RemoveButton, RemoveConfirm } from './AdminControls.jsx';
import { NameBadge } from './Badges.jsx';
import { PlayerChip, PlayerLink } from './Player.jsx';

/**
 * Where someone whose turn has come stands: asked, or confirmed - and,
 * in a league with more than one table, at which.
 */
function TurnTag({ entry, showTable }) {
  if (!entry.called) return null;
  const where = showTable && entry.table_name ? ` - ${entry.table_name}` : '';
  return entry.confirmed ? (
    <span className="queue-tag" data-tag="here">
      here{where}
    </span>
  ) : (
    <span className="queue-tag" data-tag="up">
      up{where || ' - confirming'}
    </span>
  );
}

/**
 * A league's queue, split into its lines when it has more than one table:
 * the line for whichever table frees up first, then one for each table
 * someone chose. queue_position is each player's place in their own line.
 * [{key, title, entries}], lines with nobody in them left out.
 */
function linesOf(queue, tables) {
  const lines = [{ key: 'any', title: 'First available table', entries: [] }];
  (tables || []).forEach((t) => lines.push({ key: t.table_id, title: t.table_name, entries: [] }));
  queue.forEach((entry) => {
    const key = entry.target_table_id ?? 'any';
    let line = lines.find((l) => l.key === key);
    if (!line) {
      line = { key, title: entry.target_table_name || 'Another table', entries: [] };
      lines.push(line);
    }
    line.entries.push(entry);
  });
  return lines.filter((l) => l.entries.length > 0);
}

/**
 * onRemove is given for the organiser only: each waiting player then has
 * a Remove button, which asks first. tables (the league's, when it has
 * more than one) splits the queue into its lines.
 */
export function QueueCard({
  queue,
  loaded,
  currentUsername,
  onRemove = null,
  busy = false,
  manyTables = false,
  tables = null,
}) {
  // user_id of the player the organiser is asking to remove.
  const [asking, setAsking] = useState(null);
  const lines = manyTables ? linesOf(queue, tables) : [{ key: 'any', title: null, entries: queue }];

  const row = (player, index) => {
    const isYou = currentUsername && player.username === currentUsername;
    const removable = Boolean(onRemove && player.user_id);
    const askingHere = removable && asking === player.user_id;
    const place = player.queue_position ?? index + 1;
    return (
      <li
        className="queue-row"
        key={`${player.username}-${player.user_id}`}
        data-next={place === 1 || player.called ? 'true' : 'false'}
      >
        <span className="queue-pos" aria-hidden="true">
          {place}
        </span>
        <span className="queue-name">
          <PlayerLink userId={player.user_id} name={player.username} isYou={isYou} />
          {isYou && <span className="tag-you">you</span>}
        </span>
        {player.called ? (
          <TurnTag entry={player} showTable={manyTables} />
        ) : (
          place === 1 && <span className="up-next">up next</span>
        )}
        {removable && (
          <RemoveButton
            id={`remove-queued-${player.user_id}`}
            name={player.username}
            place="the queue"
            expanded={askingHere}
            controls={`remove-queued-${player.user_id}-confirm`}
            onClick={() => setAsking(askingHere ? null : player.user_id)}
          />
        )}
        {askingHere && (
          <RemoveConfirm
            id={`remove-queued-${player.user_id}-confirm`}
            triggerId={`remove-queued-${player.user_id}`}
            question={`Take ${player.username} out of the queue?`}
            consequence={
              player.called
                ? "It's their turn, so the next in line is up instead."
                : 'They lose their place in line.'
            }
            busy={busy}
            onCancel={() => setAsking(null)}
            onConfirm={async () => {
              await onRemove(player);
              setAsking(null);
            }}
          />
        )}
      </li>
    );
  };

  return (
    <section className="card" aria-labelledby="queue-heading">
      <div className="card-head">
        <h2 className="card-title" id="queue-heading">
          <Users size={18} aria-hidden="true" style={{ marginRight: 8, verticalAlign: '-3px' }} />
          Waiting to play
        </h2>
        <span className="count-pill">
          {queue.length} {queue.length === 1 ? 'player' : 'players'}
        </span>
      </div>

      {!loaded && <p className="empty">Checking the queue...</p>}

      {loaded && queue.length === 0 && (
        <p className="empty">Nobody is waiting. Join and you're first up.</p>
      )}

      {loaded &&
        queue.length > 0 &&
        lines.map((line) => (
          <div className="queue-line" key={line.key}>
            {line.title && (
              <h3 className="queue-line-title">
                {line.title}
                <span className="queue-line-count">{line.entries.length} waiting</span>
              </h3>
            )}
            <ol className="queue-list" aria-label={line.title ? `Waiting for ${line.title}` : undefined}>
              {line.entries.map(row)}
            </ol>
          </div>
        ))}

      <p className="small muted" style={{ marginTop: 16 }}>
        {manyTables
          ? "Each table takes the next player who chose it, and only then the next who'll play anywhere. The winner keeps the table. When it's your turn, you have a minute to say you're here."
          : "The winner keeps the table and plays whoever is next in line. When it's your turn, you have a minute to say you're here."}
      </p>
    </section>
  );
}

/** A ladder row as a player card, so the ladder can draw it like everywhere else. */
function asCard(row, league) {
  return {
    user_id: row.user_id,
    username: row.username,
    country_flag: row.country_flag,
    profile_picture: row.profile_picture,
    league_type: league.game,
    league_id: league.league_id,
    elo: row.elo_rating,
    rank_name: row.rank_name,
    wins: row.total_wins,
    losses: row.total_losses,
  };
}

export function LeaderboardCard({ players, loaded, league, currentUsername }) {
  return (
    <section className="card" aria-labelledby="ladder-heading">
      <div className="card-head">
        <h2 className="card-title" id="ladder-heading">
          <Trophy size={18} aria-hidden="true" style={{ marginRight: 8, verticalAlign: '-3px' }} />
          League ladder
        </h2>
      </div>

      {!loaded && <p className="empty">Loading the ladder...</p>}

      {loaded && players.length === 0 && (
        <p className="empty">No games played yet. The first result starts the ladder.</p>
      )}

      {loaded && players.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Player</th>
                <th scope="col">Points</th>
                <th scope="col">W&ndash;L</th>
                <th scope="col">Win rate</th>
              </tr>
            </thead>
            <tbody>
              {players.map((player, index) => {
                const played = (player.total_wins || 0) + (player.total_losses || 0);
                const winRate = played > 0 ? Math.round((player.total_wins / played) * 100) : null;
                const isYou = currentUsername && player.username === currentUsername;

                return (
                  <tr key={player.username} data-self={isYou ? 'true' : 'false'}>
                    <td>{index + 1}</td>
                    <td className="ladder-player">
                      <PlayerChip
                        player={asCard(player, league)}
                        league={league}
                        size="sm"
                        isYou={isYou}
                      />
                      <NameBadge badge={player.badge} size={20} />
                      <span className="rank-name">{player.rank_name || 'Unranked'}</span>
                    </td>
                    <td className="elo">{player.elo_rating}</td>
                    <td className="record">
                      <span className="record-win">{player.total_wins}</span>
                      <span className="muted"> &ndash; </span>
                      <span className="record-loss">{player.total_losses}</span>
                    </td>
                    {/* A win rate off zero games would read as 0%, which is
                        harsher than the truth: they simply haven't played. */}
                    <td>
                      {winRate === null ? <span className="muted">&mdash;</span> : `${winRate}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
