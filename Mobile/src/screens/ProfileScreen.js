/**
 * The Profile tab: pick a flag, set a picture, see where you stand in
 * both leagues, and sign out. Port of ProfileSettings.jsx.
 *
 * Problems appear beside the field they concern - both the ones caught
 * here and the ones the server sends back (it names the field).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useIsFocused } from '@react-navigation/native';
import Feather from '@expo/vector-icons/Feather';

import * as api from '../api';
import { CountryPicker } from '../components/CountryPicker';
import { Avatar } from '../components/Player';
import { Button, Card, Field, FieldError, Screen, Txt } from '../components/ui';
import { flagEmoji } from '../flags';
import { LEAGUE_ORDER, LEAGUES } from '../leagues';
import { useLeague } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { useSession } from '../state/SessionContext';
import { useToast } from '../state/ToastContext';
import { pointsText } from '../format';
import { fonts, radius, type } from '../theme';

// The database column's limit; the server enforces it too.
const MAX_PICTURE_LINK = 512;
const WEB_LINK = /^https?:\/\/[^\s/]+\S*$/i;
// How long typing must pause before the preview tries the link.
const PREVIEW_DELAY_MS = 600;

function pictureProblem(link) {
  if (!link) return null;
  if (link.length > MAX_PICTURE_LINK) return `Picture links can be at most ${MAX_PICTURE_LINK} characters.`;
  if (!WEB_LINK.test(link)) return 'Use a link that starts with https:// (or http://).';
  return null;
}

export function ProfileScreen() {
  const { signOut } = useSession();
  const { gamesVersion } = useLive();
  const focused = useIsFocused();
  const [profile, setProfile] = useState(null);
  const [problem, setProblem] = useState(null);

  // Reloaded whenever the tab comes into view or a game ends, so the
  // standings reflect the games just played.
  useEffect(() => {
    if (!focused) return undefined;
    const controller = new AbortController();
    api.getProfile(controller.signal).then((res) => {
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && res.data?.profile) {
        setProfile(res.data.profile);
        setProblem(null);
      } else if (res.kind !== api.ErrorKind.AUTH) {
        setProblem(res.message);
      }
    });
    return () => controller.abort();
  }, [focused, gamesVersion]);

  return (
    <Screen>
      {profile ? (
        <ProfileForm key={profile.user_id} profile={profile} onSaved={setProfile} />
      ) : (
        <Card>
          <Txt muted>{problem ? `${problem} Try again in a moment.` : 'Loading your profile...'}</Txt>
        </Card>
      )}
      {profile ? <Standing profile={profile} /> : null}
      <Button variant="quiet" icon="log-out" title="Sign out" onPress={signOut} style={styles.signOut} />
    </Screen>
  );
}

function ProfileForm({ profile, onSaved }) {
  const { theme } = useLeague();
  const toast = useToast();
  const [values, setValues] = useState({
    country_flag: profile.country_flag || '',
    profile_picture: profile.profile_picture || '',
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [countries, setCountries] = useState(null);

  const link = values.profile_picture.trim();

  // The preview follows the link once typing pauses, rather than trying
  // every half-typed address on the way.
  const [previewLink, setPreviewLink] = useState(link);
  useEffect(() => {
    const timer = setTimeout(() => setPreviewLink(link), PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [link]);
  const preview = {
    username: profile.username,
    profile_picture: previewLink && !pictureProblem(previewLink) ? previewLink : null,
  };

  // The picker's list, fetched with the form so the chosen country shows
  // by name ("Canada", not "CA") from the start. Returns whether it loaded.
  const loadCountries = useCallback(async (signal) => {
    const res = await api.getCountries(signal);
    if (signal?.aborted || res.aborted) return false;
    if (res.ok && Array.isArray(res.data?.countries)) {
      setCountries(res.data.countries);
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadCountries(controller.signal);
    return () => controller.abort();
  }, [loadCountries]);

  // If the list didn't load with the form, opening the picker tries again.
  const openPicker = useCallback(async () => {
    setPickerOpen(true);
    if (countries || (await loadCountries())) return;
    setPickerOpen(false);
    toast.push("Couldn't load the list of countries. Try again in a moment.", 'error');
  }, [countries, loadCountries, toast]);

  const countryName =
    countries?.find((c) => c.code === values.country_flag)?.name ?? values.country_flag;

  const save = async () => {
    const problem = pictureProblem(link);
    if (problem) {
      setErrors({ profile_picture: problem });
      return;
    }
    setErrors({});
    setBusy(true);
    const res = await api.updateProfile({
      country_flag: values.country_flag || null,
      profile_picture: link || null,
    });
    setBusy(false);

    if (!res.ok) {
      const field = res.data?.field;
      if (field) setErrors({ [field]: res.message });
      else if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
      return;
    }
    onSaved(res.data.profile);
    toast.push('Profile saved.', 'success');
  };

  const savedFlag = flagEmoji(profile.country_flag);

  return (
    <Card>
      <View style={[styles.head, { borderBottomColor: theme.line }]}>
        <Avatar player={preview} size="xl" label={`Picture for ${profile.username}`} />
        <View style={styles.headText}>
          <Txt variant="title" accessibilityRole="header">
            {profile.username}
            {savedFlag ? ` ${savedFlag}` : ''}
          </Txt>
          <Txt variant="small" muted>
            {profile.first_name} {profile.last_name}
          </Txt>
        </View>
      </View>

      <View style={styles.field}>
        <Text style={[styles.label, { color: theme.quietText }]}>Country flag</Text>
        <Pressable
          onPress={openPicker}
          accessibilityRole="button"
          accessibilityLabel={`Country flag: ${values.country_flag ? countryName : 'no flag'}`}
          accessibilityHint="Opens the list of countries"
          style={({ pressed }) => [
            styles.select,
            {
              borderColor: errors.country_flag ? theme.danger : theme.inputBorder,
              backgroundColor: pressed ? theme.accentWash : theme.surface,
            },
          ]}
        >
          <Text style={[styles.selectText, { color: theme.text }]} numberOfLines={1}>
            {values.country_flag ? `${flagEmoji(values.country_flag)}  ${countryName}` : 'No flag'}
          </Text>
          <Feather name="chevron-down" size={18} color={theme.textMuted} />
        </Pressable>
        <FieldError message={errors.country_flag} />
      </View>

      <Field
        label="Profile picture link"
        value={values.profile_picture}
        onChangeText={(text) => {
          setValues((v) => ({ ...v, profile_picture: text }));
          setErrors((prev) => (prev.profile_picture ? { ...prev, profile_picture: null } : prev));
        }}
        error={errors.profile_picture}
        hint="Paste a link to an image. Leave it empty to show your initial instead."
        placeholder="https://..."
        keyboardType="url"
        inputMode="url"
        autoCapitalize="none"
        autoCorrect={false}
        textContentType="URL"
      />

      <Button title={busy ? 'Saving...' : 'Save profile'} size="lg" onPress={save} busy={busy} />

      <CountryPicker
        visible={pickerOpen}
        countries={countries}
        selected={values.country_flag}
        onSelect={(code) => {
          setValues((v) => ({ ...v, country_flag: code }));
          setErrors((prev) => (prev.country_flag ? { ...prev, country_flag: null } : prev));
        }}
        onClose={() => setPickerOpen(false)}
      />
    </Card>
  );
}

function Standing({ profile }) {
  const { theme } = useLeague();
  return (
    <Card title="Where you stand">
      {LEAGUE_ORDER.map((key, index) => {
        const standing = profile.leagues?.[key];
        return (
          <View
            key={key}
            accessible
            accessibilityLabel={`${LEAGUES[key].name}: ${standing?.rank_name ?? 'Unranked'}, ${pointsText(standing?.elo)}, ${standing?.wins ?? 0} won, ${standing?.losses ?? 0} lost`}
            style={[
              styles.standingRow,
              index < LEAGUE_ORDER.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft },
            ]}
          >
            <View style={styles.standingName}>
              <Txt weight="semibold">{LEAGUES[key].name}</Txt>
              <Txt variant="small" muted>
                {standing?.rank_name ?? 'Unranked'}
              </Txt>
            </View>
            <Text style={[styles.standingNumber, { color: theme.text, fontFamily: fonts.bold }]}>
              {standing?.elo ?? 0}
            </Text>
            <Text style={[styles.standingNumber, { color: theme.textMuted }]}>
              <Text style={{ color: theme.accentPressed, fontFamily: fonts.semibold }}>{standing?.wins ?? 0}</Text>
              –{standing?.losses ?? 0}
            </Text>
          </View>
        );
      })}
    </Card>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    paddingBottom: 18,
    marginBottom: 18,
    borderBottomWidth: 1,
  },
  headText: { flex: 1, gap: 2 },
  field: { marginBottom: 14 },
  label: { fontFamily: fonts.semibold, fontSize: type.small, marginBottom: 6 },
  select: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderRadius: radius.sm,
  },
  selectText: { flex: 1, fontFamily: fonts.regular, fontSize: type.body },
  standingRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingVertical: 8 },
  standingName: { flex: 1 },
  standingNumber: { fontFamily: fonts.regular, fontSize: type.body, fontVariant: ['tabular-nums'], minWidth: 44, textAlign: 'right' },
  signOut: { marginTop: 4 },
});
