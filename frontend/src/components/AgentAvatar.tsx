export const agentPalettes: Record<string, { color: string; glow: string; avatar: string }> = {
  orchestrator: { color: '#60a5fa', glow: 'shadow-blue-500/50', avatar: 'OR' },
  loadwatch: { color: '#f97316', glow: 'shadow-amber-500/50', avatar: 'LW' },
  netseer: { color: '#22d3ee', glow: 'shadow-cyan-500/50', avatar: 'NT' },
  taskwarden: { color: '#a855f7', glow: 'shadow-purple-500/50', avatar: 'TW' },
  sentinel: { color: '#ef4444', glow: 'shadow-red-500/50', avatar: 'SN' },
  ioguard: { color: '#10b981', glow: 'shadow-emerald-500/50', avatar: 'IO' },
  memsmith: { color: '#eab308', glow: 'shadow-yellow-400/50', avatar: 'MM' },
  firebreak: { color: '#f43f5e', glow: 'shadow-rose-500/50', avatar: 'FB' },
  caretaker: { color: '#8b5cf6', glow: 'shadow-violet-500/50', avatar: 'CK' },
  'agent-1': { color: '#38bdf8', glow: 'shadow-cyan-400/40', avatar: 'A1' },
  'agent-2': { color: '#34d399', glow: 'shadow-emerald-400/40', avatar: 'A2' },
  'agent-3': { color: '#f472b6', glow: 'shadow-pink-400/40', avatar: 'A3' },
};

export const moodColor: Record<string, string> = {
  stressed: 'bg-amber-500',
  concerned: 'bg-red-500',
  calm: 'bg-emerald-500',
  focused: 'bg-sky-500',
  unknown: 'bg-gray-400',
};

export function AgentAvatar({ id, mood }: { id: string; mood?: string }) {
  const palette = agentPalettes[id] || { color: '#94a3b8', glow: 'shadow-gray-400/50', avatar: 'AG' };
  const moodCls = moodColor[mood || 'unknown'] || 'bg-gray-400';
  return (
    <div
      className={`relative w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold shadow-lg ${palette.glow}`}
      style={{ background: palette.color }}
    >
      <span>{palette.avatar}</span>
      <span className={`absolute -bottom-1 right-0 w-3 h-3 rounded-full border border-white ${moodCls} animate-pulse`} />
    </div>
  );
}
