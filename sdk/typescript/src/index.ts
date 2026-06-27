/**
 * AI Team Hub — TypeScript SDK
 *
 * Usage:
 *   import { Client } from 'ai-team-hub';
 *   const client = new Client({ apiKey: 'cfut_...' });
 *   const result = await client.run('Analyze market trends');
 *   console.log(result.result);
 */

export interface TaskResponse {
  task_id: string;
  status: string;
  result: string;
  trace_id: string;
  cost: string;
  latency: string;
  message: string;
}

export interface WorkspaceResponse {
  workspace_id: string;
  status: string;
  title: string;
  created_at: string;
  message: string;
}

export interface TraceStep {
  step: string;
  agent: string;
  latency_ms: number;
  timestamp: string;
}

export interface TraceResponse {
  trace_id: string;
  task_id: string;
  status: string;
  steps: TraceStep[];
  fsm_transitions: Array<{ from: string; to: string }>;
  agent_calls: Array<{ agent: string; input_preview: string; output_preview: string; latency_ms: number }>;
  cache_hits: number;
  total_cost: string;
 string;
  message: string;
}

export interface ChatResponse {
  session_id: string;
  status: string;
  response: string;
  agent_used: string;
  latency: string;
  message: string;
}

export interface ClientOptions {
  apiKey: string;
  baseUrl?: string;
  timeout?: number;
}

export class Client {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;

  constructor(options: ClientOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl || 'https://ai-team-hub.wt5371.workers.dev').replace(/\/$/, '');
    this.timeout = options.timeout || 120000;
  }

  /**
   * Execute a task through the AI Runtime.
   */
  async run(
    task: string,
    options?: {
      mode?: 'auto' | 'control' | 'debug';
      provider?: string;
      model?: string;
      budget?: number;
      timeout?: number;
      agent_config?: Record<string, unknown>;
      workspace_id?: string;
    }
  ): Promise<TaskResponse> {
    return this._post('/v1/task/run', {
      task,
      mode: options?.mode || 'auto',
      provider: options?.provider || 'openrouter',
      model: options?.model || 'openrouter/owl-alpha',
      budget: options?.budget ?? 0.5,
      timeout: options?.timeout ?? 120,
      agent_config: options?.agent_config,
      workspace_id: options?.workspace_id,
    });
  }

  /**
   * Create a new workspace.
   */
  async createWorkspace(title: string, description?: string): Promise<WorkspaceResponse> {
    return this._post('/v1/workspace/create', {
      title,
      description: description || '',
    });
  }

  /**
   * Get task status.
   */
  async getStatus(taskId: string): Promise<TaskResponse> {
    return this._get(`/v1/task/${taskId}/status`);
  }

  /**
   * Get full execution trace.
   */
  async getTrace(taskId: string): Promise<TraceResponse> {
    return this._get(`/v1/task/${taskId}/trace`);
  }

  /**
   * Simple agent chat.
   */
  async chat(
    message: string,
    options?: {
      session_id?: string;
      mode?: string;
      context?: Record<string, unknown>;
    }
  ): Promise<ChatResponse> {
    return this._post('/v1/agent/chat', {
      message,
      mode: options?.mode || 'auto',
      session_id: options?.session_id,
      context: options?.context,
    });
  }

  /**
   * Check API health.
   */
  async health(): Promise<{ status: string; version: string; modes_available: string[] }> {
    const res = await fetch(`${this.baseUrl}/v1/health`);
    return res.json();
  }

  // ── Observability ──

  async getTimeline(taskId: string): Promise<{ events: any[]; total_duration_ms: number }> {
    return this._get(`/v1/timeline/${taskId}`);
  }

  async getAgentGraph(taskId: string): Promise<{ nodes: any[]; edges: any[] }> {
    return this._get(`/v1/agent-graph/${taskId}`);
  }

  async getCost(taskId: string): Promise<Record<string, any>> {
    return this._get(`/v1/cost/${taskId}`);
  }

  async getCacheStats(): Promise<{ hits: number; misses: number; hit_rate: number; layers: any[] }> {
    return this._get('/v1/cache/vis');
  }

  async getFsmTransitions(taskId: string): Promise<{ transitions: any[]; final_state: string }> {
    return this._get(`/v1/fsm-transitions/${taskId}`);
  }

  // ── Internal ──

  private async _post(path: string, data: any): Promise<any> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      throw new Error(`API error ${res.status}: ${await res.text()}`);
    }
    return res.json();
  }

  private async _get(path: string): Promise<any> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { 'X-API-Key': this.apiKey },
    });
    if (!res.ok) {
      throw new Error(`API error ${res.status}: ${await res.text()}`);
    }
    return res.json();
  }
}

export default Client;
