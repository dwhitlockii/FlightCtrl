import { useEffect, useMemo, useRef, useState } from 'react';
import { Panel } from './ui/Card';
import { Badge } from './ui/Badge';

type EventItem = {
  ts: number | string;
  type: string;
  message: string;
  mood?: string;
  metrics?: Record<string, unknown>;
};

type Props = {
  events: EventItem[];
  loading?: boolean;
};

const typeColor: Record<string, 'neutral' | 'info' | 'success' | 'warning' | 'danger'> = {
  info: 'info',
  warn: 'warning',
  warning: 'warning',
  error: 'danger',
  metric: 'success',
};

export function AgentEventConsole({ events, loading }: Props) {
  const [filter, setFilter] = useState<string>('all');
  const [pause, setPause] = useState(false);
  const [query, setQuery] = useState('');
  const viewRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    const base = filter === 'all' ? events : events.filter((e) => e.type === filter);
    if (!query.trim()) return base;
    return base.filter((e) => (e.message || '').toLowerCase().includes(query.toLowerCase()));
  }, [events, filter, query]);

  useEffect(() => {
    if (pause) return;
    if (viewRef.current) {
      viewRef.current.scrollTop = viewRef.current.scrollHeight;
    }
  }, [filtered, pause]);

  return (
    <Panel>
      <div className="flex items-center justify-between mb-2">
        <div className="font-semibold text-sm">Agent Event Log</div>
        <div className="flex items-center space-x-2 text-xs">
          {['all', 'info', 'warning', 'error', 'metric'].map((t) => (
            <button
              key={t}
              className={`px-2 py-1 rounded ${filter === t ? 'bg-slate-700 text-white' : 'bg-slate-800 text-gray-400'}`}
              onClick={() => setFilter(t)}
            >
              {t}
            </button>
          ))}
          <input className="bg-slate-900 border border-slate-700 rounded px-2 py-1" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
          <label className="flex items-center space-x-1">
            <input type="checkbox" checked={pause} onChange={() => setPause(!pause)} />
            <span>Pause</span>
          </label>
        </div>
      </div>
      <div ref={viewRef} className="bg-black text-green-200 text-xs rounded p-2 h-48 overflow-y-auto border border-slate-700">
        {loading && <div className="text-gray-400">Loading events...</div>}
        {filtered.map((ev, idx) => (
          <div key={idx} className="flex items-start space-x-2 mb-1">
            <span className="text-gray-500">{new Date(Number(ev.ts) * 1000 || Number(ev.ts)).toLocaleTimeString()}</span>
            <Badge variant={typeColor[ev.type] || 'neutral'}>{ev.type}</Badge>
            <span className="text-gray-100">{ev.message}</span>
          </div>
        ))}
        {filtered.length === 0 && !loading && <div className="text-gray-500">No events.</div>}
      </div>
    </Panel>
  );
}
