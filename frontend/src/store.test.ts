import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAgentStore } from './store'

describe('useAgentStore', () => {
  beforeEach(() => {
    useAgentStore.setState({
      agents: [],
      agentsLoading: false,
      agentsError: null,
      tasks: [],
      tasksLoading: false,
      tasksError: null,
    })
  })

  it('initializes with empty agents and tasks', () => {
    const state = useAgentStore.getState()
    expect(state.agents).toEqual([])
    expect(state.tasks).toEqual([])
  })

  it('handles fetchAgents failure', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    await useAgentStore.getState().fetchAgents()
    expect(useAgentStore.getState().agentsError).toContain('Failed to fetch agents')
  })
})
