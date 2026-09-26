/**
 * The Play tab: can I play right now (the status panel), who's at the
 * table, and who's waiting. Everything comes from LiveContext, which
 * polls for the whole app; pulling down refreshes at once.
 */
import React, { useState } from 'react';

import { ConnectionBanner } from '../components/Feedback';
import { StatusPanel } from '../components/StatusPanel';
import { ActiveTableCard, QueueCard } from '../components/TableCards';
import { Button, Card, Screen, Txt } from '../components/ui';
import { useLeague } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { useSession } from '../state/SessionContext';

export function PlayScreen({ navigation }) {
  const live = useLive();
  const { league, info, tables, tableId, tableName, unreachable } = useLeague();
  const { user, chooseLeague } = useSession();
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = async () => {
    setRefreshing(true);
    await live.refresh();
    setRefreshing(false);
  };

  // The venue hasn't given this league a table yet.
  if (tables && !tableId) {
    return (
      <Screen>
        <Card>
          <Txt style={{ marginBottom: 14 }}>The {info.name} doesn't have a table set up yet.</Txt>
          <Button variant="quiet" title="Choose another league" onPress={() => navigation.navigate('SwitchLeague')} />
        </Card>
      </Screen>
    );
  }

  return (
    <Screen onRefresh={onRefresh} refreshing={refreshing}>
      <ConnectionBanner offline={live.offline || (unreachable && !tables)} />

      <StatusPanel
        status={live.matchStatus}
        problem={live.statusProblem}
        league={league}
        tableName={tableName}
        queueLength={live.queue.length}
        onJoin={live.join}
        onLeave={live.leave}
        onRecord={live.record}
        onStepDown={live.stepDown}
        onSwitchLeague={chooseLeague}
        busy={live.busy}
      />

      <ActiveTableCard
        table={live.table}
        loaded={live.loaded.table}
        league={league}
        tableName={tableName}
        currentUserId={user?.user_id}
      />

      <QueueCard queue={live.queue} loaded={live.loaded.queue} currentUsername={user?.username} />
    </Screen>
  );
}
