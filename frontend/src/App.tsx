import { useState, useEffect, useMemo, useCallback } from 'react';
import 'primereact/resources/themes/lara-light-blue/theme.css';
import 'primereact/resources/primereact.min.css';
import 'primeicons/primeicons.css';
import './index.css';
import { useAgentStore, type Task } from './store';
import { Card, Panel } from './components/ui/Card';
import { Button } from './components/ui/Button';
import { Badge } from './components/ui/Badge';
import { TabBar } from './components/ui/TabBar';
import { ToastProvider } from './components/ui/ToastProvider';
import { AgentAvatar } from './components/AgentAvatar';
import { AgentProfile } from './components/AgentProfile';
import { AgentEventConsole } from './components/AgentEventConsole';
import { Drawer } from './components/ui/Drawer';
import { Modal } from './components/ui/Modal';

type Health = {
  status: string;
  timestamp: number;
  system: string;
  release: string;
};
type Metrics = {
  cpu: number | null;
  memory: Record<string, unknown> | null;
  disk: Record<string, unknown> | null;
  note?: string;
  platform?: string;
  source_type?: string;
  freshness_seconds?: number | null;
  provenance?: {
    source_type?: string;
    collectors?: string[];
    privilege_level?: string;
    last_success_at?: Record<string, number | null>;
  };
  unavailable?: { metric: string; reason: string; remediation: string }[];
  confidence?: number;
};
type ChatMessage = {
  messageId: string;
  parentId?: string | null;
  incidentId?: string | null;
  role: string;
  content: string;
  agentId?: string;
  streaming?: boolean;
  ts: number;
};

const formatValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const withAuthHeaders = (headers: HeadersInit | undefined, token: string | null) => {
  const finalHeaders = new Headers(headers || {});
  if (token && !finalHeaders.has('Authorization')) {
    finalHeaders.set('Authorization', `Bearer ${token}`);
  }
  return finalHeaders;
};

const toPercent = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return null;
};

const formatPercent = (value: number | null): string => {
  if (value === null) return 'n/a';
  return `${Math.round(value)}%`;
};

function Gauge({ label, value, color }: { label: string; value: number | null; color: string }) {
  const v = typeof value === 'number' ? Math.min(Math.max(value, 0), 100) : 0;
  const display = typeof value === 'number' ? `${Math.round(v)}%` : '--';
  return (
    <div className="flex flex-col items-center">
      <div
        className="w-20 h-20 rounded-full grid place-items-center text-sm font-semibold"
        style={{
          background: `conic-gradient(${color} ${v}%, #1f2937 ${v}% 100%)`,
          color: '#e2e8f0',
        }}
      >
        <div className="w-14 h-14 rounded-full bg-slate-900 grid place-items-center text-xs">{display}</div>
      </div>
      <div className="mt-1 text-xs text-gray-400">{label}</div>
    </div>
  );
}

