// Canvas renderer for the disaster map. Pure drawing functions: no React here.

import type { Pos, SearchTrace, Snapshot, Unit } from '../types/api'
import { CAPABILITY_GLYPH, SEVERITY_COLOR } from './theme'

export const GUTTER = 16 // px reserved for coordinate labels

export interface Overlays {
  paths: boolean
  search: boolean
  danger: boolean
  unknown: boolean
  labels: boolean
}

export interface Flash {
  cells: Pos[]
  color: string
  startedAt: number
  duration: number
}

export interface ReplanAnim {
  oldPath: Pos[]
  newPath: Pos[]
  color: string
  startedAt: number
}

export interface RenderState {
  snap: Snapshot
  prevPositions: Map<string, Pos>
  moveStartedAt: number
  moveDuration: number
  overlays: Overlays
  hover: Pos | null
  placementLabel: string | null
  selectedVictim: string | null
  flashes: Flash[]
  replans: ReplanAnim[]
  search: { trace: SearchTrace; startedAt: number } | null
  unitColors: Record<string, string>
}

const C = {
  bg: '#070b12',
  road: '#1c2637',
  roadLine: '#141c29',
  building: '#0e1522',
  buildingTop: '#141e2e',
  buildingEdge: '#1b2739',
  hospital: '#1d4ed8',
  base: '#4338ca',
  safe: '#14532d',
  safeMark: '#4ade80',
  water: '#0b3b5c',
  waterWave: '#38bdf8',
  fireBase: '#7c1d12',
  hazardYellow: '#eab308',
  text: '#e2e8f0',
  muted: '#64748b',
}

// ------------------------------------------------------------- geometry
export function cellSizeFor(width: number, height: number, rows: number, cols: number): number {
  return Math.max(6, Math.floor(Math.min((width - GUTTER) / cols, (height - GUTTER) / rows)))
}

function center(p: Pos, cs: number): [number, number] {
  return [GUTTER + p[1] * cs + cs / 2, GUTTER + p[0] * cs + cs / 2]
}

export function cellAt(x: number, y: number, cs: number, rows: number, cols: number): Pos | null {
  const c = Math.floor((x - GUTTER) / cs)
  const r = Math.floor((y - GUTTER) / cs)
  if (r < 0 || c < 0 || r >= rows || c >= cols) return null
  return [r, c]
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
}

// ------------------------------------------------------------- terrain
/** Static terrain layer, cached in an offscreen canvas until the grid changes. */
export function renderTerrain(cells: string[], cs: number, dpr: number): HTMLCanvasElement {
  const rows = cells.length
  const cols = cells[0].length
  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil((GUTTER + cols * cs) * dpr)
  canvas.height = Math.ceil((GUTTER + rows * cs) * dpr)
  const ctx = canvas.getContext('2d')!
  ctx.scale(dpr, dpr)
  ctx.fillStyle = C.bg
  ctx.fillRect(0, 0, GUTTER + cols * cs, GUTTER + rows * cs)

  // Coordinate gutter (every 5 cells) so log references like (8, 12) can be found.
  ctx.fillStyle = C.muted
  ctx.font = `${Math.max(8, Math.min(10, cs * 0.42))}px ui-monospace, Menlo, monospace`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (let c = 0; c < cols; c += 5) ctx.fillText(String(c), GUTTER + c * cs + cs / 2, GUTTER / 2)
  for (let r = 0; r < rows; r += 5) ctx.fillText(String(r), GUTTER / 2, GUTTER + r * cs + cs / 2)

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const code = cells[r][c]
      const x = GUTTER + c * cs
      const y = GUTTER + r * cs
      if (code === '#') {
        ctx.fillStyle = C.building
        ctx.fillRect(x, y, cs, cs)
        ctx.fillStyle = C.buildingTop
        ctx.fillRect(x + 1.5, y + 1.5, cs - 3, cs - 3)
        ctx.fillStyle = C.buildingEdge
        ctx.fillRect(x + 1.5, y + 1.5, cs - 3, 1)
        continue
      }
      // Everything else sits on a road-coloured base.
      ctx.fillStyle = C.road
      ctx.fillRect(x, y, cs, cs)
      ctx.strokeStyle = C.roadLine
      ctx.lineWidth = 1
      ctx.strokeRect(x + 0.5, y + 0.5, cs - 1, cs - 1)
      if (code === 'X') drawDebris(ctx, x, y, cs)
      else if (code === 'H') drawHospital(ctx, x, y, cs)
      else if (code === 'B') drawBase(ctx, x, y, cs)
      else if (code === 'S') drawSafeZone(ctx, x, y, cs)
    }
  }
  return canvas
}

