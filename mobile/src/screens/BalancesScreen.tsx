/**
 * Home. The question this screen answers is "can I afford this, right now",
 * so it leads with what is left in each envelope and pushes everything else
 * down. Categories with the least room float to the top, because those are the
 * ones you are about to get wrong.
 */

import React, { useMemo } from 'react'
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'

import { formatCents, formatCentsShort } from '../lib/money'
import { currentMonth, useBudget } from '../lib/queries'
import { theme } from '../lib/theme'
import type { CategoryBudgetRow } from '../lib/types'

interface Row extends CategoryBudgetRow {
  groupName: string
}

export function BalancesScreen() {
  const month = currentMonth()
  const { data, isLoading, isError, error, refetch, isRefetching } = useBudget(month)

  const rows = useMemo<Row[]>(() => {
    if (!data) return []
    const flat = data.groups.flatMap((g) =>
      g.categories.map((c) => ({ ...c, groupName: g.name })),
    )
    // Tightest first: what is actually left once pending charges settle.
    return flat
      .filter((c) => c.assigned_cents !== 0 || c.activity_cents !== 0)
      .sort(
        (a, b) =>
          a.available_cents - a.pending_cents - (b.available_cents - b.pending_cents),
      )
  }, [data])

  if (isLoading) {
    return (
      <SafeAreaView style={styles.centered}>
        <ActivityIndicator color={theme.accent} />
      </SafeAreaView>
    )
  }

  if (isError) {
    return (
      <SafeAreaView style={styles.centered}>
        <Text style={styles.errorTitle}>Can&apos;t reach your budget</Text>
        <Text style={styles.errorBody}>
          {error instanceof Error ? error.message : 'Unknown error'}
        </Text>
        <Text style={styles.errorHint}>Pull down to try again.</Text>
      </SafeAreaView>
    )
  }

  const left = data?.left_to_assign_cents ?? 0
  const leftState = left > 0 ? 'positive' : left < 0 ? 'negative' : 'zero'

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={isRefetching}
            onRefresh={() => void refetch()}
            tintColor={theme.inkMuted}
          />
        }
      >
        <View style={styles.header}>
          <Text style={styles.month}>{monthLabel(month)}</Text>
          <Text
            style={[
              styles.leftAmount,
              leftState === 'negative' && styles.leftNegative,
              leftState === 'zero' && styles.leftZero,
            ]}
          >
            {formatCents(left)}
          </Text>
          <Text style={styles.leftCaption}>
            {leftState === 'positive'
              ? 'left to assign'
              : leftState === 'negative'
                ? 'over-assigned'
                : 'every dollar assigned'}
          </Text>
        </View>

        {rows.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Nothing budgeted yet</Text>
            <Text style={styles.emptyBody}>
              Assign money to your categories on the desktop app, and they&apos;ll show up
              here.
            </Text>
          </View>
        ) : (
          rows.map((row) => <CategoryRow key={row.id} row={row} />)
        )}
      </ScrollView>
    </SafeAreaView>
  )
}

function CategoryRow({ row }: { row: Row }) {
  const afterPending = row.available_cents - row.pending_cents
  const short = row.available_cents > 0 && afterPending < 0
  const overspent = row.available_cents < 0

  return (
    <View style={styles.row}>
      <View style={styles.rowText}>
        <Text style={styles.rowName} numberOfLines={1}>
          {row.name}
        </Text>
        <Text style={styles.rowGroup} numberOfLines={1}>
          {row.groupName}
        </Text>
      </View>
      <View style={styles.rowAmounts}>
        <Text
          style={[styles.rowAvailable, overspent && styles.rowOverspent]}
          accessibilityLabel={accessibleAmount(row, short, afterPending)}
        >
          {formatCentsShort(row.available_cents)}
        </Text>
        {row.pending_cents !== 0 ? (
          <Text style={[styles.rowPending, short && styles.rowPendingShort]}>
            {formatCentsShort(Math.abs(row.pending_cents))} pending
            {short ? ` · ${formatCentsShort(Math.abs(afterPending))} short` : ''}
          </Text>
        ) : (
          <View style={styles.pendingSpacer} />
        )}
      </View>
    </View>
  )
}

function accessibleAmount(row: Row, short: boolean, afterPending: number): string {
  const base = `${row.name}, ${formatCents(row.available_cents)} available`
  if (row.pending_cents === 0) return base
  const pending = `, ${formatCents(Math.abs(row.pending_cents))} pending`
  const shortfall = short ? `, ${formatCents(Math.abs(afterPending))} short once pending clears` : ''
  return `${base}${pending}${shortfall}`
}

function monthLabel(month: string): string {
  const [year, m] = month.split('-')
  const date = new Date(Number(year), Number(m) - 1, 1)
  return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  centered: {
    flex: 1,
    backgroundColor: theme.bg,
    alignItems: 'center',
    justifyContent: 'center',
    padding: theme.space(6),
    gap: theme.space(2),
  },
  scroll: { padding: theme.space(4), paddingBottom: theme.space(12) },
  header: { marginBottom: theme.space(6), gap: theme.space(1) },
  month: {
    color: theme.inkFaint,
    fontSize: 12,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  leftAmount: { color: theme.accent, fontSize: 44, fontWeight: '800', letterSpacing: -1.5 },
  leftNegative: { color: theme.danger },
  leftZero: { color: theme.ink },
  leftCaption: { color: theme.inkMuted, fontSize: 15 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: theme.space(3),
    borderBottomColor: theme.line,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: theme.space(3),
  },
  rowText: { flex: 1, gap: 2 },
  rowName: { color: theme.ink, fontSize: 17, fontWeight: '500' },
  rowGroup: { color: theme.inkFaint, fontSize: 13 },
  rowAmounts: { alignItems: 'flex-end', gap: 2 },
  rowAvailable: { color: theme.ink, fontSize: 19, fontWeight: '600', fontVariant: ['tabular-nums'] },
  rowOverspent: { color: theme.danger },
  rowPending: { color: theme.inkFaint, fontSize: 12, fontVariant: ['tabular-nums'] },
  rowPendingShort: { color: theme.warn },
  pendingSpacer: { height: 15 },
  empty: { paddingVertical: theme.space(10), gap: theme.space(2) },
  emptyTitle: { color: theme.ink, fontSize: 18, fontWeight: '600' },
  emptyBody: { color: theme.inkMuted, fontSize: 15, lineHeight: 22 },
  errorTitle: { color: theme.ink, fontSize: 18, fontWeight: '600' },
  errorBody: { color: theme.inkMuted, fontSize: 15, textAlign: 'center' },
  errorHint: { color: theme.inkFaint, fontSize: 13 },
})
