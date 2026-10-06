/**
 * The Play tab: can I play right now (the status panel), who's at the
 * league's tables, and who's waiting. Everything comes from LiveContext,
 * which polls for the whole app; pulling down refreshes at once.
 *
 * Anyone can look at any league. Until the player enters a league's PIN
 * the status panel asks for it instead of offering Join.
 */
import React, { useState } from 'react';
import { View } from 'react-native';

import { ConnectionBanner } from '../components/Feedback';
import { StatusPanel } from '../components/StatusPanel';
import { QueueCard, TablesCard } from '../components/TableCards';
import { Button, Card, Screen, Txt } from '../components/ui';
import { useLeague } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { useSession } from '../state/SessionContext';

export function PlayScreen({ navigation }) {
  const live = useLive();
  const { league, leagues, tables, unreachable } = useLeague();
  const { user, isAdmin, chooseLeague } = useSession();
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = async () => {
    setRefreshing(true);
    await live.refresh();
    setRefreshing(false);
  };

  // The organiser hasn't given this league a table yet.
  if (league && tables.length === 0) {
    return (
      <Screen>
        <Card>
          <Txt style={{ marginBottom: 14 }}>{league.name} doesn't have a table set up yet.</Txt>
          <View style={{ gap: 10 }}>
            {isAdmin ? (
              <Button title="Add a table" icon="plus" onPress={() => navigation.navigate('LeagueSettings')} />
            ) : null}
            <Button variant="quiet" title="Choose another league" onPress={() => navigation.navigate('SwitchLeague')} />
          </View>
        </Card>
      </Screen>
    );
  }

  return (
    <Screen onRefresh={onRefresh} refreshing={refreshing}>
      <ConnectionBanner offline={live.offline || (unreachable && !leagues)} />

      <StatusPanel
        status={live.matchStatus}
        problem={live.statusProblem}
        league={league}
        leagues={leagues}
        manyTables={tables.length > 1}
        readOnly={live.readOnly}
        onUnlock={live.unlock}
        queueLength={live.queue.length}
        onJoin={live.join}
        onLeave={live.leave}
        onConfirm={live.confirm}
        onRecord={live.record}
        onCancelGame={live.cancelGame}
        onKeepPlaying={live.keepPlaying}
        onStepDown={live.stepDown}
        onSwitchLeague={chooseLeague}
        busy={live.busy}
      />

      <TablesCard
        tables={live.tables}
        loaded={live.loaded.tables}
        league={league}
        currentUserId={user?.user_id}
        onRemove={isAdmin ? live.removeFromTable : null}
        busy={live.busy}
      />

      <QueueCard
        queue={live.queue}
        loaded={live.loaded.queue}
        currentUsername={user?.username}
        onRemove={isAdmin ? live.removeFromQueue : null}
        busy={live.busy}
        manyTables={tables.length > 1}
      />

      {isAdmin && league ? (
        <Button
          variant="quiet"
          icon="settings"
          title={`Manage ${league.name}`}
          accessibilityHint="The league's PIN and tables"
          onPress={() => navigation.navigate('LeagueSettings')}
          style={{ alignSelf: 'flex-start', marginTop: 4 }}
        />
      ) : null}
    </Screen>
  );
}
