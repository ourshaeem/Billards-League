/**
 * Which screens exist, decided by the session - React Navigation's
 * recommended pattern for sign-in flows. The web app's single `view`
 * variable (login / register / league / dashboard / profile) becomes:
 *
 *   Signed out           SignIn, Register        (a stack)
 *   Signed in, no league ChooseLeague
 *   Signed in, league    Main                    (tabs: Play, Games, Ladder, Profile)
 *                        Player                  (a player's profile, over the tabs)
 *                        SwitchLeague            (a modal over the tabs)
 *
 * Because the signed-out screens only exist while signed out, signing
 * out (or a session expiring) can't leave a screen behind that the back
 * button would return to.
 */
import React, { useState } from 'react';
import {
  DarkTheme,
  DefaultTheme,
  NavigationContainer,
  useNavigationContainerRef,
} from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';

import { TurnBanner } from '../components/TurnBanner';
import { Splash } from '../components/Wordmark';
import { LoginScreen } from '../screens/LoginScreen';
import { PlayerScreen } from '../screens/PlayerScreen';
import { RegisterScreen } from '../screens/RegisterScreen';
import { LeagueSelectScreen } from '../screens/LeagueSelectScreen';
import { useLeague } from '../state/LeagueContext';
import { useSession } from '../state/SessionContext';
import { fonts } from '../theme';
import { MainTabs, TAB_BAR_HEIGHT, TAB_ROUTES } from './MainTabs';

const Stack = createNativeStackNavigator();

const APP_NAME = 'Billiards & Ping Pong';

export function AppNavigation() {
  const { status, league } = useSession();
  const { theme, info } = useLeague();
  const navigationRef = useNavigationContainerRef();
  // The screen showing, for the turn banner, which isn't inside any one.
  const [routeName, setRouteName] = useState(null);
  const noteRoute = () => setRouteName(navigationRef.getCurrentRoute()?.name ?? null);

  // Reading the saved session takes a moment at launch. Showing the
  // sign-in screen meanwhile would flash it at people who are signed in.
  if (status === 'restoring') return <Splash />;

  const base = theme.scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navigationTheme = {
    ...base,
    colors: {
      ...base.colors,
      primary: theme.accent,
      background: theme.page,
      card: theme.page,
      text: theme.text,
      border: theme.line,
      notification: theme.accent,
    },
  };

  return (
    <NavigationContainer
      ref={navigationRef}
      theme={navigationTheme}
      onReady={noteRoute}
      onStateChange={noteRoute}
      // The browser tab's title, in the web preview.
      documentTitle={{ formatter: () => (league ? info.name : APP_NAME) }}
    >
      <StatusBar style={theme.statusBar} />
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          headerTitleStyle: { fontFamily: fonts.semibold, color: theme.text },
          headerTintColor: theme.accent,
          contentStyle: { backgroundColor: theme.page },
        }}
      >
        {status === 'signedOut' ? (
          <>
            <Stack.Screen name="SignIn" component={LoginScreen} />
            <Stack.Screen name="Register" component={RegisterScreen} />
          </>
        ) : !league ? (
          <Stack.Screen name="ChooseLeague" component={LeagueSelectScreen} />
        ) : (
          <>
            <Stack.Screen name="Main" component={MainTabs} />
            <Stack.Screen
              name="Player"
              component={PlayerScreen}
              options={{
                headerShown: true,
                title: '',
                headerBackTitle: 'Back',
                headerStyle: { backgroundColor: theme.page },
                headerShadowVisible: false,
              }}
            />
            <Stack.Screen
              name="SwitchLeague"
              component={LeagueSelectScreen}
              options={{ presentation: 'modal', headerShown: true, title: 'Switch league' }}
            />
          </>
        )}
      </Stack.Navigator>
      {status === 'signedIn' && league ? (
        <TurnBanner
          routeName={routeName}
          overTabs={TAB_ROUTES.includes(routeName)}
          tabBarHeight={TAB_BAR_HEIGHT}
          onGoToTable={() => navigationRef.navigate('Main', { screen: 'Play' })}
        />
      ) : null}
    </NavigationContainer>
  );
}
