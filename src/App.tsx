import { useMemo, useState } from 'react'
import './App.css'

type ColumnId = 'todo' | 'doing' | 'done'

interface Task {
  id: string
  title: string
  column: ColumnId
}

const COLUMNS: { id: ColumnId; label: string; accent: string }[] = [
  { id: 'todo', label: 'To do', accent: '#6366f1' },
  { id: 'doing', label: 'In progress', accent: '#f59e0b' },
  { id: 'done', label: 'Done', accent: '#10b981' },
]

const INITIAL_TASKS: Task[] = [
  { id: 't1', title: 'Sketch onboarding flow', column: 'todo' },
  { id: 't2', title: 'Define color tokens', column: 'doing' },
  { id: 't3', title: 'Audit spacing scale', column: 'done' },
]

let nextId = 100

export default function App() {
  const [tasks, setTasks] = useState<Task[]>(INITIAL_TASKS)
  const [draft, setDraft] = useState('')

  const grouped = useMemo(() => {
    return COLUMNS.map((col) => ({
      ...col,
      items: tasks.filter((t) => t.column === col.id),
    }))
  }, [tasks])

  const addTask = () => {
    const title = draft.trim()
    if (!title) return
    setTasks((prev) => [...prev, { id: `t${nextId++}`, title, column: 'todo' }])
    setDraft('')
  }

  const move = (id: string, direction: 1 | -1) => {
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t
        const order: ColumnId[] = ['todo', 'doing', 'done']
        const idx = order.indexOf(t.column)
        const nextIdx = Math.min(order.length - 1, Math.max(0, idx + direction))
        return { ...t, column: order[nextIdx] }
      }),
    )
  }

  const remove = (id: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== id))
  }

  const doneCount = tasks.filter((t) => t.column === 'done').length

  return (
    <div className="app">
      <header className="hero">
        <div className="brand">
          <img src="/vite.svg" alt="Palette logo" width={40} height={40} />
          <div>
            <h1>Palette</h1>
            <p className="subtitle">A tiny task board for design work</p>
          </div>
        </div>
        <div className="progress" aria-live="polite">
          <span className="progress-count">{doneCount}</span>
          <span className="progress-label">
            of {tasks.length} done
          </span>
        </div>
      </header>

      <section className="composer">
        <input
          className="composer-input"
          placeholder="Add a task and press Enter…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addTask()}
          aria-label="New task title"
        />
        <button className="composer-button" onClick={addTask}>
          Add task
        </button>
      </section>

      <main className="board">
        {grouped.map((col) => (
          <div className="column" key={col.id}>
            <div className="column-head">
              <span className="dot" style={{ background: col.accent }} />
              <h2>{col.label}</h2>
              <span className="badge">{col.items.length}</span>
            </div>
            <div className="column-body">
              {col.items.length === 0 && (
                <p className="empty">Nothing here yet</p>
              )}
              {col.items.map((task) => (
                <article className="card" key={task.id}>
                  <p className="card-title">{task.title}</p>
                  <div className="card-actions">
                    <button
                      aria-label="Move left"
                      disabled={task.column === 'todo'}
                      onClick={() => move(task.id, -1)}
                    >
                      ←
                    </button>
                    <button
                      aria-label="Move right"
                      disabled={task.column === 'done'}
                      onClick={() => move(task.id, 1)}
                    >
                      →
                    </button>
                    <button
                      className="delete"
                      aria-label="Delete task"
                      onClick={() => remove(task.id)}
                    >
                      ✕
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </div>
        ))}
      </main>
    </div>
  )
}
