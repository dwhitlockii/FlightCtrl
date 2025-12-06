import { create } from 'zustand';

export type Agent = {
  agent_id: string;
  role: string;
  status: string;
  task: string | null;
  last_ollama_response: string | null;
  learning_state: Record<string, unknown>;
  mood?: string;
  last_notes?: { summary?: string; usage?: string }[];
};

export type Task = {
  id: string;
  agent_id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  priority: 'low' | 'normal' | 'high' | 'critical';
  status_history?: { status: string; ts: number; note?: string }[];
  created_at: number;
  updated_at: number;
};

export type AgentStore = {
  agents: Agent[];
  agentsLoading: boolean;
  agentsError: string | null;
  fetchAgents: () => Promise<void>;
  // Task state
  tasks: Task[];
  tasksLoading: boolean;
  tasksError: string | null;
  fetchTasks: () => Promise<void>;
  createTask: (description: string, agentId: string, priority?: Task['priority']) => Promise<void>;
};

export const useAgentStore = create<AgentStore>((set) => ({
  agents: [],
  agentsLoading: false,
  agentsError: null,
  fetchAgents: async () => {
    set({ agentsLoading: true, agentsError: null });
    try {
      const res = await fetch('/api/agents');
      if (!res.ok) throw new Error(`Failed to fetch agents: ${res.status}`);
      const data = await res.json();
      set({ agents: Object.values(data) as Agent[] });
    } catch (err) {
      if (err instanceof Error) {
        set({ agentsError: err.message });
      } else {
        set({ agentsError: 'Unknown error' });
      }
    } finally {
      set({ agentsLoading: false });
    }
  },
  // Task state and actions
  tasks: [],
  tasksLoading: false,
  tasksError: null,
  fetchTasks: async () => {
    set({ tasksLoading: true, tasksError: null });
    try {
      const res = await fetch('/api/tasks');
      if (!res.ok) throw new Error(`Failed to fetch tasks: ${res.status}`);
      const data = await res.json();
      set({ tasks: data as Task[] });
    } catch (err) {
      if (err instanceof Error) {
        set({ tasksError: err.message });
      } else {
        set({ tasksError: 'Unknown error' });
      }
    } finally {
      set({ tasksLoading: false });
    }
  },
  createTask: async (description: string, agentId: string, priority: Task['priority'] = 'normal') => {
    set({ tasksLoading: true, tasksError: null });
    try {
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description, agent_id: agentId, priority }),
      });
      if (!res.ok) throw new Error(`Failed to create task: ${res.status}`);
      await res.json();
      // Refresh tasks
      const listRes = await fetch('/api/tasks');
      if (listRes.ok) {
        const data = await listRes.json();
        set({ tasks: data as Task[] });
      }
    } catch (err) {
      if (err instanceof Error) {
        set({ tasksError: err.message });
      } else {
        set({ tasksError: 'Unknown error' });
      }
    } finally {
      set({ tasksLoading: false });
    }
  },
})); 
