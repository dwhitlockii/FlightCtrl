import { motion } from 'framer-motion';
import type { Agent } from '../store';
import { AgentAvatar } from './AgentAvatar';
import { slideUp, staggerChildren } from './ui/motionPresets';
import { Badge } from './ui/Badge';
import { Card, Panel } from './ui/Card';

type Note = { summary?: string; usage?: string; ts?: number };

type AgentProfileData = {
  agent: Agent;
  personality: string;
  last_notes: Note[];
  state: string;
  current_task?: string | null;
};

type Props = {
  data: AgentProfileData | null;
  loading?: boolean;
};

const strengthsMap: Record<string, string[]> = {
  orchestrator: ['Coordination', 'Decision fusion', 'Load routing'],
  loadwatch: ['CPU/mem tuning', 'Load shedding'],
  netseer: ['Network anomalies', 'Flow analysis'],
  taskwarden: ['Prioritization', 'Dispatch'],
  sentinel: ['Threat detection', 'Policy enforcement'],
  ioguard: ['Disk pressure', 'IO throughput'],
  memsmith: ['Memory hygiene', 'Leak detection'],
  firebreak: ['Firewall policy', 'Ingress/egress'],
  caretaker: ['Self-modification', 'Maintenance'],
};

const weaknessesMap: Record<string, string[]> = {
  orchestrator: ['Needs accurate telemetry'],
  loadwatch: ['May over-shed under burst'],
  netseer: ['Relies on flow visibility'],
  taskwarden: ['Needs clear objectives'],
  sentinel: ['Can be overly strict'],
  ioguard: ['IO stats needed'],
  memsmith: ['Sensitive to noisy metrics'],
  firebreak: ['May block aggressively'],
  caretaker: ['Requires safeguards'],
};

export function AgentProfile({ data, loading }: Props) {
  if (loading) return <div className="text-gray-400 text-sm">Loading profile...</div>;
  if (!data) return <div className="text-gray-400 text-sm">Select an agent to view profile.</div>;
  const { agent, personality, last_notes, state } = data;
  const strengths = strengthsMap[agent.agent_id] || ['Reliable', 'Diligent'];
  const weaknesses = weaknessesMap[agent.agent_id] || ['None observed'];
  return (
    <Card>
      <div className="flex items-center space-x-3 mb-3">
        <AgentAvatar id={agent.agent_id} mood={agent.mood} />
        <div>
          <div className="text-lg font-semibold">{agent.agent_id} [{agent.role}]</div>
          <div className="text-xs text-gray-400">Personality: {personality || 'n/a'}</div>
          <Badge variant={state === 'running' ? 'success' : 'neutral'}>{state}</Badge>
        </div>
      </div>
      <Panel className="mb-3">
        <div className="text-sm font-semibold mb-1">Current Task</div>
        <div className="text-sm text-gray-300">{agent.task || 'Idle'}</div>
      </Panel>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <Panel>
          <div className="text-sm font-semibold mb-1">Strengths</div>
          <ul className="text-sm text-gray-300 space-y-1">
            {strengths.map((s) => <li key={s}>• {s}</li>)}
          </ul>
        </Panel>
        <Panel>
          <div className="text-sm font-semibold mb-1">Weaknesses</div>
          <ul className="text-sm text-gray-300 space-y-1">
            {weaknesses.map((s) => <li key={s}>• {s}</li>)}
          </ul>
        </Panel>
      </div>
      <div className="text-sm font-semibold mb-1">Last 5 Notes</div>
      <motion.div variants={staggerChildren} initial="initial" animate="animate" className="space-y-2">
        {last_notes && last_notes.length > 0 ? last_notes.map((note, idx) => (
          <motion.div key={idx} variants={slideUp} className="text-xs text-gray-300 border border-slate-700 rounded px-3 py-2">
            <div className="font-medium text-gray-100">{note.summary ?? 'n/a'}</div>
            {note.usage && <div className="text-gray-400">Use: {note.usage}</div>}
          </motion.div>
        )) : <div className="text-xs text-gray-500">No notes yet.</div>}
      </motion.div>
    </Card>
  );
}
