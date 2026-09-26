/**
 * The league's four tabs. The web dashboard put everything on one long
 * page; on a phone each part gets a tab:
 *
 *   Play     your status (join, leave, report a score), who's at the
 *            table, and the queue - the web app's status panel and cards
 *   Games    recent games, everyone's or yours
 *   Ladder   the league's leaderboard
 *   Profile  flag, picture, standing in both leagues, sign out
 *
 * The header carries the league's name and a Switch league button, as
 * the web masthead did.
 */
import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Feather from '@expo/vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { HeaderButton } from '../components/ui';
import { Wordmark } from '../components/Wordmark';
import { HistoryScreen } from '../screens/HistoryScreen';
import { LadderScreen } from '../screens/LadderScreen';
import { PlayScreen } from '../screens/PlayScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { useLeague } from '../state/LeagueContext';
import { fonts } from '../theme';

const Tab = createBottomTabNavigator();

// React Navigation's bar is 49 points, with a fixed 28-point box for
// each icon; what's left was too little for a 12-point label in Archivo,
// whose letters were cut off at the bottom. This leaves the label room.
// The phone's bottom safe area (the home indicator) is added on top.
const TAB_BAR_HEIGHT = 60;

const TAB_ICONS = {
  Play: 'play-circle',
  Games: 'clock',
  Ladder: 'bar-chart-2',
  Profile: 'user',
};

export function MainTabs() {
  const { theme, info } = useLeague();
  const insets = useSafeAreaInsets();

  return (
    <Tab.Navigator
      screenOptions={({ route, navigation }) => ({
        headerTitle: () => <Wordmark title={info.name} />,
        headerTitleAlign: 'left',
        headerStyle: { backgroundColor: theme.page },
        headerShadowVisible: false,
        headerRight: () => (
          <HeaderButton
            icon="repeat"
            label="Switch league"
            onPress={() => navigation.navigate('SwitchLeague')}
          />
        ),
        tabBarActiveTintColor: theme.accent,
        tabBarInactiveTintColor: theme.textMuted,
        tabBarStyle: {
          height: TAB_BAR_HEIGHT + insets.bottom,
          backgroundColor: theme.surface,
          borderTopColor: theme.line,
        },
        tabBarLabelStyle: { fontFamily: fonts.semibold, fontSize: 12, lineHeight: 15 },
        tabBarIcon: ({ color }) => <Feather name={TAB_ICONS[route.name]} color={color} size={22} />,
      })}
    >
      <Tab.Screen name="Play" component={PlayScreen} />
      <Tab.Screen name="Games" component={HistoryScreen} options={{ title: 'Games' }} />
      <Tab.Screen name="Ladder" component={LadderScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}
