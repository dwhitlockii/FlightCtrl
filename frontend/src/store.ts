import { create } from 'zustand';

export type Agent = {
  agent_id: string;
  role: string;
  status: string;
  task: string | null;
  last_ollama_response: string | null;
  learning_state: Record<string, unknown>;
};

export type Task = {
  id: string;
  agent_id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
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
      // Placeholder: Replace with real API call when backend supports tasks
      // const res = await fetch('/api/tasks');
      // if (!res.ok) throw new Error(`Failed to fetch tasks: ${res.status}`);
      // const data = await res.json();
      // set({ tasks: data as Task[] });
      set({ tasks: [] }); // No tasks yet
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