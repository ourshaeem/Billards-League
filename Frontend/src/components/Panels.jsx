/**
 * The two reference panels: who's waiting, and who's on top.
 *
 * Both distinguish "still loading" from "genuinely empty". The old
 * version showed "Loading leaderboard..." forever when the request had
 * actually failed, which reads as a hang rather than a problem.
 *
 * Above them sits the king banner: who holds the table and how long
 * they've held it.
 */
import React from 'react';
import { Crown, Flame, Trophy, Users } from 'lucide-react';

export function KingBanner({ table, currentUsername }) {
  // Nothing to say until the first answer, and a one-line card that
  // flickers in and out would be worse than waiting a poll.
  if (!table) return null;

  const king = table.current_king;
  const streak = table.current_streak || 0;
  const record = table.table_record_streak || 0;
  const isYou = Boolean(king) && king === currentUsername;
  const onRecordRun = Boolean(king) && streak > 0 && streak >= record;

  return (
    <section className="card king-banner" aria-label="Who holds the table">
      <Crown
        size={26}
        aria-hidden="true"
        className="king-crown"
        data-empty={king ? 'false' : 'true'}
      />

      <div className="king-main">
        {king ? (
          <>
            <p className="king-name">
              {king}
              {isYou && <span className="tag-you">you</span>}
              <span className="king-label">holds the table</span>
            </p>
            <p className="small muted">
              {table.challenger
                ? `Playing ${table.challenger} now.`
                : 'Waiting for a challenger.'}
            </p>
          </>
        ) : (
          <>
            <p className="king-name king-name-empty">Nobody holds the table</p>
            <p className="small muted">Win a game to take it.</p>
          </>
        )}
      </div>

      <div className="king-stats">
        {king && (
          <span className="streak-pill" data-record={onRecordRun ? 'true' : 'false'}>
            <Flame size={15} aria-hidden="true" />
            {streak} {streak === 1 ? 'win' : 'wins'} in a row
          </span>
        )}
        {/* "Record: 0" before anyone has won says nothing useful. */}
        {record > 0 && (
          <span className="small muted king-record">
            {onRecordRun ? 'Table record - on it now' : `Table record: ${record}`}
          </span>
        )}
      </div>
    </section>
  );
}

export function QueueCard({ queue, loaded, currentUsername }) {
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

      {loaded && queue.length > 0 && (
        <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {queue.map((player, index) => {
            const isYou = currentUsername && player.username === currentUsername;
            return (
              <li
                className="queue-row"
                key={`${player.username}-${player.queue_position}`}
                data-next={index === 0 ? 'true' : 'false'}
              >
                <span className="queue-pos" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="queue-name">
                  {player.username}
                  {isYou && <span className="tag-you">you</span>}
                </span>
                {index === 0 && <span className="up-next">up next</span>}
              </li>
            );
          })}
        </ol>
      )}

      <p className="small muted" style={{ marginTop: 16 }}>
        The winner keeps the table and plays whoever is next in line.
      </p>
    </section>
  );
}

export function LeaderboardCard({ players, loaded, currentUsername }) {
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
                    <td>
                      {player.username}
                      {isYou && <span className="tag-you">you</span>}
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
                    <td>{winRate === null ? <span className="muted">&mdash;</span> : `${winRate}%`}</td>
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
