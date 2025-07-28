import { useState, useEffect } from 'react';
import 'primereact/resources/themes/lara-light-blue/theme.css';
import 'primereact/resources/primereact.min.css';
import 'primeicons/primeicons.css';
import './index.css';
import { useAgentStore } from './store';

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
};
type PluginResult = { plugin: string; result: unknown } | null;

export default function App() {
  // --- Chat State ---
  const [messages, setMessages] = useState<{role: string, content: string}[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [pluginResult, setPluginResult] = useState<PluginResult>(null);
  const agents = useAgentStore((s) => s.agents);
  const agentsLoading = useAgentStore((s) => s.agentsLoading);
  const agentsError = useAgentStore((s) => s.agentsError);
  const fetchAgents = useAgentStore((s) => s.fetchAgents);
  const tasks = useAgentStore((s) => s.tasks);
  const tasksLoading = useAgentStore((s) => s.tasksLoading);
  const tasksError = useAgentStore((s) => s.tasksError);
  const fetchTasks = useAgentStore((s) => s.fetchTasks);

  useEffect(() => {
    const fetchHealth = async () => {
      const res = await fetch("/api/health");
      setHealth(await res.json());
    };
    const fetchMetrics = async () => {
      const res = await fetch("/api/metrics");
      setMetrics(await res.json());
    };
    fetchHealth();
    fetchMetrics();
    fetchAgents();
    fetchTasks();
    const interval = setInterval(() => {
      fetchHealth();
      fetchMetrics();
      fetchAgents();
      fetchTasks();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchAgents, fetchTasks]);

  useEffect(() => {
    const socket = new WebSocket('ws://localhost:8000/ws/chat');
    setWs(socket);
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.role === 'agent') {
        setMessages((msgs) => [...msgs, { role: 'agent', content: data.response }]);
      }
    };
    return () => socket.close();
  }, []);

  const sendMessage = async () => {
    if (!input.trim()) return;
    setMessages((msgs) => [...msgs, { role: 'user', content: input }]);
    setInput('');
    setLoading(true);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ agent_id: 'agent-1', prompt: input, model: 'llama3' }));
    }
    setLoading(false);
  };

  const runPlugin = async () => {
    const res = await fetch('/api/caretaker/plugin/example_plugin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ foo: 'bar' })
    });
    setPluginResult(await res.json());
  };

  return (
    <div className="flex flex-col min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 bg-white dark:bg-gray-800 shadow">
        <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">FlightCtrl AI Agent System</div>
        <div className="flex items-center space-x-4">
          {/* Status indicators, user menu, etc. */}
          <span className="pi pi-user text-xl" />
        </div>
      </header>
      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 p-4 flex flex-col">
          <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200">Agents</div>
          {agentsLoading && <div className="text-gray-400">Loading agents...</div>}
          {agentsError && <div className="text-red-500">Error: {agentsError}</div>}
          <ul className="space-y-2">
            {agents.map((agent) => (
              <li key={agent.agent_id} className="flex items-center space-x-2">
                <span className={
                  agent.role === 'caretaker'
                    ? 'pi pi-user-edit text-purple-500'
                    : 'pi pi-robot text-blue-500'
                } />
                <span className="font-medium">{agent.agent_id}</span>
                <span className={
                  agent.status === 'running'
                    ? 'text-green-600 dark:text-green-400 ml-2'
                    : 'text-gray-500 ml-2'
                }>
                  {agent.status}
                </span>
                <span className="ml-2 text-xs text-gray-400">[{agent.role}]</span>
              </li>
            ))}
          </ul>
          {/* Task list section */}
          <div className="font-semibold mt-6 mb-2 text-gray-700 dark:text-gray-200">Tasks</div>
          {tasksLoading && <div className="text-gray-400">Loading tasks...</div>}
          {tasksError && <div className="text-red-500">Error: {tasksError}</div>}
          <ul className="space-y-2">
            {tasks.length === 0 && !tasksLoading && <li className="text-gray-400">No tasks</li>}
            {tasks.map((task) => (
              <li key={task.id} className="flex flex-col border-b border-gray-200 dark:border-gray-700 pb-2 mb-2">
                <span className="text-sm font-medium text-gray-800 dark:text-gray-100">{task.description}</span>
                <span className="text-xs text-gray-500">Agent: {task.agent_id}</span>
                <span className={
                  task.status === 'completed'
                    ? 'text-green-600 dark:text-green-400'
                    : task.status === 'in_progress'
                    ? 'text-blue-600 dark:text-blue-400'
                    : task.status === 'failed'
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-gray-500'
                }>
                  {task.status}
                </span>
              </li>
            ))}
          </ul>
          {/* Quick actions placeholder */}
          <div className="mt-6">
            <button className="w-full py-2 px-4 bg-blue-600 text-white rounded hover:bg-blue-700 transition">New Task</button>
          </div>
        </aside>
        {/* Main Panel */}
        <main className="flex-1 flex flex-col p-6 space-y-6">
          {/* Chat Window */}
          <section className="flex-1 bg-white dark:bg-gray-800 rounded shadow p-4 flex flex-col">
            <div className="font-semibold text-lg mb-2 text-gray-800 dark:text-gray-100">Agent & User Chat</div>
            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto space-y-2">
              {messages.length === 0 && (
                <div className="text-gray-600 dark:text-gray-300">[Chat messages will appear here]</div>
              )}
              {messages.map((msg, idx) => (
                <div key={idx} className={msg.role === 'user' ? 'text-blue-700 dark:text-blue-300' : 'text-green-700 dark:text-green-300'}>
                  <b>{msg.role === 'user' ? 'You' : 'Agent'}:</b> {msg.content}
                </div>
              ))}
              {loading && <div className="text-gray-400 italic">Agent is typing...</div>}
            </div>
            {/* Chat input */}
            <div className="mt-4 flex">
              <input
                className="flex-1 border rounded-l px-3 py-2 focus:outline-none"
                placeholder="Type a message..."
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') sendMessage(); }}
                disabled={loading}
              />
              <button
                className="bg-blue-600 text-white px-4 py-2 rounded-r hover:bg-blue-700 transition"
                onClick={sendMessage}
                disabled={loading || !input.trim()}
              >
                {loading ? 'Sending...' : 'Send'}
              </button>
            </div>
          </section>
          {/* Widgets & Status Panel */}
          <section className="grid grid-cols-3 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded shadow p-4">
              <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200">System Metrics</div>
              <div className="text-gray-600 dark:text-gray-300">[Live metrics widget]</div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded shadow p-4">
              <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200">Agent Health</div>
              <div className="text-gray-600 dark:text-gray-300">[Agent health widget]</div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded shadow p-4">
              <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200">Diagnostics</div>
              <div className="text-gray-600 dark:text-gray-300">[Diagnostics widget]</div>
            </div>
          </section>
          {/* Task/Status Panel */}
          <section className="bg-white dark:bg-gray-800 rounded shadow p-4">
            <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200">Agent Tasks & Status</div>
            <div className="text-gray-600 dark:text-gray-300">[Task/status panel]</div>
          </section>
          <div style={{marginTop:20}}>
            <h2>System Health</h2>
            <pre>{JSON.stringify(health, null, 2)}</pre>
            <h2>System Metrics</h2>
            <pre>{JSON.stringify(metrics, null, 2)}</pre>
          </div>
          <button onClick={runPlugin} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded">Run Example Plugin</button>
          {pluginResult && <pre>{JSON.stringify(pluginResult, null, 2)}</pre>}
        </main>
      </div>
      {/* Footer */}
      <footer className="px-6 py-2 bg-white dark:bg-gray-800 text-center text-xs text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-gray-700">
        &copy; {new Date().getFullYear()} FlightCtrl. All rights reserved.
      </footer>
    </div>
  );
}