export default function App() {
  // --- Chat State ---
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [newTaskDesc, setNewTaskDesc] = useState('');
  const [newTaskAgent, setNewTaskAgent] = useState('');
  const [newTaskPriority, setNewTaskPriority] = useState<'low' | 'normal' | 'high' | 'critical'>('normal');
  const [pollDelay, setPollDelay] = useState(10000);
  const [quickTaskDesc, setQuickTaskDesc] = useState('Diagnostics sweep');
  const [activeTab, setActiveTab] = useState<'overview' | 'chat' | 'agents' | 'tasks' | 'network' | 'warroom' | 'council'>('overview');
  const [theme, setTheme] = useState<'cyber' | 'jet' | 'starship' | 'minimal' | 'hacker'>('cyber');
  const [isPaletteOpen, setIsPaletteOpen] = useState(false);
  const [showStatusBar, setShowStatusBar] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [showSplash, setShowSplash] = useState(true);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [agentProfile, setAgentProfile] = useState<any | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [flows, setFlows] = useState<{ host: string; host_ip?: string; source_type?: string; note?: string; flows: any[]; platform?: string; freshness_seconds?: number | null; provenance?: any; unavailable?: any[]; confidence?: number } | null>(null);
  const [diskIo, setDiskIo] = useState<{ latest?: any; history?: any[]; platform?: string; source_type?: string; freshness_seconds?: number | null; provenance?: any; unavailable?: any[]; confidence?: number } | null>(null);
  const [firewallEvents, setFirewallEvents] = useState<{ events: any[]; platform?: string; source_type?: string; freshness_seconds?: number | null; provenance?: any; unavailable?: any[]; confidence?: number } | null>(null);
  const [firewallRulesState, setFirewallRulesState] = useState<{ rules: any[]; platform?: string; source_type?: string; freshness_seconds?: number | null; provenance?: any; unavailable?: any[]; confidence?: number } | null>(null);
  const [metricsHistory, setMetricsHistory] = useState<any[]>([]);
  const [automations, setAutomations] = useState<any[]>([]);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [autoName, setAutoName] = useState('Heartbeat');
  const [autoInterval, setAutoInterval] = useState(60);
  const [autoAction, setAutoAction] = useState<'notify' | 'create_task'>('notify');
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [taskMessages, setTaskMessages] = useState<any[]>([]);
  const [taskMessageInput, setTaskMessageInput] = useState('');
  const [timeline, setTimeline] = useState<any[]>([]);
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [replayIndex, setReplayIndex] = useState(0);
  const [councilResult, setCouncilResult] = useState<any | null>(null);
  const [councilQuestion, setCouncilQuestion] = useState('What is the biggest risk right now?');
  const [agentEvents, setAgentEvents] = useState<any[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [incidentFilter, setIncidentFilter] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState<string>('');
  const [keywordFilter, setKeywordFilter] = useState<string>('');
  const [typingAgents, setTypingAgents] = useState<Record<string, 'typing' | 'thinking'>>({});
  const authToken = useAgentStore((s) => s.authToken);
  const refreshToken = useAgentStore((s) => s.refreshToken);
  const refreshAuth = useAgentStore((s) => s.refreshAuth);
  const setAuthTokens = useAgentStore((s) => s.setAuthTokens);
  const clearAuth = useAgentStore((s) => s.clearAuth);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginLoading, setLoginLoading] = useState(false);
  const agents = useAgentStore((s) => s.agents);
  const agentsLoading = useAgentStore((s) => s.agentsLoading);
  const agentsError = useAgentStore((s) => s.agentsError);
  const fetchAgents = useAgentStore((s) => s.fetchAgents);
  const tasks = useAgentStore((s) => s.tasks);
  const tasksLoading = useAgentStore((s) => s.tasksLoading);
  const tasksError = useAgentStore((s) => s.tasksError);
  const fetchTasks = useAgentStore((s) => s.fetchTasks);
  const createTask = useAgentStore((s) => s.createTask);
  const cpuPercent = toPercent(metrics?.cpu);
  const memPercent = toPercent(metrics?.memory?.['percent']);
  const diskPercent = toPercent(metrics?.disk?.['percent']);
  const flowSummary = useMemo(() => {
    const list = flows?.flows ?? [];
    let allowed = 0;
    let blocked = 0;
    let unknown = 0;
    list.forEach((flow) => {
      if (flow.allowed === true) {
        allowed += 1;
      } else if (flow.allowed === false) {
        blocked += 1;
      } else {
        unknown += 1;
      }
    });
    return { total: list.length, allowed, blocked, unknown };
  }, [flows]);
  const diskIops = typeof diskIo?.latest?.iops === 'number' ? diskIo.latest.iops : null;
  const diskThroughput = typeof diskIo?.latest?.throughput_mb === 'number' ? diskIo.latest.throughput_mb : null;
  const firewallMeta = firewallRulesState ?? firewallEvents;

  const handleUnauthorized = useCallback(() => {
    if (authToken || refreshToken) {
      setLoginError('Session expired. Please log in again.');
    }
    clearAuth();
    setLoginOpen(true);
  }, [authToken, refreshToken, clearAuth]);

  const authFetch = useCallback(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const res = await fetch(input, {
      ...init,
      headers: withAuthHeaders(init.headers, authToken),
    });
    if (res.status !== 401) return res;
    const refreshed = await refreshAuth();
    if (!refreshed) {
      handleUnauthorized();
      return res;
    }
    const retry = await fetch(input, {
      ...init,
      headers: withAuthHeaders(init.headers, refreshed),
    });
    if (retry.status === 401) {
      handleUnauthorized();
    }
    return retry;
  }, [authToken, refreshAuth, handleUnauthorized]);

  const resolveWsUrl = useCallback(() => {
    const envUrl = import.meta.env.VITE_WS_URL as string | undefined;
    const base = envUrl ?? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/chat`;
    if (!authToken) return base;
    const url = new URL(base, window.location.origin);
    url.searchParams.set('token', authToken);
    return url.toString();
  }, [authToken]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const healthRes = await authFetch("/api/health");
        if (healthRes.ok) setHealth(await healthRes.json());
        const metricsRes = await authFetch("/api/metrics");
        if (metricsRes.ok) setMetrics(await metricsRes.json());
        const flowRes = await authFetch("/api/network/flows");
        if (flowRes.ok) setFlows(await flowRes.json());
        const diskRes = await authFetch("/api/disk/io");
        if (diskRes.ok) setDiskIo(await diskRes.json());
        const fwEvRes = await authFetch("/api/firewall/events");
        if (fwEvRes.ok) {
          const data = await fwEvRes.json();
          setFirewallEvents(data?.events ? data : { events: data });
        }
        const fwRulesRes = await authFetch("/api/firewall/rules");
        if (fwRulesRes.ok) {
          const data = await fwRulesRes.json();
          setFirewallRulesState(data?.rules ? data : { rules: data });
        }
        const histRes = await authFetch("/api/metrics/history?resolution=120");
        if (histRes.ok) setMetricsHistory(await histRes.json());
        const autoRes = await authFetch("/api/automations");
        if (autoRes.ok) setAutomations(await autoRes.json());
        const timelineRes = await authFetch("/api/timeline");
        if (timelineRes.ok) setTimeline(await timelineRes.json());
        const snapRes = await authFetch("/api/replay/snapshots");
        if (snapRes.ok) setSnapshots(await snapRes.json());
        await fetchAgents();
        await fetchTasks();
        setPollDelay(10000);
      } catch (err) {
        setPollDelay((d) => Math.min(d * 2, 60000));
        console.error("Polling error", err);
      } finally {
        timer = setTimeout(poll, pollDelay);
      }
    };
    if (!loginOpen || authToken) {
      poll();
    }
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [authFetch, authToken, fetchAgents, fetchTasks, loginOpen, pollDelay]);

  useEffect(() => {
    if (agents.length > 0 && !newTaskAgent) {
      setNewTaskAgent(agents[0].agent_id);
    }
    if (agents.length > 0 && !selectedAgentId) {
      setSelectedAgentId(agents[0].agent_id);
    }
  }, [agents, newTaskAgent, selectedAgentId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (authToken) {
      setLoginOpen(false);
      setLoginError(null);
    } else {
      setLoginOpen(true);
    }
  }, [authToken]);

  useEffect(() => {
    const timer = setTimeout(() => setShowSplash(false), 1500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    let socket: WebSocket | null = null;
    const connect = () => {
      if (!authToken && loginOpen) return;
      socket = new WebSocket(resolveWsUrl());
      setWs(socket);
      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: 'hello', message: 'Client connected' }));
      };
      socket.onclose = () => {
        setTimeout(connect, 2000);
      };
      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'agent_typing' || data.type === 'agent_thinking') {
          const agentId = data.agent_id || data.agentId || 'agent';
          setTypingAgents((prev) => ({ ...prev, [agentId]: data.type === 'agent_typing' ? 'typing' : 'thinking' }));
          setTimeout(() => {
            setTypingAgents((prev) => {
              const clone = { ...prev };
              delete clone[agentId];
              return clone;
            });
          }, 4000);
          return;
        }
        if (data.type === 'message_chunk' || data.type === 'message_complete') {
          const mid = data.messageId || data.id || `${Date.now()}`;
          setMessages((msgs) => {
            const existing = msgs.find((m) => m.messageId === mid);
            if (existing) {
              return msgs.map((m) =>
                m.messageId === mid
                  ? { ...m, content: formatValue(data.chunk ? `${m.content}${data.chunk}` : (data.content ?? m.content)), streaming: data.type === 'message_chunk' }
                  : m
              );
            }
            const newMsg: ChatMessage = {
              messageId: mid,
              parentId: data.parentId || null,
              incidentId: data.incidentId || null,
              role: data.role || 'agent',
              agentId: data.agent_id || data.agentId,
              content: formatValue(data.content ?? data.chunk ?? ''),
              streaming: data.type === 'message_chunk',
              ts: Date.now() / 1000,
            };
            return [...msgs, newMsg];
          });
          return;
        }
        if (data.role === 'agent') {
          const mid = data.messageId || `${Date.now()}-${Math.random()}`;
          setMessages((msgs) => [...msgs, {
            messageId: mid,
            parentId: data.parentId || null,
            incidentId: data.incidentId || null,
            role: 'agent',
            agentId: data.agent_id || 'agent',
            content: formatValue(data.response ?? data.content),
            ts: Date.now() / 1000,
          }]);
        }
      };
    };
    connect();
    return () => socket?.close();
  }, [authToken, loginOpen, resolveWsUrl]);

  useEffect(() => {
    const loadProfile = async () => {
      if (!selectedAgentId) return;
      setProfileLoading(true);
      try {
        const res = await authFetch(`/api/agents/${selectedAgentId}/profile`);
        if (res.ok) {
          const data = await res.json();
          setAgentProfile(data);
        } else {
          setAgentProfile(null);
        }
      } catch {
        setAgentProfile(null);
      } finally {
        setProfileLoading(false);
      }
    };
    const loadEvents = async () => {
      if (!selectedAgentId) return;
      setEventsLoading(true);
      try {
        const res = await authFetch(`/api/agents/${selectedAgentId}/events?limit=100`);
        if (res.ok) {
          const data = await res.json();
          setAgentEvents(data || []);
        } else {
          setAgentEvents([]);
        }
      } catch {
        setAgentEvents([]);
      } finally {
        setEventsLoading(false);
      }
    };
    loadProfile();
    loadEvents();
  }, [authFetch, selectedAgentId]);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const mid = `${Date.now()}-${Math.random()}`;
    setMessages((msgs) => [...msgs, { messageId: mid, role: 'user', parentId: replyTo?.messageId || null, incidentId: replyTo?.incidentId || null, content: input, ts: Date.now() / 1000 }]);
    setInput('');
    setReplyTo(null);
    setLoading(true);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ agent_id: 'agent-1', prompt: input, parentId: replyTo?.messageId || null, incidentId: replyTo?.incidentId || null }));
    }
    setLoading(false);
  };


  const handleCreateTask = async () => {
    if (!newTaskDesc.trim() || !newTaskAgent) return;
    await createTask(newTaskDesc, newTaskAgent, newTaskPriority);
    setNewTaskDesc('');
  };

  const handleQuickCommands = async () => {
    const desc = quickTaskDesc || 'Diagnostics sweep';
    const target = newTaskAgent || (agents[0]?.agent_id ?? 'orchestrator');
    await createTask(desc, target, newTaskPriority);
  };

  const openTask = async (task: Task) => {
    setSelectedTask(task);
    try {
      const res = await authFetch(`/api/tasks/${task.id}/messages`);
      if (res.ok) {
        setTaskMessages(await res.json());
      } else {
        setTaskMessages([]);
      }
    } catch {
      setTaskMessages([]);
    }
  };

  const sendTaskMessage = async () => {
    if (!selectedTask || !taskMessageInput.trim()) return;
    const payload = { role: 'user', content: taskMessageInput };
    await authFetch(`/api/tasks/${selectedTask.id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setTaskMessageInput('');
    openTask(selectedTask);
    // also echo into main chat for linkage
    setMessages((msgs) => [...msgs, { messageId: `${Date.now()}-task`, role: 'user', incidentId: selectedTask.id, content: `[task ${selectedTask.id}] ${payload.content}`, ts: Date.now() / 1000 } as any]);
  };

  const handleCreateAutomation = async () => {
    const payload = {
      name: autoName || 'Automation',
      trigger: { type: 'interval', seconds: autoInterval },
      action: autoAction === 'notify'
        ? { type: 'notify', agent_id: 'orchestrator', message: 'Automation ping' }
        : { type: 'create_task', agent_id: newTaskAgent || 'taskwarden', description: 'Auto-created task', priority: newTaskPriority },
    };
    await authFetch('/api/automations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const res = await authFetch('/api/automations');
    if (res.ok) setAutomations(await res.json());
  };

  const runCouncil = async () => {
    const res = await authFetch('/api/council/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: councilQuestion }),
    });
    if (res.ok) setCouncilResult(await res.json());
  };

  const exportCouncilMarkdown = () => {
    if (!councilResult) return;
    const lines: string[] = [];
    lines.push(`# Council Session`);
    lines.push(`Question: ${formatValue(councilResult.question)}`);
    lines.push(``);
    lines.push(`## Responses`);
    (councilResult.responses || []).forEach((r: any) => {
      lines.push(`- **${r.agent}** (${r.mood}): ${formatValue(r.content)}`);
    });
    lines.push(``);
    lines.push(`## Votes`);
    lines.push(`Most likely cause: ${JSON.stringify(councilResult.votes?.most_likely_cause || {})}`);
    lines.push(`Best fix: ${JSON.stringify(councilResult.votes?.best_fix || {})}`);
    lines.push(``);
    lines.push(`Summary: ${formatValue(councilResult.summary)}`);
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'council-session.md'; a.click();
    URL.revokeObjectURL(url);
  };

  const filteredMessages = useMemo(() => {
    return messages.filter((m) => {
      if (incidentFilter && m.incidentId !== incidentFilter) return false;
      if (agentFilter && m.agentId !== agentFilter && m.role === 'agent') return false;
      if (keywordFilter && !m.content.toLowerCase().includes(keywordFilter.toLowerCase())) return false;
      return true;
    });
  }, [messages, incidentFilter, agentFilter, keywordFilter]);

  const renderThreads = () => {
    const byId: Record<string, ChatMessage> = {};
    filteredMessages.forEach((m) => { byId[m.messageId] = { ...m, children: [] as ChatMessage[] } as any; });
    const roots: ChatMessage[] = [];
    filteredMessages.forEach((m) => {
      const node = byId[m.messageId] as any;
      if (m.parentId && byId[m.parentId]) {
        (byId[m.parentId] as any).children.push(node);
      } else {
        roots.push(node);
      }
    });
    const renderNode = (node: any, depth = 0) => (
      <div key={node.messageId} className={`flex ${node.role === 'user' ? 'justify-end' : 'justify-start'}`}>
        {node.role !== 'user' && <AgentAvatar id={node.agentId || 'agent'} mood={agents.find(a => a.agent_id === node.agentId)?.mood} />}
        <div className={`max-w-xl px-4 py-3 rounded-2xl shadow-lg ${node.role === 'user' ? 'bg-blue-600 text-white ml-2' : 'bg-slate-800 text-gray-100 mr-2 border border-slate-700'}`} style={{ marginLeft: depth ? depth * 16 : 0 }}>
          <div className="text-sm">{formatValue(node.content)}</div>
          <div className="text-[11px] text-gray-300 mt-1 flex space-x-3 items-center">
            <span>{new Date(node.ts * 1000).toLocaleTimeString()}</span>
            <span>⚙ CPU {formatPercent(cpuPercent)}</span>
            <button className="text-xs underline" onClick={() => setReplyTo(node)}>Reply</button>
          </div>
          {node.children && node.children.length > 0 && (
            <div className="mt-2 space-y-2">
              {node.children.map((child: any) => renderNode(child, depth + 1))}
            </div>
          )}
        </div>
        {node.role === 'user' && <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white ml-2">🙂</div>}
      </div>
    );
    return roots.map((r) => renderNode(r));
  };

  type PaletteAction = { label: string; action: () => void | Promise<void> };
  const paletteActions: PaletteAction[] = [
    { label: 'Restart orchestrator', action: () => authFetch('/api/agents/orchestrator/start', { method: 'POST' }) },
    { label: 'Fetch agents', action: fetchAgents },
    { label: 'Fetch tasks', action: fetchTasks },
    { label: 'Run diagnostics command', action: () => handleQuickCommands() },
    { label: 'Switch to Overview', action: () => setActiveTab('overview') },
    { label: 'Switch to Chat', action: () => setActiveTab('chat') },
    { label: 'Switch to Agents', action: () => setActiveTab('agents') },
    { label: 'Switch to Tasks', action: () => setActiveTab('tasks') },
    { label: 'Switch to Network', action: () => setActiveTab('network') },
    { label: 'Switch to War Room', action: () => setActiveTab('warroom') },
    { label: 'Switch to Council', action: () => setActiveTab('council') },
  ];

  const handleLogin = async () => {
    if (!loginUsername.trim() || !loginPassword) {
      setLoginError('Enter a username and password.');
      return;
    }
    setLoginLoading(true);
    setLoginError(null);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setLoginError(data?.detail || 'Login failed.');
        return;
      }
      const data = await res.json();
      setAuthTokens(data.access_token, data.refresh_token);
      setLoginPassword('');
      setLoginError(null);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : 'Login failed.');
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = () => {
    clearAuth();
    setLoginOpen(true);
  };

  return (
    <ToastProvider>
    <div className="app-shell">
      {showGrid && <div className="pointer-events-none absolute inset-0 app-grid" />}
      <div className="pointer-events-none absolute inset-0 app-veil" />
      {showSplash && (
        <div className="app-splash">
          <div className="splash-spinner"></div>
          <div className="splash-title">Bringing agents online…</div>
          <div className="splash-subtitle">
            <div>orchestrator: initializing subsystems</div>
            <div>loadwatch: subscribing to metrics</div>
            <div>firebreak: loading firewall rules</div>
          </div>
        </div>
      )}
      {/* Header */}
      <header className="app-header">
        <div className="app-header-left">
          <div className="app-logo">
            <span>FC</span>
          </div>
          <div>
            <div className="app-title">FlightCtrl Command</div>
            <div className="app-subtitle">Live multi-agent operations</div>
          </div>
        </div>
        <div className="app-header-right">
          <div className={`app-pill ${ws?.readyState === WebSocket.OPEN ? 'online' : 'offline'}`}>
            WS {ws?.readyState === WebSocket.OPEN ? 'online' : 'reconnecting'}
          </div>
          <Button size="sm" variant="ghost" onClick={() => setShowGrid((v) => !v)}>
            {showGrid ? 'Hide grid' : 'Show grid'}
          </Button>
          <select
            className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
            value={theme}
            onChange={(e) => setTheme(e.target.value as any)}
          >
            <option value="cyber">Cyberpunk</option>
            <option value="jet">Jet Cockpit</option>
            <option value="starship">Starship</option>
            <option value="minimal">Minimal White</option>
            <option value="hacker">Hacker Green</option>
          </select>
          {authToken ? (
            <Button size="sm" variant="ghost" onClick={handleLogout}>
              Sign out
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setLoginOpen(true)}>
              Sign in
            </Button>
          )}
          <Button size="sm" onClick={() => setIsPaletteOpen(true)}>
            Ctrl/Cmd+K
          </Button>
        </div>
      </header>
      {showStatusBar && (
        <div className="app-statusbar">
          <div className="flex items-center space-x-2">
            <span className="status-dot"></span>
            <span>Health: {health ? `${health.status}` : 'loading'}</span>
          </div>
          <div>CPU: {formatPercent(cpuPercent)}</div>
          <div>Agents: {agents.length}</div>
          <div>Tasks: {tasks.length}</div>
          <div>WS: {ws ? (ws.readyState === WebSocket.OPEN ? 'Connected' : 'Connecting') : 'N/A'}</div>
          <button className="ml-auto text-xs underline" onClick={() => setShowStatusBar(false)}>hide</button>
        </div>
      )}
      <div className="app-body">
        {/* Sidebar */}
        <aside className="app-rail">
          <TabBar className="rail-nav">
            {[
              { key: 'overview', label: 'Overview' },
              { key: 'chat', label: 'Chat' },
              { key: 'agents', label: 'Agents' },
              { key: 'tasks', label: 'Tasks' },
              { key: 'network', label: 'Network' },
              { key: 'warroom', label: 'War Room' },
              { key: 'council', label: 'Council' },
            ].map((tab) => (
              <TabBar.Item
                key={tab.key}
                active={activeTab === tab.key}
                onClick={() => setActiveTab(tab.key as any)}
              >
                <span>{tab.label}</span>
              </TabBar.Item>
            ))}
          </TabBar>
          <div className="rail-title">Agents</div>
          {agentsLoading && <div className="text-gray-400">Loading agents...</div>}
          {agentsError && <div className="text-red-500">Error: {agentsError}</div>}
          <ul className="space-y-2">
            {agents.map((agent) => (
              <Panel key={agent.agent_id} className="flex flex-col space-y-1">
                <div className="flex items-center space-x-3">
                  <AgentAvatar id={agent.agent_id} mood={agent.mood} />
                  <div className="flex flex-col">
                    <div className="flex items-center space-x-2">
                      <span className="font-medium">{agent.agent_id}</span>
                      <span className={`px-2 py-0.5 text-xs rounded-full ${agent.status === 'running' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-700 text-slate-300'}`}>
                        {agent.status}
                      </span>
                      <span className="ml-1 text-xs text-gray-400">[{agent.role}]</span>
                    </div>
                    {(() => {
                      const notes = Array.isArray((agent.learning_state as any)?.notes) ? (agent.learning_state as any).notes as { summary?: string }[] : [];
                      const last = notes.length > 0 ? notes[notes.length - 1] : null;
                      return last ? (
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          Last note: {last.summary ?? 'n/a'}
                        </div>
                      ) : (
                        <div className="text-xs text-gray-500 dark:text-gray-400">No notes yet.</div>
                      );
                    })()}
                  </div>
                </div>
              </Panel>
            ))}
          </ul>
          {/* Task list section */}
          <div className="rail-title">Tasks</div>
          {tasksLoading && <div className="text-gray-400">Loading tasks...</div>}
          {tasksError && <div className="text-red-500">Error: {tasksError}</div>}
          <div className="space-y-2">
            {tasks.length === 0 && !tasksLoading && <div className="text-gray-400">No tasks</div>}
            {tasks.map((task) => (
              <Panel key={task.id} className="flex flex-col space-y-1">
                <span className="text-sm font-medium text-gray-100">{task.description}</span>
                <span className="text-xs text-gray-400">Agent: {task.agent_id}</span>
                <span className="text-xs text-gray-500">Created: {new Date(task.created_at * 1000).toLocaleString()}</span>
                <span className={
                  task.status === 'completed'
                    ? 'text-green-400'
                    : task.status === 'in_progress'
                    ? 'text-blue-400'
                    : task.status === 'failed'
                    ? 'text-red-400'
                    : 'text-gray-400'
                }>
                  {task.status}
                </span>
              </Panel>
            ))}
          </div>
          <div className="rail-form">
            <input
              className="rail-input"
              value={newTaskDesc}
              onChange={(e) => setNewTaskDesc(e.target.value)}
            />
            <select
              className="rail-input"
              value={newTaskAgent}
              onChange={(e) => setNewTaskAgent(e.target.value)}
            >
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>{a.agent_id} [{a.role}]</option>
              ))}
            </select>
            <div className="rail-inline">
              <input
                className="rail-input"
                value={quickTaskDesc}
                onChange={(e) => setQuickTaskDesc(e.target.value)}
              />
              <button
                className="rail-action"
                onClick={handleQuickCommands}
                disabled={tasksLoading || agents.length === 0}
              >
                Run
              </button>
            </div>
            <button
              className="rail-cta"
              onClick={handleCreateTask}
              disabled={!newTaskDesc.trim() || !newTaskAgent || tasksLoading}
            >
              {tasksLoading ? 'Saving...' : 'Create Task'}
            </button>
          </div>
        </aside>
        {/* Main Panel */}
        <main className="app-main">
          <div className="main-hero">
            <div>
              <div className="hero-kicker">Live Control Surface</div>
              <div className="hero-title">Operations Canvas</div>
              <div className="hero-subtitle">Streaming telemetry, agent coordination, and incident response in one place.</div>
            </div>
            <div className="hero-stats">
              <div className="hero-stat">
                <span>CPU</span>
                <strong>{formatPercent(cpuPercent)}</strong>
              </div>
              <div className="hero-stat">
                <span>Memory</span>
                <strong>{formatPercent(memPercent)}</strong>
              </div>
              <div className="hero-stat">
                <span>Disk</span>
                <strong>{formatPercent(diskPercent)}</strong>
              </div>
              <div className="hero-stat">
                <span>Agents</span>
                <strong>{agents.length}</strong>
              </div>
              <div className="hero-stat">
                <span>Tasks</span>
                <strong>{tasks.length}</strong>
              </div>
            </div>
          </div>
          {activeTab === 'chat' && (
            <Card className="flex-1 flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <div className="font-semibold text-lg">Agent & User Chat</div>
                <div className="flex space-x-2 text-xs">
                  <select className="bg-slate-800 border border-slate-700 rounded px-2 py-1" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
                    <option value="">All agents</option>
                    {agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.agent_id}</option>)}
                  </select>
                  <input className="bg-slate-800 border border-slate-700 rounded px-2 py-1" value={incidentFilter ?? ''} onChange={(e) => setIncidentFilter(e.target.value || null)} />
                  <input className="bg-slate-800 border border-slate-700 rounded px-2 py-1" value={keywordFilter} onChange={(e) => setKeywordFilter(e.target.value)} />
                </div>
              </div>
              {Object.keys(typingAgents).length > 0 && (
                <div className="text-xs text-emerald-300 mb-2">Agent is thinking...</div>
              )}
              <div className="flex-1 overflow-y-auto space-y-2">
                {messages.length === 0 && (
                  <div className="text-gray-400">[Chat messages will appear here]</div>
                )}
                {renderThreads()}
                {loading && <div className="text-gray-400 italic">Agent is typing...</div>}
              </div>
              <div className="mt-4 flex">
                <input
                  className="flex-1 border rounded-l px-3 py-2 focus:outline-none"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') sendMessage(); }}
                  disabled={loading}
                />
                <Button className="rounded-l-none" onClick={sendMessage} disabled={loading || !input.trim()}>
                  {loading ? 'Sending...' : 'Send'}
                </Button>
              </div>
            </Card>
          )}

          {activeTab === 'overview' && (
            <>
              <div className="grid grid-cols-3 gap-4">
                <Card>
                  <div className="font-semibold mb-2">System Metrics</div>
                  <div className="text-[11px] text-gray-400 mb-3">
                    Source: {metrics?.source_type || 'unknown'} | Freshness: {metrics?.freshness_seconds ?? 'n/a'}s
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-sm text-gray-200">
                    <Gauge label="CPU" value={cpuPercent} color="#60a5fa" />
                    <Gauge label="Memory" value={memPercent} color="#10b981" />
                    <Gauge label="Disk" value={diskPercent} color="#f59e0b" />
                  </div>
                </Card>
                <Card>
                  <div className="font-semibold mb-2">Agent Health</div>
                  {health ? (
                    <div className="text-sm text-gray-200 space-y-1">
                      <div>Status: {health.status}</div>
                      <div>System: {health.system} {health.release}</div>
                      <div>Timestamp: {new Date(health.timestamp * 1000).toLocaleString()}</div>
                    </div>
                  ) : (
                    <div className="text-gray-400">Waiting for health...</div>
                  )}
                </Card>
                <Card>
                  <div className="font-semibold mb-2">Diagnostics</div>
                  <div className="text-gray-300 text-sm space-y-1">
                    <div>WS: {ws ? (ws.readyState === WebSocket.OPEN ? 'Connected' : 'Connecting') : 'N/A'}</div>
                    <div>Next poll: {pollDelay / 1000}s</div>
                    <div>Agents: {agents.length}</div>
                  </div>
                </Card>
              </div>
              <Card>
                <div className="font-semibold mb-2">Trust & Provenance</div>
                <div className="grid md:grid-cols-2 gap-3 text-xs text-gray-300">
                  {[
                    { label: 'System Metrics', meta: metrics },
                    { label: 'Network Flows', meta: flows },
                    { label: 'Disk I/O', meta: diskIo },
                    { label: 'Firewall', meta: firewallMeta },
                  ].map((item) => (
                    <div key={item.label} className="rounded border border-white/10 p-3 space-y-1">
                      <div className="text-gray-100 font-medium">{item.label}</div>
                      <div>Platform: {item.meta?.platform || 'unknown'}</div>
                      <div>Source: {item.meta?.source_type || 'unknown'}</div>
                      <div>Freshness: {item.meta?.freshness_seconds ?? 'n/a'}s</div>
                      <div>Privilege: {item.meta?.provenance?.privilege_level || 'unknown'}</div>
                      <div>Collectors: {(item.meta?.provenance?.collectors || []).join(', ') || 'n/a'}</div>
                      <div>Confidence: {typeof item.meta?.confidence === 'number' ? item.meta?.confidence : 'n/a'}</div>
                      <div className="text-[11px] text-gray-400">
                        Unavailable: {item.meta?.unavailable?.length ? item.meta.unavailable.map((u: any) => `${u.metric} (${u.reason})`).join('; ') : 'none'}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
              <Card>
                <div className="font-semibold mb-2">Agent Tasks & Status</div>
                <div className="text-gray-300">Use the Tasks tab to dispatch commands and monitor progress.</div>
              </Card>
              <div className="grid grid-cols-3 gap-4 mt-4">
                <Card>
                  <div className="font-semibold mb-2">Network Flow Graph</div>
                  <div className="text-[11px] text-gray-400 mb-2">
                    Source: {flows?.source_type || 'unknown'} | Freshness: {flows?.freshness_seconds ?? 'n/a'}s
                    {flows?.host_ip ? ` | Host IP: ${flows.host_ip}` : ''}
                    {flows?.note ? ` | ${flows.note}` : ''}
                  </div>
                  <div className="text-xs text-gray-300 space-y-2">
                    {!flows && <div>Loading flows...</div>}
                    {flows && flows.flows.map((f) => (
                      <div key={f.remote} className="flex items-center justify-between">
                        <div>
                          <div className="font-semibold text-gray-100">{f.remote}</div>
                          <div className="text-[11px] text-gray-400">Threat {f.threat_score}</div>
                        </div>
                        <div className="flex-1 mx-2 h-2 rounded bg-slate-800 overflow-hidden">
                          <div className={`h-2 ${f.allowed ? 'bg-emerald-500' : 'bg-red-500'}`} style={{ width: `${Math.min(100, (f.bytes_in + f.bytes_out) / 2000)}%` }} />
                        </div>
                        <span className={`text-xs ${f.allowed ? 'text-emerald-400' : 'text-red-400'}`}>{f.allowed ? 'allowed' : 'blocked'}</span>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card>
                  <div className="font-semibold mb-2">Disk I/O Ripple</div>
                  {diskIo ? (
                    <div className="text-sm text-gray-200 space-y-2">
                      <div>IOPS: {diskIops ?? 'n/a'}</div>
                      <div>Throughput: {diskThroughput !== null ? diskThroughput.toFixed(1) : 'n/a'} MB/s</div>
                      <div className="h-24 bg-slate-900 rounded relative overflow-hidden">
                        <div className="absolute inset-0 flex items-end space-x-1 px-1">
                          {diskIo.history.slice(-40).map((p, idx) => {
                            if (typeof p.iops !== 'number') return null;
                            return (
                              <div key={idx} className="bg-blue-500/60" style={{ width: '4px', height: `${Math.min(100, p.iops / 20)}%` }}></div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  ) : <div className="text-gray-400 text-sm">Loading disk I/O...</div>}
                </Card>
                <Card>
                  <div className="font-semibold mb-2">Firewall Threats</div>
                  <div className="text-xs text-gray-300 space-y-1 max-h-40 overflow-y-auto">
                    {firewallEvents?.events?.map((ev, idx) => (
                      <div key={idx} className="flex items-center justify-between">
                        <span>{ev.ip || ev.source}</span>
                        <span className={ev.action === 'deny' || ev.action === 'blocked' ? 'text-red-400' : 'text-emerald-400'}>
                          {ev.action}
                        </span>
                        <span className="text-gray-500">{new Date((ev.ts || Date.now()) * 1000).toLocaleTimeString()}</span>
                      </div>
                    ))}
                    {(firewallEvents?.events?.length ?? 0) === 0 && <div className="text-gray-500">No firewall events yet.</div>}
                  </div>
                </Card>
              </div>
              <div className="grid grid-cols-2 gap-4 mt-4">
                <Card>
                  <div className="font-semibold mb-2">Historical Charts</div>
                  <div className="h-32 bg-slate-900 rounded relative overflow-hidden">
                    <svg viewBox="0 0 400 120" className="absolute inset-0">
                      {metricsHistory.length > 1 && (
                        <>
                          <polyline
                            fill="none"
                            stroke="#38bdf8"
                            strokeWidth="2"
                            points={metricsHistory.map((p, idx) => `${(idx / metricsHistory.length) * 400},${120 - p.cpu}`).join(' ')}
                          />
                          <polyline
                            fill="none"
                            stroke="#10b981"
                            strokeWidth="2"
                            points={metricsHistory.map((p, idx) => `${(idx / metricsHistory.length) * 400},${120 - p.mem}`).join(' ')}
                          />
                        </>
                      )}
                    </svg>
                  </div>
                  <div className="text-xs text-gray-400 mt-1">CPU (cyan) / MEM (green)</div>
                </Card>
                <Card>
                  <div className="font-semibold mb-2">Timeline & Replay</div>
                  <div className="max-h-32 overflow-y-auto text-xs text-gray-300 space-y-1">
                    {timeline.map((t, idx) => (
                      <div key={idx} className="flex items-center space-x-2">
                        <span className="text-gray-500">{new Date((t.ts || 0) * 1000).toLocaleTimeString()}</span>
                        <span className="uppercase tracking-wide text-[10px] px-1 rounded bg-slate-800 border border-slate-700">{t.type || 'event'}</span>
                        <span>{formatValue(t.message ?? t.action ?? t.type)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2">
                    <input type="range" min={0} max={Math.max(0, snapshots.length - 1)} value={replayIndex}
                      onChange={(e) => setReplayIndex(Number(e.target.value))}
                      className="w-full" />
                    {snapshots[replayIndex] && (
                      <div className="text-xs text-gray-300 mt-1">
                        Snapshot @ {new Date(snapshots[replayIndex].ts * 1000).toLocaleTimeString()} |
                        cpu {formatPercent(toPercent(snapshots[replayIndex].metrics?.cpu))} mem {formatPercent(toPercent(snapshots[replayIndex].metrics?.mem))}
                      </div>
                    )}
                  </div>
                </Card>
              </div>
            </>
          )}

          {activeTab === 'agents' && (
            <div className="grid grid-cols-2 gap-4 items-start">
              <Card>
                <div className="font-semibold mb-2">Agents</div>
                <div className="space-y-2 max-h-[600px] overflow-y-auto">
                  {agents.map((agent) => (
                    <Panel
                      key={agent.agent_id}
                      className={`flex items-center justify-between cursor-pointer ${selectedAgentId === agent.agent_id ? 'ring-2 ring-blue-500' : ''}`}
                      onClick={() => setSelectedAgentId(agent.agent_id)}
                    >
                      <div className="flex items-center space-x-2">
                        <AgentAvatar id={agent.agent_id} mood={agent.mood} />
                        <div>
                          <div className="font-semibold">{agent.agent_id}</div>
                          <div className="text-xs text-gray-400">{agent.role}</div>
                        </div>
                      </div>
                      <span className={`px-2 py-0.5 text-xs rounded-full ${agent.status === 'running' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-700 text-slate-300'}`}>
                        {agent.status}
                      </span>
                    </Panel>
                  ))}
                </div>
              </Card>
              <div className="space-y-3">
                <AgentProfile data={agentProfile} loading={profileLoading} />
                <AgentEventConsole events={agentEvents} loading={eventsLoading} />
                <Panel className="space-y-2">
                  <div className="font-semibold">Council Mode</div>
                  <textarea
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm"
                    value={councilQuestion}
                    onChange={(e) => setCouncilQuestion(e.target.value)}
                  />
                  <Button onClick={runCouncil}>Ask Council</Button>
                  {councilResult && (
                    <div className="text-xs text-gray-300 space-y-1">
                      <div className="font-medium text-gray-100">Summary</div>
                      <div>{formatValue(councilResult.summary)}</div>
                      <div className="font-medium text-gray-100 mt-2">Votes</div>
                      <div>Likely cause: {JSON.stringify(councilResult.votes?.most_likely_cause || {})}</div>
                      <div>Best fix: {JSON.stringify(councilResult.votes?.best_fix || {})}</div>
                    </div>
                  )}
                </Panel>
              </div>
            </div>
          )}

          {activeTab === 'tasks' && (
            <Card>
              <div className="font-semibold mb-2">Tasks</div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                    <div className="text-sm font-medium text-gray-700 dark:text-gray-200">Create Task</div>
                  <input
                    className="w-full border rounded px-3 py-2 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                    value={newTaskDesc}
                    onChange={(e) => setNewTaskDesc(e.target.value)}
                  />
                  <select
                    className="w-full border rounded px-3 py-2 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                    value={newTaskAgent}
                    onChange={(e) => setNewTaskAgent(e.target.value)}
                  >
                    {agents.map((a) => (
                      <option key={a.agent_id} value={a.agent_id}>{a.agent_id} [{a.role}]</option>
                    ))}
                  </select>
                  <select
                    className="w-full border rounded px-3 py-2 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                    value={newTaskPriority}
                    onChange={(e) => setNewTaskPriority(e.target.value as any)}
                  >
                    {['low','normal','high','critical'].map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                  <div className="flex space-x-2">
                    <input
                      className="flex-1 border rounded px-3 py-2 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                      value={quickTaskDesc}
                      onChange={(e) => setQuickTaskDesc(e.target.value)}
                    />
                    <Button tone="secondary" onClick={handleQuickCommands} disabled={tasksLoading || agents.length === 0}>
                      Run
                    </Button>
                  </div>
                  <Button className="w-full" onClick={handleCreateTask} disabled={!newTaskDesc.trim() || !newTaskAgent || tasksLoading}>
                    {tasksLoading ? 'Saving...' : 'Create Task'}
                  </Button>
                  {tasksError && <div className="text-red-500 text-sm">Error: {tasksError}</div>}
                </div>
                <div>
                  <div className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">Task List</div>
                  <div className="space-y-2 max-h-96 overflow-y-auto">
                    {tasks.length === 0 && !tasksLoading && <div className="text-gray-400">No tasks</div>}
                    {tasks.map((task) => (
                      <Panel key={task.id} className="flex flex-col space-y-1 cursor-pointer hover:border-blue-500" onClick={() => openTask(task)}>
                        <span className="text-sm font-medium text-gray-100">{task.description}</span>
                        <span className="text-xs text-gray-400">Agent: {task.agent_id}</span>
                        <span className="text-xs">
                          <span className={`px-2 py-0.5 rounded-full text-white ${task.priority === 'critical' ? 'bg-red-600' : task.priority === 'high' ? 'bg-orange-500' : task.priority === 'low' ? 'bg-slate-600' : 'bg-blue-600'}`}>
                            {task.priority}
                          </span>
                        </span>
                        <span className="text-xs text-gray-500">Created: {new Date(task.created_at * 1000).toLocaleString()}</span>
                        <span className={
                          task.status === 'completed'
                            ? 'text-green-400'
                            : task.status === 'in_progress'
                            ? 'text-blue-400'
                            : task.status === 'failed'
                            ? 'text-red-400'
                            : 'text-gray-400'
                        }>
                          {task.status}
                        </span>
                        <div className="text-[11px] text-gray-500 space-y-1">
                          {(task.status_history || []).slice(-4).map((h, idx) => (
                            <div key={idx} className="flex items-center space-x-2">
                              <span className="uppercase">{h.status}</span>
                              <span>{formatValue(h.note)}</span>
                              <span className="text-gray-600">{new Date(h.ts * 1000).toLocaleTimeString()}</span>
                            </div>
                          ))}
                        </div>
                      </Panel>
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-6">
                <div className="font-semibold mb-2">Automations</div>
                <div className="grid grid-cols-2 gap-4">
                  <Panel className="space-y-2">
                    <div className="text-sm font-medium">New Automation</div>
                    <input className="w-full border rounded px-3 py-2 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                      value={autoName} onChange={(e) => setAutoName(e.target.value)} />
                    <div className="flex items-center space-x-2">
                      <span className="text-sm text-gray-400">Every</span>
                      <input type="number" min={10} className="w-24 border rounded px-2 py-1 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                        value={autoInterval} onChange={(e) => setAutoInterval(Number(e.target.value))} />
                      <span className="text-sm text-gray-400">seconds</span>
                    </div>
                    <select className="w-full border rounded px-3 py-2 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                      value={autoAction} onChange={(e) => setAutoAction(e.target.value as any)}>
                      <option value="notify">Notify</option>
                      <option value="create_task">Create Task</option>
                    </select>
                    <Button onClick={handleCreateAutomation}>Save Automation</Button>
                  </Panel>
                  <Panel className="space-y-2 max-h-48 overflow-y-auto">
                    {automations.map((a) => (
                      <div key={a.id} className="border border-slate-700 rounded p-2 text-sm text-gray-200">
                        <div className="font-semibold">{a.name}</div>
                        <div className="text-xs text-gray-400">Trigger: {a.trigger?.type}</div>
                        <div className="text-xs text-gray-400">Action: {a.action?.type}</div>
                        <div className="text-xs text-gray-500">Last run: {a.last_run ? new Date(a.last_run * 1000).toLocaleTimeString() : 'never'}</div>
                      </div>
                    ))}
                    {automations.length === 0 && <div className="text-gray-500 text-sm">No automations defined.</div>}
                  </Panel>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'network' && (
            <Card>
              <div className="font-semibold mb-2">Network & Firewall Agent</div>
              <div className="grid grid-cols-2 gap-4">
                <Panel className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <AgentAvatar id="firebreak" mood={agents.find(a => a.agent_id === 'firebreak')?.mood} />
                    <div>
                      <div className="font-medium">Firebreak (firewall)</div>
                      <div className="text-xs text-gray-400">Ingress/egress guardian</div>
                    </div>
                  </div>
                  <div className="text-xs text-gray-500">WS: {ws ? (ws.readyState === WebSocket.OPEN ? 'Connected' : 'Connecting') : 'N/A'}</div>
                  <div className="text-sm text-gray-200">Active flows</div>
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {flows?.flows?.map((f) => (
                      <div key={f.remote} className="border border-slate-700 rounded p-2 text-xs text-gray-200">
                        <div className="flex justify-between items-center">
                          <span>{f.remote}</span>
                          <span className={f.allowed === false ? 'text-red-400' : f.allowed === true ? 'text-emerald-400' : 'text-slate-400'}>
                            {f.allowed === false ? 'blocked' : f.allowed === true ? 'allowed' : 'unknown'}
                          </span>
                        </div>
                        <div className="text-[11px] text-gray-400">Threat {f.threat_score}</div>
                        <div className="flex space-x-2 mt-1">
                          <Button size="sm" variant="outline" onClick={() => authFetch('/api/firewall/allow?ip=' + f.remote, { method: 'POST' })}>Allow</Button>
                          <Button size="sm" variant="outline" tone="danger" onClick={() => authFetch('/api/firewall/deny?ip=' + f.remote, { method: 'POST' })}>Deny</Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </Panel>
                <Panel className="space-y-2">
                  <div className="text-sm font-medium">Firewall Rules</div>
                  <div className="space-y-1 max-h-64 overflow-y-auto">
                    {firewallRulesState?.rules?.map((r) => (
                      <div key={r.id} className="text-xs text-gray-200 border border-slate-700 rounded px-2 py-1 flex items-center justify-between">
                        <span>{r.source} → {r.dest || 'host'}</span>
                        <span className={r.action === 'deny' ? 'text-red-400' : 'text-emerald-400'}>{r.action}</span>
                      </div>
                    ))}
                    {(firewallRulesState?.rules?.length ?? 0) === 0 && <div className="text-gray-500 text-sm">No rules defined.</div>}
                  </div>
                  <div className="text-sm font-medium mt-2">Recent events</div>
                  <div className="space-y-1 max-h-32 overflow-y-auto text-xs text-gray-300">
                    {firewallEvents?.events?.map((ev, idx) => (
                      <div key={idx} className="flex items-center space-x-2">
                        <span className={ev.action === 'deny' ? 'text-red-400' : 'text-emerald-400'}>{ev.action}</span>
                        <span>{ev.ip || ev.source}</span>
                        <span className="text-gray-500">{new Date((ev.ts || Date.now()) * 1000).toLocaleTimeString()}</span>
                      </div>
                    ))}
                  </div>
                </Panel>
              </div>
            </Card>
          )}

          {activeTab === 'warroom' && (
            <Card>
              <div className="flex items-center justify-between mb-3">
                <div className="font-semibold text-lg">Network War Room</div>
                <div className="text-xs text-gray-400">Live flows focus</div>
              </div>
              <div className="grid md:grid-cols-3 gap-4">
                <Panel className="md:col-span-2">
                  <div className="text-sm font-medium mb-2">Connection Graph</div>
                  <svg viewBox="0 0 600 360" className="w-full h-80 bg-slate-900 rounded-lg border border-slate-800">
                    <g>
                      <circle cx="300" cy="180" r="28" fill="#0ea5e9" opacity="0.7" />
                      <text x="300" y="185" textAnchor="middle" fontSize="12" fill="#fff">HOST</text>
                    </g>
                    {flows?.flows?.map((f, idx) => {
                      const angle = (idx / Math.max(1, flows.flows.length)) * Math.PI * 2;
                      const r = 130;
                      const x = 300 + r * Math.cos(angle);
                      const y = 180 + r * Math.sin(angle);
                      const width = Math.min(6, Math.max(2, (f.bytes_in + f.bytes_out) / 120000));
                      const color = f.allowed === false ? '#ef4444' : f.allowed === true ? '#22c55e' : '#94a3b8';
                      return (
                        <g key={f.remote} onClick={() => setSelectedNode(f.remote)} style={{ cursor: 'pointer' }}>
                          <line x1="300" y1="180" x2={x} y2={y} stroke={color} strokeWidth={width} strokeOpacity="0.7">
                            <animate attributeName="stroke-dashoffset" from="20" to="0" dur="1.2s" repeatCount="indefinite" />
                          </line>
                          <circle cx={x} cy={y} r="18" fill={color} fillOpacity="0.15" stroke={color} strokeWidth="2" />
                          <text x={x} y={y+4} textAnchor="middle" fontSize="10" fill="#e5e7eb">{f.remote.split('.').slice(-2).join('.')}</text>
                        </g>
                      );
                    })}
                  </svg>
                </Panel>
                <Panel className="space-y-2">
                  <div className="text-sm font-medium">Node Details</div>
                  {selectedNode ? (
                    (() => {
                      const f = flows?.flows?.find((x) => x.remote === selectedNode);
                      if (!f) return <div className="text-sm text-gray-400">Select a node.</div>;
                      return (
                        <div className="space-y-1 text-sm text-gray-200">
                          <div className="font-semibold text-gray-100">{f.remote}</div>
                          <div>Bytes in/out: {f.bytes_in}/{f.bytes_out}</div>
                          <div>Threat: {f.threat_score}</div>
                          <div className="flex space-x-2">
                            <Button size="sm" variant="outline" onClick={() => authFetch('/api/firewall/allow?ip=' + f.remote, { method: 'POST' })}>Allow</Button>
                            <Button size="sm" variant="outline" tone="danger" onClick={() => authFetch('/api/firewall/deny?ip=' + f.remote, { method: 'POST' })}>Deny</Button>
                          </div>
                        </div>
                      );
                    })()
                  ) : <div className="text-sm text-gray-400">Click a node to inspect.</div>}
                  <div className="text-sm font-medium mt-3">Traffic Summary</div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-1 bg-slate-700/50 text-slate-200 rounded">Total: {flowSummary.total}</span>
                    <span className="px-2 py-1 bg-emerald-500/20 text-emerald-300 rounded">Allowed: {flowSummary.allowed}</span>
                    <span className="px-2 py-1 bg-red-500/20 text-red-200 rounded">Blocked: {flowSummary.blocked}</span>
                    <span className="px-2 py-1 bg-amber-500/20 text-amber-200 rounded">Unknown: {flowSummary.unknown}</span>
                  </div>
                  <div className="text-sm font-medium mt-3">Firewall Timeline</div>
                  <div className="space-y-1 max-h-32 overflow-y-auto text-xs text-gray-300">
                    {firewallEvents?.events?.map((ev, idx) => (
                      <div key={idx} className="flex items-center space-x-2">
                        <span className={ev.action === 'deny' ? 'text-red-400' : 'text-emerald-400'}>{ev.action}</span>
                        <span>{ev.ip || ev.source}</span>
                        <span className="text-gray-500">{new Date((ev.ts || Date.now()) * 1000).toLocaleTimeString()}</span>
                      </div>
                    ))}
                  </div>
                </Panel>
              </div>
            </Card>
          )}

          {activeTab === 'council' && (
            <Card>
              <div className="flex items-center justify-between mb-3">
                <div className="font-semibold text-lg">Council Mode</div>
                <div className="text-xs text-gray-400">Multi-agent debate</div>
              </div>
              <div className="grid md:grid-cols-3 gap-3">
                <Panel className="md:col-span-2 space-y-3">
                  <div className="flex space-x-2">
                    <input
                      className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm"
                      value={councilQuestion}
                      onChange={(e) => setCouncilQuestion(e.target.value)}
                    />
                    <Button onClick={runCouncil}>Send</Button>
                    <Button variant="outline" onClick={() => {
                      if (!councilResult) return;
                      const blob = new Blob([JSON.stringify(councilResult, null, 2)], { type: 'application/json' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url; a.download = 'council-session.json'; a.click();
                      URL.revokeObjectURL(url);
                    }}>Export JSON</Button>
                    <Button variant="outline" onClick={exportCouncilMarkdown}>Export MD</Button>
                  </div>
                  {councilResult ? (
                    <>
                      <div className="grid grid-cols-2 gap-2">
                        {councilResult.responses?.map((r: any) => (
                          <Panel key={r.agent} className="space-y-1">
                            <div className="flex items-center space-x-2">
                              <AgentAvatar id={r.agent} mood={r.mood} />
                              <div className="font-semibold">{r.agent}</div>
                            </div>
                            <div className="text-xs text-gray-300">{formatValue(r.content)}</div>
                          </Panel>
                        ))}
                      </div>
                      <Panel>
                        <div className="font-semibold text-sm">Summary</div>
                        <div className="text-sm text-gray-200">{formatValue(councilResult.summary)}</div>
                        <div className="mt-2 text-xs text-gray-300">Most likely cause: {JSON.stringify(councilResult.votes?.most_likely_cause || {})}</div>
                        <div className="text-xs text-gray-300">Best fix: {JSON.stringify(councilResult.votes?.best_fix || {})}</div>
                      </Panel>
                    </>
                  ) : (
                    <div className="text-sm text-gray-400">Ask a question to start council.</div>
                  )}
                </Panel>
                <Panel className="space-y-2">
                  <div className="text-sm font-medium">Incident Search</div>
                  <input className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm" onChange={async (e) => {
                    const res = await authFetch('/api/incidents/search?keyword=' + encodeURIComponent(e.target.value));
                    if (res.ok) setTimeline(await res.json());
                  }} />
                  <div className="text-xs text-gray-300 max-h-64 overflow-y-auto space-y-1">
                    {timeline.map((t, idx) => (
                      <div key={idx} className="border border-slate-700 rounded px-2 py-1">
                        <div className="flex justify-between text-[11px] text-gray-500">
                          <span>{new Date((t.ts || 0) * 1000).toLocaleTimeString()}</span>
                          <span className="uppercase">{t.type}</span>
                        </div>
                        <div className="text-sm text-gray-200">{formatValue(t.message)}</div>
                      </div>
                    ))}
                  </div>
                </Panel>
              </div>
            </Card>
          )}
        </main>
      </div>
      {isPaletteOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-start justify-center pt-24 z-50" onClick={() => setIsPaletteOpen(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-3xl p-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center space-x-2 mb-3">
              <span className="text-lg">⌘</span>
              <input
                autoFocus
                className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div className="space-y-1 max-h-80 overflow-y-auto">
              {paletteActions.map((item) => (
                <button
                  key={item.label}
                  className="w-full text-left px-3 py-2 rounded hover:bg-slate-800 border border-transparent hover:border-slate-700"
                  onClick={() => { setIsPaletteOpen(false); item.action(); }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
      <Modal open={loginOpen} onClose={() => setLoginOpen(false)} title="Sign in">
        <div className="space-y-3">
          <div className="text-xs text-gray-400">Use your FlightCtrl credentials.</div>
          <div>
            <div className="text-xs text-gray-400 mb-1">Username</div>
            <input
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm"
              value={loginUsername}
              onChange={(e) => setLoginUsername(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleLogin(); }}
            />
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-1">Password</div>
            <input
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm"
              type="password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleLogin(); }}
            />
          </div>
          {loginError && <div className="text-xs text-red-400">{loginError}</div>}
          <div className="flex justify-end space-x-2">
            <Button variant="ghost" onClick={() => setLoginOpen(false)} disabled={loginLoading}>
              Close
            </Button>
            <Button onClick={handleLogin} disabled={loginLoading}>
              {loginLoading ? 'Signing in...' : 'Sign in'}
            </Button>
          </div>
        </div>
      </Modal>
      <Drawer open={!!selectedTask} onClose={() => setSelectedTask(null)} title={selectedTask ? `Task ${selectedTask.id}` : ''}>
        {selectedTask && (
          <div className="space-y-3 text-sm text-gray-200">
            <div className="font-semibold text-base">{selectedTask.description}</div>
            <div className="flex items-center space-x-2">
              <Badge variant="info">{selectedTask.priority}</Badge>
              <Badge variant={selectedTask.status === 'completed' ? 'success' : selectedTask.status === 'failed' ? 'danger' : 'neutral'}>{selectedTask.status}</Badge>
            </div>
            <div className="text-xs text-gray-400">Agent: {selectedTask.agent_id}</div>
            <div className="text-xs text-gray-400">Created: {new Date(selectedTask.created_at * 1000).toLocaleString()}</div>
            <div>
              <div className="font-semibold mb-1">Status History</div>
              <div className="space-y-1">
                {(selectedTask.status_history || []).map((h: { status: string; ts: number; note?: string }, idx: number) => (
                  <div key={idx} className="flex items-center space-x-2 text-xs">
                    <span className="uppercase">{h.status}</span>
                    <span>{formatValue(h.note)}</span>
                    <span className="text-gray-500">{new Date(h.ts * 1000).toLocaleTimeString()}</span>
                  </div>
                ))}
                {(selectedTask.status_history || []).length === 0 && <div className="text-gray-500 text-xs">No history.</div>}
              </div>
            </div>
            <div>
              <div className="font-semibold mb-1">Task Chat</div>
              <div className="border border-slate-700 rounded p-2 h-40 overflow-y-auto space-y-1 bg-slate-900">
                {taskMessages.map((m) => (
                  <div key={m.id} className="text-xs text-gray-200">
                    <span className="text-gray-500 mr-2">{new Date(m.ts * 1000).toLocaleTimeString()}</span>
                    <span className="font-semibold">{m.role}:</span> {formatValue(m.content)}
                  </div>
                ))}
                {taskMessages.length === 0 && <div className="text-gray-500 text-xs">No messages yet.</div>}
              </div>
              <div className="mt-2 flex space-x-2">
                <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm" value={taskMessageInput} onChange={(e) => setTaskMessageInput(e.target.value)} />
                <Button onClick={sendTaskMessage}>Send</Button>
              </div>
            </div>
          </div>
        )}
      </Drawer>
      {/* Footer */}
      <footer className="px-6 py-2 bg-white dark:bg-gray-800 text-center text-xs text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-gray-700">
        &copy; {new Date().getFullYear()} FlightCtrl. All rights reserved.
      </footer>
    </div>
    </ToastProvider>
  );
}
