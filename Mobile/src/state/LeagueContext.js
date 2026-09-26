/**
 * The chosen league, as the screens need it: its details (leagues.js),
 * the table it plays on (from GET /leagues), and its theme.
 *
 * Which table each league plays on is the venue's data, so it comes from
 * the server rather than being written into the app. It's fetched once,
 * and retried until it arrives - without it there is no table to show or
 * queue for.
 */
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

import * as api from '../api';
import { LEAGUES_RETRY_MS } from '../config';
import { isLeague, leagueInfo } from '../leagues';
import { themeFor } from '../theme';
import { useSession } from './SessionContext';

const LeagueContext = createContext(null);

export function LeagueProvider({ children }) {
  const { league } = useSession();
  // { billiards: {league_type, name, table_id, table_name}, ping_pong: {...} }
  const [tables, setTables] = useState(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    if (tables) return undefined;
    const controller = new AbortController();
    let timer;

    const load = async () => {
      const res = await api.getLeagues(controller.signal);
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && Array.isArray(res.data?.leagues)) {
        const byLeague = {};
        res.data.leagues.forEach((entry) => {
          if (isLeague(entry.league_type)) byLeague[entry.league_type] = entry;
        });
        setUnreachable(false);
        setTables(byLeague);
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
  }, [tables]);

  const value = useMemo(() => {
    const table = league && tables ? tables[league] : null;
    return {
      league,
      info: leagueInfo(league),
      tables,
      // null until GET /leagues answers, or if the league has no table.
      tableId: table?.table_id ?? null,
      tableName: table?.table_name ?? null,
      // True while the league list can't be fetched at all - the server
      // is unreachable or still waking up.
      unreachable,
      theme: themeFor(league),
    };
  }, [league, tables, unreachable]);

  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}

/** { league, info, tables, tableId, tableName, unreachable, theme } */
export function useLeague() {
  return useContext(LeagueContext);
}

/** The current league's colours and roles (theme.js). */
export function useTheme() {
  return useContext(LeagueContext).theme;
}
