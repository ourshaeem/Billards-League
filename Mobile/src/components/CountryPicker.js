/**
 * Choosing a flag. The web app used a <select>; a list of 249 countries
 * needs a search box on a phone, so this is a full-screen list with one.
 * The list itself comes from the server (GET /countries) - the same
 * codes it accepts.
 */
import React, { useMemo, useState } from 'react';
import { FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Feather from '@expo/vector-icons/Feather';

import { flagEmoji } from '../flags';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { Txt } from './ui';

const NO_FLAG = { code: '', name: 'No flag' };

export function CountryPicker({ visible, countries, selected, onSelect, onClose }) {
  const theme = useTheme();
  const reducedMotion = useReducedMotion();
  const [query, setQuery] = useState('');

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = countries || [];
    const matches = needle
      ? list.filter((c) => c.name.toLowerCase().includes(needle) || c.code.toLowerCase() === needle)
      : list;
    return needle ? matches : [NO_FLAG, ...matches];
  }, [countries, query]);

  const close = () => {
    setQuery('');
    onClose();
  };

  return (
    <Modal
      visible={visible}
      animationType={reducedMotion ? 'none' : 'slide'}
      presentationStyle="pageSheet"
      onRequestClose={close}
    >
      <SafeAreaView style={[styles.sheet, { backgroundColor: theme.page }]} edges={['top', 'bottom']}>
        <View style={[styles.header, { borderBottomColor: theme.line }]}>
          <Txt variant="title" accessibilityRole="header">
            Country flag
          </Txt>
          <Pressable
            onPress={close}
            accessibilityRole="button"
            accessibilityLabel="Close"
            hitSlop={8}
            style={styles.close}
          >
            <Feather name="x" size={22} color={theme.quietText} />
          </Pressable>
        </View>

        <View style={[styles.search, { borderColor: theme.inputBorder, backgroundColor: theme.surface }]}>
          <Feather name="search" size={18} color={theme.textMuted} />
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Search countries"
            placeholderTextColor={theme.textMuted}
            accessibilityLabel="Search countries"
            autoCorrect={false}
            autoCapitalize="none"
            clearButtonMode="while-editing"
            style={[styles.searchInput, { color: theme.text }]}
          />
        </View>

        {!countries ? (
          <Txt muted style={styles.message}>
            Loading the list of countries...
          </Txt>
        ) : rows.length === 0 ? (
          <Txt muted style={styles.message}>
            No country matches "{query}".
          </Txt>
        ) : (
          <FlatList
            data={rows}
            keyExtractor={(item) => item.code || 'none'}
            keyboardShouldPersistTaps="handled"
            initialNumToRender={20}
            renderItem={({ item }) => {
              const isSelected = (selected || '') === item.code;
              return (
                <Pressable
                  onPress={() => {
                    onSelect(item.code);
                    close();
                  }}
                  accessibilityRole="button"
                  accessibilityLabel={item.name}
                  accessibilityState={{ selected: isSelected }}
                  style={({ pressed }) => [
                    styles.row,
                    { borderBottomColor: theme.lineSoft },
                    (pressed || isSelected) && { backgroundColor: theme.accentWash },
                  ]}
                >
                  <Text style={styles.flag}>{item.code ? flagEmoji(item.code) : ''}</Text>
                  <Text style={[styles.name, { color: theme.text }]} numberOfLines={1}>
                    {item.name}
                  </Text>
                  {isSelected ? <Feather name="check" size={20} color={theme.accent} /> : null}
                </Pressable>
              );
            }}
          />
        )}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    margin: 16,
    paddingHorizontal: 12,
    minHeight: 46,
    borderWidth: 1,
    borderRadius: radius.sm,
  },
  searchInput: { flex: 1, fontFamily: fonts.regular, fontSize: type.body, paddingVertical: 10 },
  message: { paddingHorizontal: 16 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 50,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
  },
  flag: { width: 28, fontSize: 22 },
  name: { flex: 1, fontFamily: fonts.regular, fontSize: type.body },
});