function drawDebris(ctx: CanvasRenderingContext2D, x: number, y: number, cs: number) {
  const inset = cs * 0.12
  ctx.save()
  ctx.beginPath()
  ctx.rect(x + inset, y + inset, cs - 2 * inset, cs - 2 * inset)
  ctx.clip()
  ctx.fillStyle = '#1f1a0a'
  ctx.fillRect(x, y, cs, cs)
  ctx.strokeStyle = C.hazardYellow
  ctx.lineWidth = Math.max(1.5, cs * 0.12)
  for (let k = -cs; k < cs * 2; k += cs * 0.34) {
    ctx.beginPath()
    ctx.moveTo(x + k, y)
    ctx.lineTo(x + k - cs, y + cs)
    ctx.stroke()
  }
  ctx.restore()
  ctx.strokeStyle = '#111827'
  ctx.lineWidth = 1
  ctx.strokeRect(x + inset, y + inset, cs - 2 * inset, cs - 2 * inset)
}

function drawHospital(ctx: CanvasRenderingContext2D, x: number, y: number, cs: number) {
  roundRect(ctx, x + 1.5, y + 1.5, cs - 3, cs - 3, cs * 0.18)
  ctx.fillStyle = C.hospital
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  const t = cs * 0.16
  ctx.fillRect(x + cs / 2 - t / 2, y + cs * 0.22, t, cs * 0.56)
  ctx.fillRect(x + cs * 0.22, y + cs / 2 - t / 2, cs * 0.56, t)
}

function drawBase(ctx: CanvasRenderingContext2D, x: number, y: number, cs: number) {
  roundRect(ctx, x + 1.5, y + 1.5, cs - 3, cs - 3, cs * 0.18)
  ctx.fillStyle = C.base
  ctx.fill()
  ctx.strokeStyle = '#c7d2fe'
  ctx.lineWidth = Math.max(1.2, cs * 0.08)
  ctx.beginPath()
  ctx.moveTo(x + cs * 0.28, y + cs * 0.62)
  ctx.lineTo(x + cs * 0.5, y + cs * 0.36)
  ctx.lineTo(x + cs * 0.72, y + cs * 0.62)
  ctx.stroke()
}

function drawSafeZone(ctx: CanvasRenderingContext2D, x: number, y: number, cs: number) {
  ctx.fillStyle = C.safe
  ctx.fillRect(x + 1, y + 1, cs - 2, cs - 2)
  ctx.strokeStyle = C.safeMark
  ctx.lineWidth = Math.max(1, cs * 0.07)
  ctx.beginPath()
  ctx.moveTo(x + cs * 0.25, y + cs * 0.72)
  ctx.lineTo(x + cs * 0.5, y + cs * 0.3)
  ctx.lineTo(x + cs * 0.75, y + cs * 0.72)
  ctx.closePath()
  ctx.stroke()
}

