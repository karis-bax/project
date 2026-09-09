import { useRef, useState, type DragEvent } from 'react'

export function DropZone({ onFile }: { onFile: (file: File) => void }) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) onFile(file)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-6 py-14 text-center transition-colors ${
        dragging
          ? 'border-[var(--accent)] bg-[var(--accent-weak)]'
          : 'border-[var(--border-strong)] hover:bg-[var(--row-hover)]'
      }`}
    >
      <p className="font-medium text-[var(--fg)]">Drop a bank CSV here</p>
      <p className="text-[var(--fg-muted)]">or click to choose a file</p>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFile(file)
          e.target.value = ''
        }}
      />
    </div>
  )
}
