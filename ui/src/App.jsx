// WellClose Reviewer (Brief §9.4): side-by-side fact <-> source page; keystrokes a/c/r;
// conflict groups adjacent; batch-approve >= T_auto; sign-off triggers composer via Temporal.
import React, { useCallback, useEffect, useMemo, useState } from 'react'

const HEADERS = { 'Content-Type': 'application/json', 'X-Reviewer': 'reviewer-ui' }
const api = (p, opts) => fetch(p, { headers: HEADERS, ...opts }).then(r => {
  if (!r.ok) throw new Error(`${r.status}`); return r.json()
})

function Badge({ children, tone }) {
  const tones = { red: 'bg-red-100 text-red-800', amber: 'bg-amber-100 text-amber-800',
                  blue: 'bg-blue-100 text-blue-800', slate: 'bg-slate-200 text-slate-700' }
  return <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${tones[tone]}`}>{children}</span>
}

function reasonBadges(f, tAuto) {
  const out = []
  if (f.conflict_group_id) out.push(<Badge key="c" tone="red">conflict</Badge>)
  if (f.diagram) out.push(<Badge key="d" tone="blue">diagram</Badge>)
  if (f.validation_flags?.length) out.push(<Badge key="v" tone="amber">validator</Badge>)
  if (f.confidence < tAuto) out.push(<Badge key="l" tone="slate">conf {f.confidence.toFixed(2)}</Badge>)
  return out
}

export default function App() {
  const [wells, setWells] = useState([])
  const [wellId, setWellId] = useState(null)
  const [data, setData] = useState(null)
  const [idx, setIdx] = useState(0)
  const [correcting, setCorrecting] = useState(false)
  const [correction, setCorrection] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(async (wid) => {
    const d = await api(`/api/wells/${wid}/queue`)
    setData(d); setIdx(0); setCorrecting(false)
  }, [])

  useEffect(() => { api('/api/wells').then(setWells) }, [])
  useEffect(() => { if (wellId) load(wellId) }, [wellId, load])

  // Conflict groups adjacent (§9.4)
  const queue = useMemo(() => {
    if (!data) return []
    const q = [...data.queue, ...data.orphan_facts]
    return q.sort((a, b) => (a.conflict_group_id || 'zzz').localeCompare(b.conflict_group_id || 'zzz'))
  }, [data])
  const fact = queue[idx]

  const decide = useCallback(async (action) => {
    if (!fact) return
    const body = { action }
    if (action === 'correct') {
      if (!correction) { setCorrecting(true); return }
      body.corrected_value = correction
    }
    const r = await api(`/api/facts/${fact.fact_id}/decision`, { method: 'POST', body: JSON.stringify(body) })
    setMsg(`queue remaining: ${r.queue_remaining ?? '—'}`)
    setCorrection(''); setCorrecting(false)
    await load(wellId)
  }, [fact, correction, wellId, load])

  useEffect(() => {
    const h = (e) => {
      if (correcting || !fact) return
      if (e.key === 'a') decide('approve')
      else if (e.key === 'r') decide('reject')
      else if (e.key === 'c') setCorrecting(true)
      else if (e.key === 'ArrowRight') setIdx(i => Math.min(i + 1, queue.length - 1))
      else if (e.key === 'ArrowLeft') setIdx(i => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [decide, correcting, fact, queue.length])

  const batchApprove = async () => {
    const r = await api(`/api/wells/${wellId}/batch-approve`, { method: 'POST' })
    setMsg(`batch-approved ${r.approved}; queue remaining ${r.queue_remaining}`)
    await load(wellId)
  }
  const signOff = async () => {
    await api(`/api/wells/${wellId}/sign-off`, { method: 'POST' })
    setMsg('signed off — composer will run via Temporal')
  }

  if (!wellId) return (
    <div className="max-w-3xl mx-auto p-8">
      <h1 className="text-2xl font-bold text-slate-800 mb-4">WellClose Review</h1>
      <div className="space-y-2">{wells.map(w => (
        <button key={w.well_id} onClick={() => setWellId(w.well_id)}
          className="w-full text-left bg-white rounded-lg shadow px-4 py-3 hover:bg-blue-50">
          <span className="font-mono font-semibold">{w.api_number || w.uwi || w.name || w.well_id}</span>
          <span className="ml-3 text-slate-500">{w.jurisdiction}</span>
          <span className="float-right"><Badge tone="amber">{w.proposed_facts} proposed</Badge></span>
        </button>))}
      </div>
    </div>)

  return (
    <div className="h-screen flex flex-col">
      <header className="bg-slate-800 text-white px-4 py-2 flex items-center gap-4">
        <button onClick={() => setWellId(null)} className="text-slate-300 hover:text-white">← wells</button>
        <span className="font-semibold">Review queue · {queue.length} items</span>
        <span className="text-slate-300 text-sm">keys: a approve · c correct · r reject · ←/→ navigate</span>
        <div className="ml-auto flex gap-2">
          <button onClick={batchApprove}
            className="bg-emerald-600 hover:bg-emerald-500 px-3 py-1 rounded text-sm">
            Batch-approve {data?.batch_approvable ?? 0} ≥ {data?.t_auto}</button>
          <button onClick={signOff} disabled={queue.length > 0}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 px-3 py-1 rounded text-sm">
            Sign off → compose</button>
        </div>
      </header>
      {msg && <div className="bg-amber-50 text-amber-900 px-4 py-1 text-sm">{msg}</div>}
      {!fact ? (
        <div className="flex-1 grid place-items-center text-slate-500">
          <div className="text-center">
            <p className="text-xl">Queue empty 🎉</p>
            <p className="mt-2 text-sm">review_complete signaled — sign off to compose the dossier.</p>
            {data?.gaps?.length > 0 && <div className="mt-4 text-left bg-white rounded shadow p-4">
              <p className="font-semibold mb-2">Open gaps</p>
              {data.gaps.map(g => <p key={g.requirement_id} className="text-sm">
                <Badge tone={g.criticality === 'blocker' ? 'red' : 'amber'}>{g.criticality}</Badge>
                <span className="ml-2">{g.requirement_id} — {g.rubric}</span></p>)}
            </div>}
          </div>
        </div>
      ) : (
        <main className="flex-1 grid grid-cols-2 gap-0 overflow-hidden">
          <section className="overflow-auto bg-slate-900 grid place-items-start p-2">
            <img alt={`page ${fact.page}`} className="w-full"
              src={`/api/pages/${fact.document_id}/${fact.page}.png`} />
          </section>
          <section className="overflow-auto p-6 bg-white">
            <div className="flex gap-2 mb-3">{reasonBadges(fact, data.t_auto)}</div>
            <p className="text-xs text-slate-500 font-mono">{fact.document_id} · page {fact.page}
              · fact {idx + 1}/{queue.length}</p>
            <h2 className="mt-2 font-mono text-sm text-blue-700">{fact.field_path}</h2>
            <p className="mt-1 text-2xl font-semibold text-slate-900">{fact.value}
              {fact.unit && <span className="text-base text-slate-500 ml-2">{fact.unit}</span>}</p>
            <p className="mt-3 text-sm text-slate-600 border-l-4 border-slate-300 pl-3 italic">
              “{fact.snippet}”</p>
            {fact.validation_flags?.length > 0 && (
              <ul className="mt-3 text-sm text-amber-800 bg-amber-50 rounded p-3">
                {fact.validation_flags.map((v, i) => <li key={i}>⚠ {v}</li>)}</ul>)}
            {fact.conflict_group_id && (
              <p className="mt-3 text-sm text-red-700">Conflicting values for this field appear
                adjacent in the queue — approve one, reject or correct the others.</p>)}
            {correcting ? (
              <div className="mt-5 flex gap-2">
                <input autoFocus value={correction} onChange={e => setCorrection(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') decide('correct'); if (e.key === 'Escape') setCorrecting(false) }}
                  placeholder="corrected value (Enter to save, Esc to cancel)"
                  className="flex-1 border rounded px-3 py-2 font-mono" />
                <button onClick={() => decide('correct')}
                  className="bg-blue-600 text-white px-4 rounded">Save</button>
              </div>
            ) : (
              <div className="mt-6 flex gap-3">
                <button onClick={() => decide('approve')}
                  className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-2 rounded">a · Approve</button>
                <button onClick={() => setCorrecting(true)}
                  className="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded">c · Correct</button>
                <button onClick={() => decide('reject')}
                  className="bg-rose-600 hover:bg-rose-500 text-white px-5 py-2 rounded">r · Reject</button>
              </div>)}
          </section>
        </main>)}
    </div>)
}