// ------------------------------------------------------------- frame
export function drawFrame(
  ctx: CanvasRenderingContext2D,
  terrain: HTMLCanvasElement,
  rs: RenderState,
  cs: number,
  dpr: number,
  now: number,
) {
  const { snap, overlays } = rs
  const { rows, cols, cells, danger } = snap.grid
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.drawImage(terrain, 0, 0)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  // Animated hazards
  for (let r = 0; r < rows; r++) {
    const line = cells[r]
    for (let c = 0; c < cols; c++) {
      const code = line[c]
      if (code === 'F') drawFire(ctx, r, c, cs, now)
      else if (code === '~') drawWater(ctx, r, c, cs, now)
      else if (overlays.danger && danger[r][c] > 0) {
        ctx.fillStyle = `rgba(239,68,68,${(danger[r][c] / 100) * 0.38})`
        ctx.fillRect(GUTTER + c * cs, GUTTER + r * cs, cs, cs)
      }
    }
  }

  if (overlays.unknown) drawUnknown(ctx, rs, cs, now)
  if (overlays.search && rs.search) drawSearch(ctx, rs.search.trace, rs.search.startedAt, cs, now)
  for (const f of rs.flashes) drawFlash(ctx, f, cs, now)
  if (overlays.paths) drawPaths(ctx, rs, cs, now)
  for (const rp of rs.replans) drawReplan(ctx, rp, cs, now)
  drawVictims(ctx, rs, cs, now)
  drawUnits(ctx, rs, cs, now)

  if (rs.hover) {
    const [r, c] = rs.hover
    ctx.strokeStyle = rs.placementLabel ? '#fbbf24' : 'rgba(255,255,255,0.85)'
    ctx.lineWidth = rs.placementLabel ? 2 : 1.25
    ctx.strokeRect(GUTTER + c * cs + 1, GUTTER + r * cs + 1, cs - 2, cs - 2)
    if (rs.placementLabel) {
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      ctx.moveTo(GUTTER, GUTTER + r * cs + cs / 2)
      ctx.lineTo(GUTTER + cols * cs, GUTTER + r * cs + cs / 2)
      ctx.moveTo(GUTTER + c * cs + cs / 2, GUTTER)
      ctx.lineTo(GUTTER + c * cs + cs / 2, GUTTER + rows * cs)
      ctx.strokeStyle = 'rgba(251,191,36,0.35)'
      ctx.lineWidth = 1
      ctx.stroke()
      ctx.setLineDash([])
    }
  }
}

function drawFire(ctx: CanvasRenderingContext2D, r: number, c: number, cs: number, now: number) {
  const x = GUTTER + c * cs
  const y = GUTTER + r * cs
  ctx.fillStyle = C.fireBase
  ctx.fillRect(x, y, cs, cs)
  const seed = r * 31 + c * 17
  const flicker = 0.75 + 0.25 * Math.sin(now / 140 + seed)
  const g = ctx.createRadialGradient(x + cs / 2, y + cs * 0.62, cs * 0.05, x + cs / 2, y + cs * 0.55, cs * 0.62)
  g.addColorStop(0, `rgba(254,240,138,${0.95 * flicker})`)
  g.addColorStop(0.35, `rgba(249,115,22,${0.9 * flicker})`)
  g.addColorStop(1, 'rgba(127,29,29,0)')
  ctx.fillStyle = g
  ctx.fillRect(x, y, cs, cs)
  // two licking flame tongues
  ctx.fillStyle = `rgba(251,146,60,${0.55 + 0.35 * Math.sin(now / 90 + seed * 1.7)})`
  for (const off of [0.32, 0.66]) {
    const h = cs * (0.38 + 0.12 * Math.sin(now / 110 + seed + off * 10))
    ctx.beginPath()
    ctx.moveTo(x + cs * (off - 0.13), y + cs * 0.8)
    ctx.quadraticCurveTo(x + cs * off, y + cs * 0.8 - h * 1.5, x + cs * (off + 0.13), y + cs * 0.8)
    ctx.fill()
  }
}

