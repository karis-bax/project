/**
 * Entering a transaction has to take seconds, or the budget stops matching
 * reality within a fortnight. Amount is focused on mount, the sign defaults to
 * an outflow, and saving keeps you on the screen ready for the next one.
 */

import React, { useMemo, useRef, useState } from 'react'
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'

import { ApiError } from '../lib/api'
import { formatCents, parseDollars } from '../lib/money'
import { currentMonth, today, useAccounts, useBudget, useCreateTransaction } from '../lib/queries'
import { theme } from '../lib/theme'

export function QuickAddScreen() {
  const { data: accounts } = useAccounts()
  const { data: budget } = useBudget(currentMonth())
  const create = useCreateTransaction()

  const [amountText, setAmountText] = useState('')
  const [payee, setPayee] = useState('')
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [inflow, setInflow] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const payeeRef = useRef<TextInput>(null)

  const categories = useMemo(
    () => budget?.groups.flatMap((g) => g.categories.map((c) => ({ ...c, group: g.name }))) ?? [],
    [budget],
  )

  const activeAccount = accountId ?? accounts?.find((a) => !a.archived)?.id ?? null
  const magnitude = parseDollars(amountText)
  const canSave = magnitude !== null && magnitude > 0 && activeAccount !== null && !create.isPending

  const save = async () => {
    if (!canSave || magnitude === null || activeAccount === null) return
    setError(null)
    try {
      const amount_cents = inflow ? magnitude : -magnitude
      await create.mutateAsync({
        account_id: activeAccount,
        category_id: inflow ? null : categoryId,
        date: today(),
        payee: payee.trim() || 'Unknown',
        amount_cents,
        memo: '',
        cleared: false,
        pending: false,
        import_hash: null,
      })
      setSaved(`${formatCents(amount_cents)} · ${payee.trim() || 'Unknown'}`)
      setAmountText('')
      setPayee('')
      payeeRef.current?.blur()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not save. Check your connection.')
    }
  }

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.amountRow}>
            <Text style={styles.currency}>{inflow ? '+$' : '−$'}</Text>
            <TextInput
              style={styles.amount}
              value={amountText}
              onChangeText={(t) => {
                setAmountText(t)
                setSaved(null)
              }}
              placeholder="0.00"
              placeholderTextColor={theme.inkFaint}
              keyboardType="decimal-pad"
              inputMode="decimal"
              autoFocus
              accessibilityLabel="Amount in dollars"
            />
          </View>

          <Pressable
            style={styles.toggle}
            onPress={() => setInflow((v) => !v)}
            accessibilityRole="switch"
            accessibilityState={{ checked: inflow }}
          >
            <Text style={styles.toggleLabel}>
              {inflow ? 'Money in — uncategorized income' : 'Money out'}
            </Text>
            <Text style={styles.toggleAction}>{inflow ? 'Make it an expense' : 'Make it income'}</Text>
          </Pressable>

          <TextInput
            ref={payeeRef}
            style={styles.input}
            value={payee}
            onChangeText={setPayee}
            placeholder="Who did you pay?"
            placeholderTextColor={theme.inkFaint}
            autoCapitalize="words"
            returnKeyType="done"
          />

          {!inflow ? (
            <>
              <Text style={styles.sectionLabel}>Category</Text>
              <View style={styles.chips}>
                {categories.map((c) => {
                  const selected = c.id === categoryId
                  return (
                    <Pressable
                      key={c.id}
                      style={[styles.chip, selected && styles.chipSelected]}
                      onPress={() => setCategoryId(selected ? null : c.id)}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      accessibilityLabel={`${c.name}, ${formatCents(c.available_cents)} available`}
                    >
                      <Text style={[styles.chipName, selected && styles.chipNameSelected]}>
                        {c.name}
                      </Text>
                      <Text style={[styles.chipAmount, selected && styles.chipAmountSelected]}>
                        {formatCents(c.available_cents)}
                      </Text>
                    </Pressable>
                  )
                })}
              </View>
            </>
          ) : null}

          {accounts && accounts.filter((a) => !a.archived).length > 1 ? (
            <>
              <Text style={styles.sectionLabel}>Account</Text>
              <View style={styles.chips}>
                {accounts
                  .filter((a) => !a.archived)
                  .map((a) => {
                    const selected = a.id === activeAccount
                    return (
                      <Pressable
                        key={a.id}
                        style={[styles.chip, selected && styles.chipSelected]}
                        onPress={() => setAccountId(a.id)}
                        accessibilityRole="button"
                        accessibilityState={{ selected }}
                      >
                        <Text style={[styles.chipName, selected && styles.chipNameSelected]}>
                          {a.name}
                        </Text>
                      </Pressable>
                    )
                  })}
              </View>
            </>
          ) : null}

          {error ? (
            <Text style={styles.error} accessibilityLiveRegion="polite">
              {error}
            </Text>
          ) : null}
          {saved ? (
            <Text style={styles.saved} accessibilityLiveRegion="polite">
              Saved {saved}
            </Text>
          ) : null}
        </ScrollView>

        <Pressable
          style={({ pressed }) => [
            styles.saveButton,
            !canSave && styles.saveDisabled,
            pressed && canSave && styles.savePressed,
          ]}
          onPress={save}
          disabled={!canSave}
          accessibilityRole="button"
        >
          {create.isPending ? (
            <ActivityIndicator color={theme.bg} />
          ) : (
            <Text style={styles.saveLabel}>Save</Text>
          )}
        </Pressable>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  flex: { flex: 1 },
  scroll: { padding: theme.space(4), gap: theme.space(4), paddingBottom: theme.space(6) },
  amountRow: { flexDirection: 'row', alignItems: 'center', gap: theme.space(2) },
  currency: { color: theme.inkMuted, fontSize: 34, fontWeight: '600' },
  amount: {
    color: theme.ink,
    flex: 1,
    fontSize: 52,
    fontWeight: '800',
    letterSpacing: -1.5,
    fontVariant: ['tabular-nums'],
    padding: 0,
  },
  toggle: {
    backgroundColor: theme.surface,
    borderRadius: theme.radius,
    padding: theme.space(3),
    gap: 2,
  },
  toggleLabel: { color: theme.ink, fontSize: 15, fontWeight: '500' },
  toggleAction: { color: theme.accent, fontSize: 13 },
  input: {
    backgroundColor: theme.surface,
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: theme.radius,
    color: theme.ink,
    fontSize: 17,
    padding: theme.space(4),
  },
  sectionLabel: {
    color: theme.inkFaint,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.space(2) },
  chip: {
    backgroundColor: theme.surface,
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: theme.space(3),
    paddingVertical: theme.space(2),
    alignItems: 'center',
  },
  chipSelected: { backgroundColor: theme.accentSoft, borderColor: theme.accent },
  chipName: { color: theme.ink, fontSize: 14 },
  chipNameSelected: { color: theme.accent, fontWeight: '600' },
  chipAmount: { color: theme.inkFaint, fontSize: 11, fontVariant: ['tabular-nums'] },
  chipAmountSelected: { color: theme.accent },
  error: { color: theme.danger, fontSize: 14 },
  saved: { color: theme.accent, fontSize: 14 },
  saveButton: {
    backgroundColor: theme.accent,
    borderRadius: theme.radius,
    margin: theme.space(4),
    padding: theme.space(4),
    alignItems: 'center',
  },
  saveDisabled: { backgroundColor: theme.surfaceAlt },
  savePressed: { opacity: 0.85 },
  saveLabel: { color: theme.bg, fontSize: 17, fontWeight: '700' },
})
