/**
 * Another player's profile: who they are, where they stand in both
 * leagues, their games - against everyone, against one opponent, and
 * against you.
 *
 * Opened by clicking a player anywhere (see OpenPlayerContext). Their
 * real name is never here: the server doesn't send it to anyone else.
 */
import React, { useEffect, useState } from 'react';
import { ArrowLeft, History, Swords, Users } from 'lucide-react';

import * as api from '../api.js';
import { flagEmoji } from '../flags.js';
import { LEAGUE_ORDER, LEAGUES } from '../leagues.js';
import { BadgesCard } from './Badges.jsx';
import { HistoryRow } from './MatchHistory.jsx';
import { Avatar } from './Player.jsx';

const GAMES_LIMIT = 30;
const HEAD_TO_HEAD_LIMIT = 10;

export function PlayerProfile({ userId, league: startLeague, currentUserId, onBack }) {
  const [league, setLeague] = useState(startLeague || LEAGUE_ORDER[0]);
  const [player, setPlayer] = useState(null);
  const [problem, setProblem] = useState(null);
  const isYou = userId === currentUserId;

  useEffect(() => {
    const controller = new AbortController();
    api.getPlayer(userId, controller.signal).then((res) => {
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && res.data?.player) setPlayer(res.data.player);
      else setProblem(res.message);
    });
    return () => controller.abort();
  }, [userId]);

  if (problem) {
    return (
      <main className="profile-shell">
        <BackButton onBack={onBack} />
        <section className="card">
          <p className="empty">{problem}</p>
        </section>
      </main>
    );
  }

  if (!player) {
    return (
      <main className="profile-shell">
        <BackButton onBack={onBack} />
        <section className="card">
          <p className="empty">Loading their profile...</p>
        </section>
      </main>
    );
  }

  const flag = flagEmoji(player.country_flag);

  return (
    <main className="profile-shell profile-shell-wide" aria-labelledby="player-title">
      <BackButton onBack={onBack} />

      <section className="card">
        <div className="profile-head">
          <Avatar player={player} size="xl" label={`Picture of ${player.username}`} />
          <div>
            <h2 className="card-title" id="player-title">
              {player.username}
              {flag && <span className="profile-flag"> {flag}</span>}
            </h2>
            {isYou && <p className="muted small">This is how other players see you.</p>}
          </div>
        </div>
        <StandingsTable leagues={player.leagues} highlight={league} />
      </section>

      <div
        className="segmented profile-league-switch"
        role="group"
        aria-label="Which league's games to show"
      >
        {LEAGUE_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            className="segmented-option"
            aria-pressed={league === key}
            onClick={() => setLeague(key)}
          >
            {LEAGUES[key].name}
          </button>
        ))}
      </div>

      <BadgesCard
        key={`badges-${userId}-${league}`}
        userId={userId}
        league={league}
        title={isYou ? 'Your badges' : `${player.username}'s badges`}
      />

      {/* Keyed so a change of league starts each part over, rather than
          showing one league's numbers under the other's name. */}
      <PlayerGames
        key={`${userId}-${league}`}
        player={player}
        league={league}
        currentUserId={currentUserId}
      />
    </main>
  );
}

function BackButton({ onBack }) {
  return (
    <button type="button" className="btn btn-quiet btn-small profile-back" onClick={onBack}>
      <ArrowLeft size={15} aria-hidden="true" />
      Back
    </button>
  );
}

