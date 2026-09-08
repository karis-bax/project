import { useCallback, useState } from 'react'

const STORAGE_KEY = 'envelope:collapsedGroups'

function load(): Set<number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((n): n is number => typeof n === 'number'))
    }
  } catch {
    // Ignore malformed / unavailable storage; start with nothing collapsed.
  }
  return new Set()
}

function persist(ids: Set<number>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
  } catch {
    // Storage may be unavailable (private mode, quota); collapse still works
    // for the current session.
  }
}

/** Per-user group collapse state, persisted in localStorage. */
export function useCollapsedGroups(): {
  isCollapsed: (groupId: number) => boolean
  toggle: (groupId: number) => void
} {
  const [collapsed, setCollapsed] = useState<Set<number>>(load)

  const toggle = useCallback((groupId: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) {
        next.delete(groupId)
      } else {
        next.add(groupId)
      }
      persist(next)
      return next
    })
  }, [])

  const isCollapsed = useCallback(
    (groupId: number) => collapsed.has(groupId),
    [collapsed],
  )

  return { isCollapsed, toggle }
}
