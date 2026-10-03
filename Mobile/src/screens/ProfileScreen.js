/**
 * The Profile tab: pick a flag, upload or link a picture, see where you
 * stand in both leagues, choose light or dark, and sign out. Port of
 * ProfileSettings.jsx.
 *
 * Problems appear beside the field they concern - both the ones caught
 * here and the ones the server sends back (it names the field).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { useIsFocused } from '@react-navigation/native';
import Feather from '@expo/vector-icons/Feather';

import * as api from '../api';
import { CountryPicker } from '../components/CountryPicker';
import { DeleteAccountSheet } from '../components/DeleteAccountSheet';
import { Avatar, useOpenPlayer } from '../components/Player';
import { Button, Card, Field, FieldError, Screen, Segmented, Txt } from '../components/ui';
import { flagEmoji } from '../flags';
import { emailProblem } from '../accountRules';
import { LEAGUE_ORDER, LEAGUES } from '../leagues';
import { PhotoProblem, pickSquarePhoto } from '../photo';
import { APPEARANCE_OPTIONS, useAppearance } from '../state/AppearanceContext';
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
  const toast = useToast();
  const focused = useIsFocused();
  const [profile, setProfile] = useState(null);
  const [problem, setProblem] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const accountDeleted = async () => {
    setDeleting(false);
    await signOut();
    // After signing out, which clears earlier messages.
    toast.push('Your account was deleted.', 'info');
  };

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
        <ProfileForm
          // A new picture starts the form over, so the link field never
          // holds a picture that's already gone.
          key={`${profile.user_id}-${profile.profile_picture ?? ''}`}
          profile={profile}
          onSaved={setProfile}
        />
      ) : (
        <Card>
          <Txt muted>{problem ? `${problem} Try again in a moment.` : 'Loading your profile...'}</Txt>
        </Card>
      )}
      {profile ? <EmailCard email={profile.email} onSaved={setProfile} /> : null}
      {profile ? <Standing profile={profile} /> : null}
      <AppearanceCard />
      <Button variant="quiet" icon="log-out" title="Sign out" onPress={signOut} style={styles.signOut} />

      <Card title="Your account" style={styles.account}>
        <Txt variant="small" muted style={styles.accountText}>
          Deleting your account removes your name, flag, picture and password, and takes
          you off the ladders. Your games stay in other players' history as "Deleted player".
        </Txt>
        <Button variant="dangerQuiet" icon="trash-2" title="Delete account" onPress={() => setDeleting(true)} />
      </Card>

      <Button
        variant="link"
        size="sm"
        title="Privacy policy"
        accessibilityHint="Opens in your browser"
        onPress={() => Linking.openURL(api.PRIVACY_POLICY_URL)}
        style={styles.privacy}
      />

      <DeleteAccountSheet visible={deleting} onClose={() => setDeleting(false)} onDeleted={accountDeleted} />
    </Screen>
  );
}

function ProfileForm({ profile, onSaved }) {
  const { theme } = useLeague();
  const toast = useToast();
  const openPlayer = useOpenPlayer();
  // An uploaded photo's address isn't a link anyone typed, so the link
  // field starts empty rather than offering it back to edit.
  const startingLink = profile.picture_uploaded ? '' : profile.profile_picture || '';
  const [values, setValues] = useState({
    country_flag: profile.country_flag || '',
    profile_picture: startingLink,
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
  // The link being typed, once it looks like one; otherwise whatever the
  // saved picture is - including an uploaded photo.
  const linkEdited = link !== startingLink;
  const preview = {
    username: profile.username,
    profile_picture: linkEdited
      ? previewLink && !pictureProblem(previewLink)
        ? previewLink
        : null
      : profile.profile_picture,
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
    // The picture is only sent when the link was changed: an empty link
    // field also means "keep my uploaded photo", and sending it would
    // delete the photo.
    const changes = { country_flag: values.country_flag || null };
    if (linkEdited) changes.profile_picture = link || null;
    const res = await api.updateProfile(changes);
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
          <Button
            variant="link"
            size="sm"
            title="See your profile as others do"
            onPress={() => openPlayer(profile.user_id)}
            style={styles.seeProfile}
          />
        </View>
      </View>

      <PhotoPicker profile={profile} onSaved={onSaved} />

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
        label="Or use a link to a picture"
        value={values.profile_picture}
        onChangeText={(text) => {
          setValues((v) => ({ ...v, profile_picture: text }));
          setErrors((prev) => (prev.profile_picture ? { ...prev, profile_picture: null } : prev));
        }}
        error={errors.profile_picture}
        hint={
          profile.picture_uploaded
            ? "You're using an uploaded photo. Paste a link here to use that instead."
            : 'Paste a link to an image. Leave it empty to show your initial instead.'
        }
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

/**
 * Choosing a photo as the picture, or removing the picture. The photo is
 * cropped and shrunk on the phone (photo.js), and again on the server,
 * which also strips its metadata - where it was taken, the camera -
 * before anyone sees it.
 */
