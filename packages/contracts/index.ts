export type State =
  | 'draft'
  | 'clarifying'
  | 'planned'
  | 'awaiting_approval'
  | 'running'
  | 'waiting_for_user'
  | 'paused'
  | 'verifying'
  | 'awaiting_feedback'
  | 'completed'
  | 'failed'
  | 'cancelled';
export interface AcceptanceCheck {
  id: string;
  label: string;
  kind: 'file_exists' | 'text_contains' | 'command' | 'manual';
  path?: string | null;
  contains?: string | null;
  argv?: string[];
  timeout?: number;
}
export interface TaskSpec {
  conversational?: boolean;
  goal: string;
  workspace: string;
  context: string;
  inputs: string[];
  deliverables: string[];
  acceptance: string[];
  plan: string[];
  tools: string[];
  mode: 'ask' | 'workspace';
  provider: string;
  collaboration: boolean;
  collaboration_mapping?: Record<string, string>;
  token_reminder?: number | null;
  hard_token_budget: number | null;
  hard_cost_budget?: number | null;
  cost_reminder?: number | null;
  checks?: AcceptanceCheck[];
  guardrails?: Record<string, number>;
}
export interface Task {
  id: string;
  session_id: string;
  state: State;
  spec: TaskSpec;
  revision?: number;
  needs_recovery?: boolean;
  verification?: {
    status: string;
    checks: { id: string; label: string; status: string }[];
    manual_acceptance: string[];
    unresolved_calls: string[];
  } | null;
}
export interface AgentEvent {
  id: number;
  task_id: string;
  type: string;
  payload: Record<string, unknown>;
  created: number;
}

export interface Session {
  id: string;
  title: string;
  project_id?: string | null;
  created: number;
}
export interface Project {
  id: string;
  name: string;
  workspace: string;
  created: number;
}
export interface ChatMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created: number;
}
export interface ProviderSummary {
  id: string;
  name: string;
  model?: string;
  profile?: { context_window?: number };
}
export interface ToolCall {
  id: string;
  task_id: string;
  tool: string;
  status: string;
  created: number;
  args: Record<string, unknown>;
  result?: { diff?: string; [key: string]: unknown } | null;
  decision?: string | null;
}
export interface Bootstrap {
  sessions: Session[];
  projects: Project[];
  tasks: Task[];
  providers: ProviderSummary[];
  tools: string[];
  desktop?: { stopped: boolean; target: string | null };
}
export interface Skill {
  name: string;
  purpose: string;
  steps: string[];
  acceptance: string[];
  tools: string[];
}
export interface PlanResponse {
  questions?: string[];
  goal?: string;
  deliverables: string[];
  acceptance: string[];
  plan: string[];
  tools: string[];
}
export interface ContextCompaction {
  before_tokens: number;
  input_tokens: number;
  checkpoint?: string;
}
