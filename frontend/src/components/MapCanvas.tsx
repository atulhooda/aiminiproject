import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from 'react'
import type { AnimState } from '../hooks/useSimulation'
import { cellAt, cellSizeFor, drawFrame, GUTTER, renderTerrain, type Overlays } from '../simulation/renderer'
import type { Pos, Snapshot } from '../types/api'

interface Props {
  snap: Snapshot
  anim: MutableRefObject<AnimState>
  colors: Record<string, string>
  overlays: Overlays
  placementLabel: string | null
  selectedVictim: string | null
  painting: boolean
  onCellClick: (pos: Pos) => void
  onCellHover: (pos: Pos | null) => void
  children?: ReactNode
}

export function MapCanvas(props: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 600, h: 600 })
  const hoverRef = useRef<Pos | null>(null)
  const dragRef = useRef<string | null>(null)
  const propsRef = useRef(props)
  propsRef.current = props
  const terrainRef = useRef<{ key: string; canvas: HTMLCanvasElement } | null>(null)

  const { rows, cols } = props.snap.grid
  const cs = cellSizeFor(box.w, box.h, rows, cols)
  const width = GUTTER + cols * cs
  const height = GUTTER + rows * cs

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width: w, height: h } = entry.contentRect
      setBox({ w: Math.max(200, w), h: Math.max(200, h) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Animation loop: draws from refs so React renders never block it.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.ceil(width * dpr)
    canvas.height = Math.ceil(height * dpr)
    let raf = 0
    const frame = (now: number) => {
      const p = propsRef.current
      const key = `${p.snap.grid.cells.join('')}|${cs}|${dpr}`
      if (!terrainRef.current || terrainRef.current.key !== key) {
        terrainRef.current = { key, canvas: renderTerrain(p.snap.grid.cells, cs, dpr) }
      }
      const a = p.anim.current
      drawFrame(
        ctx,
        terrainRef.current.canvas,
        {
          snap: p.snap,
          prevPositions: a.prevPositions,
          moveStartedAt: a.moveStartedAt,
          moveDuration: a.moveDuration,
          overlays: p.overlays,
          hover: hoverRef.current,
          placementLabel: p.placementLabel,
          selectedVictim: p.selectedVictim,
          flashes: a.flashes,
          replans: a.replans,
          search: a.search,
          unitColors: p.colors,
        },
        cs,
        dpr,
        now,
      )
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [cs, width, height])

  const toCell = (e: React.MouseEvent<HTMLCanvasElement>): Pos | null => {
    const rect = e.currentTarget.getBoundingClientRect()
    return cellAt(e.clientX - rect.left, e.clientY - rect.top, cs, rows, cols)
  }

  return (
    <div ref={wrapRef} className="relative flex h-full w-full items-center justify-center overflow-hidden">
      <canvas
        ref={canvasRef}
        style={{ width, height, cursor: props.placementLabel || props.painting ? 'crosshair' : 'default' }}
        className="rounded-md"
        onMouseMove={(e) => {
          const pos = toCell(e)
          const prev = hoverRef.current
          if (pos?.[0] !== prev?.[0] || pos?.[1] !== prev?.[1]) {
            hoverRef.current = pos
            props.onCellHover(pos)
            if (pos && dragRef.current !== null && props.painting) {
              const k = `${pos[0]},${pos[1]}`
              if (dragRef.current !== k) {
                dragRef.current = k
                props.onCellClick(pos)
              }
            }
          }
        }}
        onMouseLeave={() => {
          hoverRef.current = null
          dragRef.current = null
          props.onCellHover(null)
        }}
        onMouseDown={(e) => {
          const pos = toCell(e)
          if (!pos) return
          dragRef.current = `${pos[0]},${pos[1]}`
          props.onCellClick(pos)
        }}
        onMouseUp={() => {
          dragRef.current = null
        }}
        role="img"
        aria-label={`Disaster map, ${rows} by ${cols} cells`}
      />
      {props.children}
    </div>
  )
}
