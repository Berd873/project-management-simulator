import { useEffect, useState } from 'react'
import { api, optional, terminal } from './api'
import type { Artifact, Baseline, Change, Delivery, Report, RunData, Simulation, Trace } from './api'

export function useRun(run: string, revision: number) {
  const [data, setData] = useState<RunData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setData(null); setError('')
    if (!run) return
    let active = true, timer: ReturnType<typeof setTimeout>
    async function refresh() {
      try {
        const [delivery, simulation, baselines, changes, traces, artifacts, report] = await Promise.all([
          api<Delivery>(`/runs/${run}/delivery`), optional<Simulation>(`/runs/${run}/simulation`),
          api<Baseline[]>(`/runs/${run}/baselines`), api<Change[]>(`/runs/${run}/changes`),
          api<Trace[]>(`/runs/${run}/traces`), api<Artifact[]>(`/runs/${run}/artifacts`), optional<Report>(`/runs/${run}/simulation/report`),
        ])
        if (!active) return
        setData({ delivery, simulation, baselines, changes, traces, artifacts, report }); setError('')
        if (!terminal(delivery.status)) timer = setTimeout(refresh, 1000)
      } catch (e) { if (active) { setError(e instanceof Error ? e.message : '无法连接后端'); timer = setTimeout(refresh, 2500) } }
    }
    void refresh()
    return () => { active = false; clearTimeout(timer) }
  }, [run, revision])
  return { data, error }
}

export type StreamEvent = { id: number; kind: string; data: Record<string, unknown> }
export function useEvents(run: string, done: boolean) {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    setEvents([])
    if (!run) return
    const controller = new AbortController()
    let cursor = 0
    async function listen() {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(`/api/v1/runs/${run}/events`, { headers: { 'Last-Event-ID': String(cursor) }, signal: controller.signal })
          if (!response.ok || !response.body) throw new Error('事件流暂不可用')
          setConnected(true)
          const reader = response.body.getReader(), decoder = new TextDecoder()
          let buffer = ''
          while (true) {
            const { value, done: ended } = await reader.read()
            if (ended) break
            buffer += decoder.decode(value, { stream: true })
            let boundary: number
            while ((boundary = buffer.indexOf('\n\n')) >= 0) {
              const part = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
              const lines = part.split('\n'), id = Number(lines.find(l => l.startsWith('id: '))?.slice(4))
              if (!id || id <= cursor) continue
              const payload = lines.find(l => l.startsWith('data: '))?.slice(6)
              if (!payload) continue
              const event = { id, kind: lines.find(l => l.startsWith('event: '))?.slice(7) || 'message', data: JSON.parse(payload) as Record<string, unknown> }
              cursor = id
              setEvents(previous => [...previous.filter(e => e.id !== id), event])
            }
          }
          if (done) break
        } catch { if (controller.signal.aborted) break; setConnected(false) }
        await new Promise(resolve => setTimeout(resolve, 1200))
      }
    }
    void listen()
    return () => { controller.abort(); setConnected(false) }
  }, [run, done])
  return { events, connected }
}
