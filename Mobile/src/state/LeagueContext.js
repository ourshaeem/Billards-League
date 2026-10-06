/**
 * The leagues, and the one chosen, as the screens need them.
 *
 * Every league - CCNY Billiards, John Jay Ping Pong and the rest - comes
 * from GET /leagues/directory: its name, school, game, colours, tables,
 * and read_only (true until the signed-in player has entered its PIN).
 * That's the league's data, not the app's, so it isn't written in here.
 * It's fetched whenever someone signs in or out (read_only is theirs),
 * when a screen asks (reload: a PIN entered, a table added), and retried
 * until it arrives - without it there is no league to show.
 *
 * The chosen league's theme is built from its colours (theme.js).
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import * as api from '../api';
import { LEAGUES_RETRY_MS } from '../config';
import { gameInfo } from '../leagues';
import { themeFor } from '../theme';
import { useAppearance } from './AppearanceContext';
import { useSession } from './SessionContext';

const LeagueContext = createContext(null);
const NO_TABLES = [];

export function LeagueProvider({ children }) {
  const { status, user, leagueId, chooseLeague } = useSession();
  const { scheme } = useAppearance();
  const userId = status === 'signedIn' ? (user?.user_id ?? null) : null;

  // The list belongs to whoever was signed in when it loaded, so it's kept
  // with them: a list from before a sign-in is never shown after it.
  const [directory, setDirectory] = useState({ forUser: undefined, leagues: null });
  const leagues = directory.forUser === userId ? directory.leagues : null;
  const [unreachable, setUnreachable] = useState(false);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (status === 'restoring') return undefined;
    const controller = new AbortController();
    const forUser = userId;
    let timer;

    const load = async () => {
      const res = await api.getLeagueDirectory(controller.signal);
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && Array.isArray(res.data?.leagues)) {
        setUnreachable(false);
        setDirectory({ forUser, leagues: res.data.leagues });
        return;
      }
      setUnreachable(res.kind === api.ErrorKind.NETWORK);
      timer = setTimeout(load, LEAGUES_RETRY_MS);
    };
    load();

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [status, userId, version]);

  // A league saved as "billiards" / "ping_pong" by the app before there
  // were schools is CCNY's league of that game; one no longer listed means
  // choosing again.
  useEffect(() => {
    if (!leagues || leagueId === null) return;
    if (typeof leagueId === 'string') {
      const match = leagues.find((l) => l.legacy_key === leagueId);
      chooseLeague(match ? match.league_id : null);
    } else if (!leagues.some((l) => l.league_id === leagueId)) {
      chooseLeague(null);
    }
  }, [leagues, leagueId, chooseLeague]);

  /** One league's entry, replaced - as the PIN and table screens get it back. */
  const replaceLeague = useCallback((updated) => {
    if (!updated?.league_id) return;
    setDirectory((d) => ({
      ...d,
      leagues: d.leagues?.map((l) => (l.league_id === updated.league_id ? updated : l)) ?? null,
    }));
  }, []);

  /** What the latest status says about a league's PIN, kept on the list too. */
  const noticeReadOnly = useCallback((id, readOnly) => {
    setDirectory((d) =>
      d.leagues?.some((l) => l.league_id === id && l.read_only !== readOnly)
        ? { ...d, leagues: d.leagues.map((l) => (l.league_id === id ? { ...l, read_only: readOnly } : l)) }
        : d,
    );
  }, []);

  const value = useMemo(() => {
    const league =
      typeof leagueId === 'number' ? (leagues?.find((l) => l.league_id === leagueId) ?? null) : null;
    return {
      // The chosen league's id - set before the list has loaded, when
      // league is still null.
      leagueId: typeof leagueId === 'number' ? leagueId : null,
      league,
      // How the league's game is played and scored (leagues.js).
      info: gameInfo(league?.game),
      // Every league, or null until GET /leagues/directory answers.
      leagues,
      // The chosen league's tables in use: [{table_id, table_name}].
      tables: league?.tables ?? NO_TABLES,
      // True while the league list can't be fetched at all - the server
      // is unreachable or still waking up.
      unreachable,
      theme: themeFor(league, scheme),
      reload,
      replaceLeague,
      noticeReadOnly,
    };
  }, [leagueId, leagues, unreachable, scheme, reload, replaceLeague, noticeReadOnly]);

  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}

/** { leagueId, league, info, leagues, tables, unreachable, theme, reload, replaceLeague, noticeReadOnly } */
export function useLeague() {
  return useContext(LeagueContext);
}

/** The current league's colours and roles (theme.js), by day or by night. */
export function useTheme() {
  return useContext(LeagueContext).theme;
}