function drawWater(ctx: CanvasRenderingContext2D, r: number, c: number, cs: number, now: number) {
  const x = GUTTER + c * cs
  const y = GUTTER + r * cs
  ctx.fillStyle = C.water
  ctx.fillRect(x, y, cs, cs)
  ctx.strokeStyle = 'rgba(56,189,248,0.45)'
  ctx.lineWidth = 1
  for (const k of [0.35, 0.7]) {
    ctx.beginPath()
    for (let i = 0; i <= 6; i++) {
      const px = x + (i / 6) * cs
      const py = y + cs * k + Math.sin(now / 400 + i * 1.2 + c * 0.9 + r * 0.5) * cs * 0.06
      if (i === 0) ctx.moveTo(px, py)
      else ctx.lineTo(px, py)
    }
    ctx.stroke()
  }
}

function drawUnknown(ctx: CanvasRenderingContext2D, rs: RenderState, cs: number, now: number) {
  const pulse = 0.55 + 0.45 * Math.sin(now / 300)
  for (const d of rs.snap.belief_diff) {
    const [r, c] = d.pos
    const x = GUTTER + c * cs
    const y = GUTTER + r * cs
    ctx.setLineDash([3, 2])
    ctx.strokeStyle = `rgba(251,191,36,${0.5 + 0.4 * pulse})`
    ctx.lineWidth = 1.5
    ctx.strokeRect(x + 2, y + 2, cs - 4, cs - 4)
    ctx.setLineDash([])
    ctx.fillStyle = `rgba(251,191,36,${0.75})`
    ctx.font = `bold ${Math.max(8, cs * 0.5)}px ui-sans-serif, system-ui`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('?', x + cs / 2, y + cs / 2 + 0.5)
  }
  if (!rs.overlays.labels) return
  // Unreported victims are part of the ground truth the agent cannot see yet.
  for (const v of rs.snap.victims) {
    if (v.reported || v.status !== 'UNREPORTED') continue
    const [cx, cy] = center(v.pos, cs)
    ctx.setLineDash([2, 2])
    ctx.strokeStyle = 'rgba(148,163,184,0.8)'
    ctx.lineWidth = 1.2
    ctx.beginPath()
    ctx.arc(cx, cy, cs * 0.3, 0, Math.PI * 2)
    ctx.stroke()
    ctx.setLineDash([])
  }
}

