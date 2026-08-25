export type Lang = 'en' | 'vi';
export type Loc = { en: string; vi: string };

export type Snippet = { file: string; start: number; end: number; code: string; caption: Loc };
export type Quote = { file: string; start: number; end: number; anchor: string; note: Loc };

export type FlowNode = { id: string; kind: 'port' | 'step' | 'gate' | 'exit'; label: Loc };
export type FlowEdge = { id: string; from: string; to: string; label: Loc };
export type Flow = { id: string; title: Loc; nodes: FlowNode[]; edges: FlowEdge[] };

export type FunctionRef = {
  id: string;
  name: string;
  signature: string;
  file: string;
  line: number;
  note: Loc;
};

export type Why = { id: string; title: Loc; body: Loc; source: Quote; principles: string[] };

export type Detail = {
  component: string;
  functions: FunctionRef[];
  flows: Flow[];
  snippets: Snippet[];
  quotes: Quote[];
  why: Why[];
};

export type Component = {
  id: string;
  group: string;
  tier: 'A' | 'B';
  title: Loc;
  summary: Loc;
  modules: string[];
  tickets: string[];
  detail?: string;
};

export type Ticket = {
  id: string;
  phase: string;
  phaseTitle: Loc;
  status: 'done' | 'open';
  title: Loc;
  creates: string[];
  modifies: string[];
  traverses: string[];
};

export type Contract = {
  transport: Loc;
  method: string | null;
  path: string | null;
  auth: Loc;
  request: Loc;
  response: Loc;
  errors: { code: string; meaning: Loc }[];
  source: Quote;
};

export type SystemNode = {
  id: string;
  kind: 'core' | 'external' | 'store' | 'planned';
  label: Loc;
  note: Loc;
  column: number;
};

export type SystemEdge = {
  id: string;
  from: string;
  to: string;
  label: Loc;
  contract: Contract;
  principles: string[];
};

export type Store = {
  id: string;
  label: Loc;
  kind: Loc;
  lifetime: Loc;
  owner: string;
  writers: string[];
  readers: string[];
  enforcement: Quote;
};

export type Principle = { id: string; title: Loc; body: Loc; source: Quote };

export type DebtItem = {
  id: string;
  title: Loc;
  body: Loc;
  severity: 'unbuilt' | 'unvalidated' | 'temporary';
  components: string[];
  source: Quote;
};

export type MachineNode = FlowNode & { component?: string; column: number };
export type Machine = { id: string; title: Loc; nodes: MachineNode[]; edges: FlowEdge[] };