function StandingsTable({ leagues, highlight }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">League</th>
            <th scope="col">Rank</th>
            <th scope="col">Points</th>
            <th scope="col">W&ndash;L</th>
          </tr>
        </thead>
        <tbody>
          {LEAGUE_ORDER.map((key) => {
            const standing = leagues?.[key];
            return (
              <tr key={key} data-self={key === highlight ? 'true' : 'false'}>
                <th scope="row" className="standing-league">
                  {LEAGUES[key].name}
                </th>
                <td>{standing?.rank_name ?? 'Unranked'}</td>
                <td className="elo">{standing?.elo ?? 0}</td>
                <td className="record">
                  <span className="record-win">{standing?.wins ?? 0}</span>
                  <span className="muted"> &ndash; </span>
                  <span className="record-loss">{standing?.losses ?? 0}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Everything about one player's games in one league: against you, their
 * record against each opponent, and the games themselves - all of them,
 * or just those against the opponent picked from the record.
 */
function PlayerGames({ player, league, currentUserId }) {
  const userId = player.user_id;
  const isYou = userId === currentUserId;
  const [opponents, setOpponents] = useState(null);
  const [vsYou, setVsYou] = useState(null);
  const [against, setAgainst] = useState(null);
  const [problem, setProblem] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      api.getPlayerOpponents(userId, league, signal),
      !isYou && currentUserId
        ? api.getPlayerMatches(
            userId,
            league,
            { limit: HEAD_TO_HEAD_LIMIT, opponentId: currentUserId },
            signal,
          )
        : null,
    ]).then(([opponentsRes, vsYouRes]) => {
      if (signal.aborted || opponentsRes.aborted) return;
      if (!opponentsRes.ok) {
        setProblem(opponentsRes.message);
        return;
      }
      setOpponents(opponentsRes.data?.opponents ?? []);
      if (vsYouRes?.ok) setVsYou(vsYouRes.data?.matches ?? []);
    });
    return () => controller.abort();
  }, [userId, league, isYou, currentUserId]);

  if (problem) {
    return (
      <section className="card">
        <p className="empty">{problem}</p>
      </section>
    );
  }

  const yourRecord = opponents?.find((o) => o.opponent?.user_id === currentUserId);

  return (
    <>
      {!isYou && currentUserId && (
        <section className="card" aria-labelledby="vs-you-heading">
          <div className="card-head">
            <h2 className="card-title" id="vs-you-heading">
              <Swords size={18} aria-hidden="true" className="card-title-icon" />
              You vs {player.username}
            </h2>
          </div>
          {opponents === null || vsYou === null ? (
            <p className="empty">Loading your games against each other...</p>
          ) : !yourRecord ? (
            <p className="empty">
              You haven&rsquo;t played {player.username} in the {LEAGUES[league].name} yet.
            </p>
          ) : (
            <>
              <p
                className="h2h-score"
                aria-label={`You ${yourRecord.losses}, ${player.username} ${yourRecord.wins}`}
              >
                <span className="h2h-side">
                  <span className="h2h-number" data-leading={yourRecord.losses > yourRecord.wins}>
                    {yourRecord.losses}
                  </span>
                  <span className="h2h-label">You</span>
                </span>
                <span className="h2h-dash" aria-hidden="true">
                  &ndash;
                </span>
                <span className="h2h-side">
                  <span className="h2h-number" data-leading={yourRecord.wins > yourRecord.losses}>
                    {yourRecord.wins}
                  </span>
                  <span className="h2h-label">{player.username}</span>
                </span>
              </p>
              <ol className="history-list">
                {vsYou.map((match) => (
                  <HistoryRow
                    key={match.match_id}
                    match={match}
                    league={league}
                    currentUserId={currentUserId}
                    subject={player.username}
                  />
                ))}
              </ol>
            </>
          )}
        </section>
      )}

      <section className="card" aria-labelledby="opponents-heading">
        <div className="card-head">
          <h2 className="card-title" id="opponents-heading">
            <Users size={18} aria-hidden="true" className="card-title-icon" />
            {isYou
              ? 'Your record against everyone'
              : `${player.username}'s record against everyone`}
          </h2>
        </div>
        {opponents === null && <p className="empty">Loading their record...</p>}
        {opponents?.length === 0 && (
          <p className="empty">No games in the {LEAGUES[league].name} yet.</p>
        )}
        {opponents?.length > 0 && (
          <>
            <ul className="opponent-list">
              {opponents.map(({ opponent, wins, losses }) => (
                <li key={opponent.user_id}>
                  <button
                    type="button"
                    className="opponent-row"
                    aria-pressed={against?.user_id === opponent.user_id}
                    onClick={() =>
                      setAgainst((current) =>
                        current?.user_id === opponent.user_id ? null : opponent,
                      )
                    }
                  >
                    <Avatar player={opponent} size="sm" />
                    <span className="opponent-name">
                      {opponent.user_id === currentUserId ? 'You' : opponent.username}
                    </span>
                    <span className="record opponent-record">
                      <span className="record-win">{wins}</span>
                      <span className="muted"> &ndash; </span>
                      <span className="record-loss">{losses}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="small muted card-foot">
              Wins first, from {isYou ? 'your' : `${player.username}'s`} side. Pick someone to see
              just the games between them.
            </p>
          </>
        )}
      </section>

      {/* Keyed by the opponent picked, so a new pick starts from "Loading"
          rather than showing the last pick's games under the new name. */}
      <GamesCard
        key={against?.user_id ?? 'everyone'}
        player={player}
        league={league}
        currentUserId={currentUserId}
        against={against}
        onShowAll={() => setAgainst(null)}
      />
    </>
  );
}

/** "alice's games", "Your games against bob", "alice's games against you". */
function gamesTitle(subject, opponentName) {
  const whose = subject ? `${subject}'s` : 'Your';
  return opponentName ? `${whose} games against ${opponentName}` : `${whose} games`;
}

function GamesCard({ player, league, currentUserId, against, onShowAll }) {
  const [games, setGames] = useState(null);
  const [problem, setProblem] = useState(null);
  const userId = player.user_id;
  const againstId = against?.user_id ?? null;
  const subject = userId === currentUserId ? null : player.username;

  useEffect(() => {
    const controller = new AbortController();
    api
      .getPlayerMatches(
        userId,
        league,
        { limit: GAMES_LIMIT, opponentId: againstId ?? undefined },
        controller.signal,
      )
      .then((res) => {
        if (controller.signal.aborted || res.aborted) return;
        if (res.ok) setGames(res.data?.matches ?? []);
        else setProblem(res.message);
      });
    return () => controller.abort();
  }, [userId, league, againstId]);

  const opponentName = againstId === currentUserId ? 'you' : against?.username;

  return (
    <section className="card" aria-labelledby="games-heading">
      <div className="card-head">
        <h2 className="card-title" id="games-heading">
          <History size={18} aria-hidden="true" className="card-title-icon" />
          {gamesTitle(subject, against ? opponentName : null)}
        </h2>
        {against && (
          <button type="button" className="btn btn-quiet btn-small" onClick={onShowAll}>
            Show all games
          </button>
        )}
      </div>

      {problem && <p className="empty">{problem}</p>}
      {!problem && games === null && <p className="empty">Loading games...</p>}
      {games?.length === 0 && <p className="empty">No finished games to show.</p>}
      {games?.length > 0 && (
        <ol className="history-list">
          {games.map((match) => (
            <HistoryRow
              key={match.match_id}
              match={match}
              league={league}
              currentUserId={currentUserId}
              subject={subject}
            />
          ))}
        </ol>
      )}
    </section>
  );
}
