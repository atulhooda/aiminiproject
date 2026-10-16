import { useState } from 'react'

export interface BarDatum {
  key: string
  label: string
  value: number
  color: string
  detail?: string
}

/**
 * Horizontal bar chart for one measure (never two scales on one chart).
 * Bars: <= 24px thick, 4px rounded data-end, square at the baseline, 2px gaps,
 * value at the bar tip in a text token, hover tooltip on every bar.
 */
export function BarChart({ title, unit, data, format }: { title: string; unit?: string; data: BarDatum[]; format?: (v: number) => string }) {
  const [hover, setHover] = useState<string | null>(null)
  const max = Math.max(1e-9, ...data.map((d) => d.value))
  const fmt = format ?? ((v: number) => (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)))
  return (
    <figure className="m-0 min-w-0 rounded-md border border-ink-600 bg-ink-850 p-3">
      <figcaption className="mb-2 text-[11.5px] font-semibold text-slate-300">
        {title}
        {unit && <span className="font-normal text-slate-500"> ({unit})</span>}
      </figcaption>
      <div className="space-y-[2px]">
        {data.map((d) => (
          <div
            key={d.key}
            className="relative flex items-center gap-2"
            onMouseEnter={() => setHover(d.key)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="w-24 shrink-0 truncate text-[11px] text-slate-400">{d.label}</span>
            {/* Bars use at most 80% of the track so the value label always fits outside the bar end. */}
            <div className="flex h-[22px] min-w-0 flex-1 items-center">
              <div
                className="h-4 shrink-0 rounded-r-[4px] transition-[width] duration-500"
                style={{ width: `${Math.max(0.5, (d.value / max) * 80)}%`, background: d.color, opacity: hover && hover !== d.key ? 0.45 : 1 }}
              />
              <span className="pl-1.5 font-mono text-[11px] text-slate-200">{fmt(d.value)}</span>
            </div>
            {hover === d.key && (
              <div className="pointer-events-none absolute -top-9 left-24 z-10 whitespace-nowrap rounded border border-ink-500 bg-ink-950 px-2 py-1 text-[11px] text-slate-200 shadow-lg">
                <span className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ background: d.color }} />
                {d.label}: <b>{fmt(d.value)}</b>
                {unit ? ` ${unit}` : ''}
                {d.detail && <span className="text-slate-400"> · {d.detail}</span>}
              </div>
            )}
          </div>
        ))}
      </div>
    </figure>
  )
}

export function Legend({ items }: { items: { label: string; color: string; dash?: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-300">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5">
          {i.dash ? (
            <span className="h-0 w-5 border-t-2 border-dashed" style={{ borderColor: i.color }} />
          ) : (
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />
          )}
          {i.label}
        </span>
      ))}
    </div>
  )
}