function drawSearch(ctx: CanvasRenderingContext2D, trace: SearchTrace, startedAt: number, cs: number, now: number) {
  const reveal = Math.min(1, (now - startedAt) / 900)
  const n = Math.floor(trace.explored.length * reveal)
  ctx.fillStyle = 'rgba(34,211,238,0.17)'
  for (let i = 0; i < n; i++) {
    const [r, c] = trace.explored[i]
    ctx.fillRect(GUTTER + c * cs + 1, GUTTER + r * cs + 1, cs - 2, cs - 2)
  }
  if (reveal < 1) return
  ctx.strokeStyle = 'rgba(245,158,11,0.85)'
  ctx.lineWidth = 1.25
  for (const [r, c] of trace.frontier) ctx.strokeRect(GUTTER + c * cs + 2, GUTTER + r * cs + 2, cs - 4, cs - 4)
  if (trace.path.length > 1) {
    ctx.strokeStyle = 'rgba(34,211,238,0.9)'
    ctx.lineWidth = 2
    ctx.beginPath()
    trace.path.forEach((p, i) => {
      const [x, y] = center(p, cs)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()
  }
}

function drawFlash(ctx: CanvasRenderingContext2D, f: Flash, cs: number, now: number) {
  const t = (now - f.startedAt) / f.duration
  if (t < 0 || t > 1) return
  for (const p of f.cells) {
    const [x, y] = center(p, cs)
    for (const lag of [0, 0.3]) {
      const tt = t - lag
      if (tt < 0) continue
      ctx.strokeStyle = f.color
      ctx.globalAlpha = Math.max(0, 1 - tt) * 0.9
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(x, y, cs * (0.4 + tt * 2.2), 0, Math.PI * 2)
      ctx.stroke()
    }
    ctx.globalAlpha = 1
  }
}

function polyline(ctx: CanvasRenderingContext2D, path: Pos[], cs: number, startXY?: [number, number]) {
  ctx.beginPath()
  path.forEach((p, i) => {
    const [x, y] = i === 0 && startXY ? startXY : center(p, cs)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
}

function drawPaths(ctx: CanvasRenderingContext2D, rs: RenderState, cs: number, now: number) {
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  for (const plan of rs.snap.plans) {
    const color = rs.unitColors[plan.unit_id] ?? '#94a3b8'
    for (const leg of plan.legs) {
      if (leg.path.length < 2) continue
      const startXY = leg.active ? unitXY(rs, plan.unit_id, cs, now) ?? undefined : undefined
      ctx.strokeStyle = color
      if (leg.active) {
        ctx.globalAlpha = 0.95
        ctx.lineWidth = 2.5
        ctx.setLineDash([cs * 0.32, cs * 0.22])
        ctx.lineDashOffset = -now / 40
      } else {
        ctx.globalAlpha = 0.45
        ctx.lineWidth = 1.5
        ctx.setLineDash([2, 4])
        ctx.lineDashOffset = 0
      }
      polyline(ctx, leg.path, cs, startXY)
      ctx.stroke()
      ctx.setLineDash([])
      // destination marker
      const [gx, gy] = center(leg.path[leg.path.length - 1], cs)
      ctx.beginPath()
      ctx.arc(gx, gy, cs * 0.18, 0, Math.PI * 2)
      ctx.lineWidth = 1.5
      ctx.stroke()
      ctx.globalAlpha = 1
    }
  }
}

function drawReplan(ctx: CanvasRenderingContext2D, rp: ReplanAnim, cs: number, now: number) {
  const t = (now - rp.startedAt) / 3500
  if (t < 0 || t > 1) return
  if (rp.oldPath.length > 1) {
    ctx.strokeStyle = '#ef4444'
    ctx.globalAlpha = Math.max(0, 1 - t) * 0.9
    ctx.lineWidth = 2.5
    ctx.setLineDash([4, 4])
    polyline(ctx, rp.oldPath, cs)
    ctx.stroke()
    ctx.setLineDash([])
  }
  if (rp.newPath.length > 1) {
    ctx.strokeStyle = rp.color
    ctx.globalAlpha = (1 - t) * (0.35 + 0.25 * Math.sin(now / 120))
    ctx.lineWidth = cs * 0.45
    ctx.lineCap = 'round'
    polyline(ctx, rp.newPath, cs)
    ctx.stroke()
  }
  ctx.globalAlpha = 1
}

function drawVictims(ctx: CanvasRenderingContext2D, rs: RenderState, cs: number, now: number) {
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const v of rs.snap.victims) {
    if (!v.reported) continue
    const [x, y] = center(v.pos, cs)
    if (v.status === 'DECEASED') {
      ctx.strokeStyle = 'rgba(148,163,184,0.6)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x - cs * 0.18, y - cs * 0.18)
      ctx.lineTo(x + cs * 0.18, y + cs * 0.18)
      ctx.moveTo(x + cs * 0.18, y - cs * 0.18)
      ctx.lineTo(x - cs * 0.18, y + cs * 0.18)
      ctx.stroke()
      continue
    }
    if (v.status === 'RESCUED' || v.carrier_id) continue
    const color = SEVERITY_COLOR[v.severity]
    const rad = cs * 0.3
    if (v.severity === 'CRITICAL') {
      const t = (now % 1400) / 1400
      ctx.strokeStyle = color
      ctx.globalAlpha = 1 - t
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(x, y, rad + t * cs * 0.45, 0, Math.PI * 2)
      ctx.stroke()
      ctx.globalAlpha = 1
    }
    ctx.beginPath()
    ctx.arc(x, y, rad + 2, 0, Math.PI * 2)
    ctx.fillStyle = C.bg
    ctx.fill()
    ctx.beginPath()
    ctx.arc(x, y, rad, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill()
    if (v.status === 'ASSIGNED' || v.status === 'BEING_RESCUED') {
      ctx.strokeStyle = '#f8fafc'
      ctx.lineWidth = 1.25
      ctx.stroke()
    }
    if (v.status === 'BEING_RESCUED' && v.rescue_time > 0) {
      ctx.strokeStyle = '#f8fafc'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(x, y, rad + 3.5, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * Math.min(1, v.rescue_progress / v.rescue_time)))
      ctx.stroke()
    }
    // cross glyph = casualty
    ctx.fillStyle = '#0b1220'
    const t = Math.max(1.2, cs * 0.07)
    ctx.fillRect(x - t / 2, y - rad * 0.55, t, rad * 1.1)
    ctx.fillRect(x - rad * 0.55, y - t / 2, rad * 1.1, t)
    if (v.trapped && !v.extracted) {
      ctx.fillStyle = '#a8a29e'
      ctx.beginPath()
      ctx.moveTo(x + rad * 0.3, y + rad * 1.15)
      ctx.lineTo(x + rad * 1.15, y + rad * 1.15)
      ctx.lineTo(x + rad * 1.15, y + rad * 0.3)
      ctx.closePath()
      ctx.fill()
    }
    // health bar
    const bw = cs * 0.7
    ctx.fillStyle = 'rgba(15,23,42,0.9)'
    ctx.fillRect(x - bw / 2, y + rad + 2, bw, 2.5)
    ctx.fillStyle = v.health > 50 ? '#22c55e' : v.health > 25 ? '#eab308' : '#ef4444'
    ctx.fillRect(x - bw / 2, y + rad + 2, (bw * v.health) / 100, 2.5)
    if (rs.selectedVictim === v.id) {
      ctx.strokeStyle = '#38bdf8'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(x, y, rad + 6 + Math.sin(now / 200) * 1.5, 0, Math.PI * 2)
      ctx.stroke()
    }
    if (rs.overlays.labels) label(ctx, v.id, x, y - rad - 6, cs)
  }
}

function unitXY(rs: RenderState, id: string, cs: number, now: number): [number, number] | null {
  const unit = [...rs.snap.ambulances, ...rs.snap.teams].find((u) => u.id === id)
  if (!unit) return null
  const prev = rs.prevPositions.get(id) ?? unit.pos
  const t = Math.min(1, Math.max(0, (now - rs.moveStartedAt) / rs.moveDuration))
  const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
  const [x0, y0] = center(prev, cs)
  const [x1, y1] = center(unit.pos, cs)
  return [x0 + (x1 - x0) * ease, y0 + (y1 - y0) * ease]
}

function drawUnits(ctx: CanvasRenderingContext2D, rs: RenderState, cs: number, now: number) {
  const units: Unit[] = [...rs.snap.ambulances, ...rs.snap.teams]
  const stack = new Map<string, number>()
  for (const u of units) {
    const xy = unitXY(rs, u.id, cs, now)
    if (!xy) continue
    let [x, y] = xy
    const key = `${u.pos[0]},${u.pos[1]}`
    const k = stack.get(key) ?? 0
    stack.set(key, k + 1)
    if (k > 0) {
      x += (k % 2 ? 1 : -1) * cs * 0.22
      y += (k > 1 ? 1 : -1) * cs * 0.18
    }
    const color = u.available ? rs.unitColors[u.id] ?? '#94a3b8' : '#475569'
    if (u.kind === 'AMBULANCE') drawAmbulance(ctx, u, x, y, cs, color)
    else drawTeam(ctx, u, x, y, cs, color)
    if (!u.available) {
      ctx.strokeStyle = '#ef4444'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(x - cs * 0.35, y - cs * 0.35)
      ctx.lineTo(x + cs * 0.35, y + cs * 0.35)
      ctx.stroke()
    }
    if (rs.overlays.labels) label(ctx, u.id, x, y + cs * 0.55, cs)
  }
}

function drawAmbulance(ctx: CanvasRenderingContext2D, u: Unit, x: number, y: number, cs: number, color: string) {
  const w = cs * 0.78
  const h = cs * 0.56
  roundRect(ctx, x - w / 2 - 1.5, y - h / 2 - 1.5, w + 3, h + 3, cs * 0.14)
  ctx.fillStyle = C.bg
  ctx.fill()
  roundRect(ctx, x - w / 2, y - h / 2, w, h, cs * 0.12)
  ctx.fillStyle = color
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  const t = Math.max(1.5, cs * 0.09)
  ctx.fillRect(x - t / 2, y - h * 0.32, t, h * 0.64)
  ctx.fillRect(x - h * 0.32, y - t / 2, h * 0.64, t)
  // seats: filled dots for patients on board
  for (let i = 0; i < u.capacity; i++) {
    ctx.beginPath()
    ctx.arc(x + w / 2 - 3 - i * 4, y - h / 2 - 3, 1.6, 0, Math.PI * 2)
    ctx.fillStyle = i < u.carrying.length ? '#ef4444' : 'rgba(226,232,240,0.5)'
    ctx.fill()
  }
}

function drawTeam(ctx: CanvasRenderingContext2D, u: Unit, x: number, y: number, cs: number, color: string) {
  const r = cs * 0.32
  ctx.beginPath()
  ctx.arc(x, y, r + 1.5, 0, Math.PI * 2)
  ctx.fillStyle = C.bg
  ctx.fill()
  ctx.beginPath()
  ctx.moveTo(x, y - r)
  ctx.lineTo(x + r, y)
  ctx.lineTo(x, y + r)
  ctx.lineTo(x - r, y)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.font = `bold ${Math.max(7, cs * 0.34)}px ui-sans-serif, system-ui`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(CAPABILITY_GLYPH[u.capability] ?? 'T', x, y + 0.5)
  if (u.carrying.length) {
    ctx.beginPath()
    ctx.arc(x + r * 0.9, y - r * 0.9, 2, 0, Math.PI * 2)
    ctx.fillStyle = '#ef4444'
    ctx.fill()
  }
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, cs: number) {
  if (cs < 14) return
  ctx.font = `600 ${Math.max(8, Math.min(11, cs * 0.38))}px ui-sans-serif, system-ui`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.lineWidth = 3
  ctx.strokeStyle = 'rgba(7,11,18,0.9)'
  ctx.strokeText(text, x, y)
  ctx.fillStyle = C.text
  ctx.fillText(text, x, y)
}

/** Flat (non-animated) fire, water and danger tint - used by the Algorithm Lab. */
export function drawStaticHazards(ctx: CanvasRenderingContext2D, cells: string[], danger: number[][] | null, cs: number) {
  for (let r = 0; r < cells.length; r++) {
    for (let c = 0; c < cells[r].length; c++) {
      const code = cells[r][c]
      const x = GUTTER + c * cs
      const y = GUTTER + r * cs
      if (code === 'F') {
        ctx.fillStyle = '#9a3412'
        ctx.fillRect(x, y, cs, cs)
        ctx.fillStyle = 'rgba(251,146,60,0.85)'
        ctx.beginPath()
        ctx.arc(x + cs / 2, y + cs * 0.58, cs * 0.26, 0, Math.PI * 2)
        ctx.fill()
      } else if (code === '~') {
        ctx.fillStyle = C.water
        ctx.fillRect(x, y, cs, cs)
      } else if (danger && danger[r][c] > 0) {
        ctx.fillStyle = `rgba(239,68,68,${(danger[r][c] / 100) * 0.3})`
        ctx.fillRect(x, y, cs, cs)
      }
    }
  }
}
