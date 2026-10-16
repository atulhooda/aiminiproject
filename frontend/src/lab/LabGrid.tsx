import { useEffect, useRef } from 'react'
import { cellAt, drawStaticHazards, GUTTER, renderTerrain } from '../simulation/renderer'
import type { LabMap, Pos } from '../types/api'

export interface Trajectory {
  path: Pos[]
  color: string
  dash?: number[]
  width?: number
}

interface Props {
  map: LabMap
  cellSize: number
  explored?: Pos[]
  frontier?: Pos[]
  path?: Pos[]
  pathColor?: string
  revealed?: number // how many explored cells to show (animation)
  showResult?: boolean
  trajectories?: Trajectory[]
  revealedCells?: Pos[]
  start: Pos
  goal: Pos
  onCellClick?: (p: Pos) => void
}

/** Small canvas map used to visualise one search run. */
export function LabGrid(p: Props) {
  const ref = useRef<HTMLCanvasElement>(null)
  const terrain = useRef<{ key: string; canvas: HTMLCanvasElement } | null>(null)
  const { rows, cols } = p.map
  const cs = p.cellSize
  const w = GUTTER + cols * cs
  const h = GUTTER + rows * cs

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.ceil(w * dpr)
    canvas.height = Math.ceil(h * dpr)
    const ctx = canvas.getContext('2d')!
    const key = `${p.map.cells.join('')}|${cs}|${dpr}`
    if (!terrain.current || terrain.current.key !== key) terrain.current = { key, canvas: renderTerrain(p.map.cells, cs, dpr) }
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.drawImage(terrain.current.canvas, 0, 0)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    drawStaticHazards(ctx, p.map.cells, p.map.danger, cs)

    if (p.revealedCells) {
      ctx.fillStyle = 'rgba(148,163,184,0.12)'
      for (const [r, c] of p.revealedCells) ctx.fillRect(GUTTER + c * cs, GUTTER + r * cs, cs, cs)
    }
    if (p.explored) {
      const n = Math.min(p.explored.length, p.revealed ?? p.explored.length)
      for (let i = 0; i < n; i++) {
        const [r, c] = p.explored[i]
        // newest expansions glow brighter: the expansion wave is visible
        const age = n - i
        ctx.fillStyle = age < 6 ? 'rgba(165,243,252,0.55)' : 'rgba(34,211,238,0.22)'
        ctx.fillRect(GUTTER + c * cs + 0.5, GUTTER + r * cs + 0.5, cs - 1, cs - 1)
      }
    }
    if (p.showResult && p.frontier) {
      ctx.strokeStyle = 'rgba(245,158,11,0.9)'
      ctx.lineWidth = 1
      for (const [r, c] of p.frontier) ctx.strokeRect(GUTTER + c * cs + 1.5, GUTTER + r * cs + 1.5, cs - 3, cs - 3)
    }
    const line = (path: Pos[], color: string, width: number, dash: number[] = []) => {
      if (path.length < 2) return
      ctx.strokeStyle = color
      ctx.lineWidth = width
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      ctx.setLineDash(dash)
      ctx.beginPath()
      path.forEach(([r, c], i) => {
        const x = GUTTER + c * cs + cs / 2
        const y = GUTTER + r * cs + cs / 2
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
      ctx.setLineDash([])
    }
    if (p.showResult && p.path) line(p.path, p.pathColor ?? '#22d3ee', 2.5)
    for (const t of p.trajectories ?? []) line(t.path, t.color, t.width ?? 2, t.dash)

    const marker = (pos: Pos, color: string, text: string) => {
      const x = GUTTER + pos[1] * cs + cs / 2
      const y = GUTTER + pos[0] * cs + cs / 2
      ctx.beginPath()
      ctx.arc(x, y, Math.max(4, cs * 0.42), 0, Math.PI * 2)
      ctx.fillStyle = '#070b12'
      ctx.fill()
      ctx.beginPath()
      ctx.arc(x, y, Math.max(3, cs * 0.34), 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.fillStyle = '#0b1220'
      ctx.font = `bold ${Math.max(7, cs * 0.42)}px ui-sans-serif, system-ui`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(text, x, y + 0.5)
    }
    marker(p.start, '#e2e8f0', 'S')
    marker(p.goal, '#f87171', 'G')
  }, [p, cs, w, h])

  return (
    <canvas
      ref={ref}
      style={{ width: w, height: h, cursor: p.onCellClick ? 'crosshair' : 'default' }}
      className="rounded"
      onClick={(e) => {
        if (!p.onCellClick) return
        const rect = e.currentTarget.getBoundingClientRect()
        const pos = cellAt(e.clientX - rect.left, e.clientY - rect.top, cs, rows, cols)
        if (pos) p.onCellClick(pos)
      }}
    />
  )
}