function PhotoPicker({ profile, onSaved }) {
  const toast = useToast();
  const [working, setWorking] = useState(null);
  const [error, setError] = useState(null);

  const choose = async () => {
    setError(null);
    let image;
    try {
      image = await pickSquarePhoto();
    } catch (problem) {
      setError(problem instanceof PhotoProblem ? problem.message : "That photo couldn't be prepared.");
      return;
    }
    if (!image) return; // backed out of the picker

    setWorking('upload');
    const res = await api.uploadProfilePicture(image);
    setWorking(null);
    if (!res.ok) {
      if (res.data?.field) setError(res.message);
      else if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
      return;
    }
    onSaved(res.data.profile);
    toast.push('Picture saved.', 'success');
  };

  const remove = async () => {
    setError(null);
    setWorking('remove');
    const res = await api.updateProfile({ profile_picture: null });
    setWorking(null);
    if (!res.ok) {
      if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
      return;
    }
    onSaved(res.data.profile);
    toast.push('Picture removed.', 'info');
  };

  return (
    <View style={styles.photo}>
      <View style={styles.photoActions}>
        <Button
          variant="quiet"
          size="sm"
          icon="image"
          title={
            working === 'upload'
              ? 'Uploading...'
              : profile.profile_picture
                ? 'Choose a new photo'
                : 'Choose a photo'
          }
          onPress={choose}
          busy={working === 'upload'}
          disabled={Boolean(working)}
        />
        {profile.profile_picture ? (
          <Button
            variant="quiet"
            size="sm"
            title={working === 'remove' ? 'Removing...' : 'Remove picture'}
            onPress={remove}
            disabled={Boolean(working)}
          />
        ) : null}
      </View>
      <Txt variant="small" muted style={styles.photoHint}>
        Any photo works - it's cropped to a square, and the location and other details photos carry
        are removed.
      </Txt>
      <FieldError message={error} />
    </View>
  );
}

/**
 * The account's email - where a reset code goes if the password is
 * forgotten. Changing it asks for the password, so a phone left signed
 * in can't be used to redirect those codes.
 */
function EmailCard({ email, onSaved }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  const update = (field) => (text) => {
    setValues((v) => ({ ...v, [field]: text }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const close = () => {
    setEditing(false);
    setValues({ email: '', password: '' });
    setErrors({});
  };

  const save = async () => {
    const next = {};
    const problem = emailProblem(values.email);
    if (problem) next.email = problem;
    if (email && !values.password) next.password = 'Enter your password to change your email.';
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await api.setEmail(values.email.trim(), email ? values.password : undefined);
    setBusy(false);
    if (!res.ok) {
      if (res.data?.field) setErrors({ [res.data.field]: res.message });
      else if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
      return;
    }
    onSaved(res.data.profile);
    toast.push('Email saved.', 'success');
    close();
  };

  return (
    <Card title="Email" icon="mail">
      {!editing ? (
        <>
          <Txt weight="semibold" muted={!email} style={styles.email}>
            {email || 'No email yet'}
          </Txt>
          <Txt variant="small" muted style={styles.emailHint}>
            Where a code goes if you forget your password. Never shown to other players.
          </Txt>
          <Button
            variant="quiet"
            size="sm"
            title={email ? 'Change email' : 'Add email'}
            onPress={() => setEditing(true)}
            style={styles.emailButton}
          />
        </>
      ) : (
        <>
          <Field
            label={email ? 'New email' : 'Email'}
            value={values.email}
            onChangeText={update('email')}
            error={errors.email}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="email"
            textContentType="emailAddress"
            keyboardType="email-address"
            inputMode="email"
          />
          {email ? (
            <Field
              label="Your password"
              value={values.password}
              onChangeText={update('password')}
              error={errors.password}
              secureTextEntry
              autoCapitalize="none"
              autoComplete="current-password"
              textContentType="password"
              returnKeyType="done"
              onSubmitEditing={save}
            />
          ) : null}
          <View style={styles.emailActions}>
            <Button title={busy ? 'Saving...' : 'Save email'} size="sm" onPress={save} busy={busy} />
            <Button variant="quiet" size="sm" title="Cancel" onPress={close} disabled={busy} />
          </View>
        </>
      )}
    </Card>
  );
}

/** Light, dark, or whatever the phone is set to. Saved on this phone. */
function AppearanceCard() {
  const { choice, setChoice } = useAppearance();
  return (
    <Card title="Appearance" icon="moon">
      <Segmented
        options={APPEARANCE_OPTIONS}
        value={choice}
        onChange={setChoice}
        accessibilityLabel="Light or dark"
      />
      <Txt variant="small" muted style={styles.appearanceHint}>
        Automatic follows your phone's light or dark setting.
      </Txt>
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
              <Text style={{ color: theme.accentText, fontFamily: fonts.semibold }}>{standing?.wins ?? 0}</Text>
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
  signOut: { marginTop: 4, marginBottom: 16 },
  seeProfile: { alignSelf: 'flex-start', marginTop: 2 },
  photo: { marginBottom: 16 },
  photoActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  photoHint: { marginTop: 6 },
  appearanceHint: { marginTop: 10 },
  email: { marginBottom: 2 },
  emailHint: { marginBottom: 12 },
  emailButton: { alignSelf: 'flex-start' },
  emailActions: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  account: { marginBottom: 8 },
  accountText: { marginBottom: 14 },
  privacy: { alignSelf: 'center' },
});
