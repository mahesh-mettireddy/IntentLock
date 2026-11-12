import {
  AuditEvent,
  CartVersion,
  CoordinatorInterview,
  EvalSuiteRun,
  FailoverDrillResponse,
  LLMStatusResponse,
  PayPalOrder,
  Persona,
  Product,
  PurchaseRequestDetail,
  PurchaseRequestSummary,
  ReconciliationRecord,
  StructuredApiError,
  SwitchPersonaResponse,
  SystemHealth,
  TamperSimulationResult,
  UpdateKeysPayload,
} from '../types/intentlock';

const API_BASE = '/api/v1';

let activeAccessToken: string | null = null;
let activePersonaId = 'user-coord-alice';
let activePersonaRole = 'COORDINATOR';

export function setAuthContext(token: string | null, personaId: string, role: string) {
  activeAccessToken = token;
  activePersonaId = personaId;
  activePersonaRole = role;
}

export function getAuthContext() {
  return {
    token: activeAccessToken,
    personaId: activePersonaId,
    role: activePersonaRole,
  };
}

export class IntentLockApiError extends Error {
  status: number;
  code: string;
  guardrail_violated?: string;
  audit_event_id?: string;
  details?: Record<string, unknown>;

  constructor(err: StructuredApiError) {
    super(err.message);
    this.name = 'IntentLockApiError';
    this.status = err.status;
    this.code = err.code;
    this.guardrail_violated = err.guardrail_violated;
    this.audit_event_id = err.audit_event_id;
    this.details = err.details;
  }
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Persona-Id': activePersonaId,
    'X-Actor-ID': activePersonaId,
    'X-Actor-Role': activePersonaRole,
    ...(options.headers as Record<string, string> || {}),
  };

  if (activeAccessToken) {
    headers['Authorization'] = `Bearer ${activeAccessToken}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 25000);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    let body: Record<string, unknown> = {};
    try {
      body = await response.json();
    } catch {
      body = { message: response.statusText };
    }

    // Handle structured error envelope: { error: { code, message, guardrail_violated, audit_event_id, details } }
    // or FastAPI detail: { detail: { ... } } or { detail: "string" }
    const errObj =
      (body.error as Record<string, unknown>) ||
      (typeof body.detail === 'object' && body.detail !== null
        ? (body.detail as Record<string, unknown>)
        : null);

    const code =
      (errObj?.code as string) ||
      (errObj?.error_code as string) ||
      (body.code as string) ||
      `HTTP_${response.status}`;

    const message =
      (errObj?.message as string) ||
      (typeof body.detail === 'string' ? body.detail : null) ||
      (body.message as string) ||
      `Request failed with status ${response.status}`;

    const guardrail_violated =
      (errObj?.guardrail_violated as string) ||
      (errObj?.guardrail_triggered as string) ||
      (errObj?.guardrail as string) ||
      (body.guardrail_violated as string);

    const audit_event_id =
      (errObj?.audit_event_id as string) ||
      (errObj?.audit_event_uid as string) ||
      (body.audit_event_id as string);

    const details =
      (errObj?.details as Record<string, unknown>) ||
      (errObj as Record<string, unknown>);

    throw new IntentLockApiError({
      status: response.status,
      code,
      message,
      guardrail_violated,
      audit_event_id,
      details,
    });
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  // 1. Health & LLM Status
  getHealth: () => apiRequest<SystemHealth>('/health'),

  getLLMStatus: () => apiRequest<LLMStatusResponse>('/llm/status'),

  updateLLMAndPayPalKeys: (payload: UpdateKeysPayload) =>
    apiRequest<LLMStatusResponse>('/llm/keys', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  runFailoverDrill: (prompt?: string) =>
    apiRequest<FailoverDrillResponse>('/llm/test-failover', {
      method: 'POST',
      body: JSON.stringify({
        prompt:
          prompt ||
          'We have 4 new backend engineers starting Monday; need onboarding cables, notebooks, pens, and desk mats under $350.',
        simulate_fail_providers: ['google_gemini'],
      }),
    }),

  getMcpTools: () =>
    apiRequest<{ tools: Array<Record<string, any>>; count?: number }>('/mcp/tools'),

  invokeMcpTool: (tool_name: string, arguments_payload: Record<string, any>) =>
    apiRequest<Record<string, any>>('/mcp/invoke', {
      method: 'POST',
      body: JSON.stringify({
        tool_name,
        arguments: arguments_payload,
      }),
    }),

  // 2. Personas & RBAC Switcher
  getPersonas: async (): Promise<Persona[]> => {
    const res = await apiRequest<Persona[] | { personas: Persona[] }>('/auth/personas');
    return Array.isArray(res) ? res : res.personas || [];
  },

  switchPersona: async (personaId: string): Promise<SwitchPersonaResponse> => {
    const res = await apiRequest<SwitchPersonaResponse>('/auth/switch', {
      method: 'POST',
      body: JSON.stringify({ persona_id: personaId }),
    });
    if (res.access_token && res.persona) {
      setAuthContext(
        res.access_token,
        res.persona.id || res.persona.user_id || personaId,
        res.persona.role
      );
    }
    return res;
  },

  // 3. Synthetic Merchant Catalog (15 SKUs)
  getCatalog: async (): Promise<Product[]> => {
    const res = await apiRequest<Product[] | { items: Product[]; products?: Product[] }>('/catalog');
    if (Array.isArray(res)) return res;
    return res.items || res.products || [];
  },

  // 4. Purchase Requests & Cart Versions
  getRequests: async (): Promise<PurchaseRequestSummary[]> => {
    const res = await apiRequest<PurchaseRequestSummary[] | { requests: PurchaseRequestSummary[] }>('/requests');
    if (Array.isArray(res)) return res;
    return res.requests || [];
  },

  getRequestDetail: (requestId: string) =>
    apiRequest<PurchaseRequestDetail>(`/requests/${requestId}`),

  createRequest: (payload: {
    title: string;
    raw_need_text: string;
    natural_language_need?: string;
    budget_limit_cents?: number | null;
    budget_ceiling_cents?: number | null;
  }) =>
    apiRequest<PurchaseRequestDetail>('/requests', {
      method: 'POST',
      body: JSON.stringify({
        title: payload.title,
        raw_need_text: payload.raw_need_text,
        natural_language_need: payload.natural_language_need || payload.raw_need_text,
        budget_limit_cents: payload.budget_limit_cents,
        budget_ceiling_cents: payload.budget_ceiling_cents ?? payload.budget_limit_cents,
      }),
    }),

  reviseCartVersion: (
    requestId: string,
    payload: {
      revision_prompt?: string | null;
      revision_instruction?: string | null;
      budget_limit_cents?: number | null;
      line_item_edits?: Array<{
        sku: string;
        quantity: number;
        selection_rationale?: string;
        headcount_math?: string;
      }> | null;
    }
  ) =>
    apiRequest<PurchaseRequestDetail | CartVersion>(`/requests/${requestId}/versions`, {
      method: 'POST',
      body: JSON.stringify({
        revision_prompt: payload.revision_prompt ?? payload.revision_instruction ?? null,
        revision_instruction: payload.revision_instruction ?? payload.revision_prompt ?? null,
        budget_limit_cents: payload.budget_limit_cents,
        updated_budget_ceiling_cents: payload.budget_limit_cents,
        line_item_edits: payload.line_item_edits ?? null,
        explicit_items: payload.line_item_edits
          ? payload.line_item_edits.map((item) => ({
              sku: item.sku,
              quantity: item.quantity,
              item_rationale: item.selection_rationale,
            }))
          : null,
      }),
    }),

  submitCartVersion: (
    requestId: string,
    versionId: string,
    note = 'Submitted for managerial review and cryptographic intent lock.'
  ) =>
    apiRequest<PurchaseRequestDetail | CartVersion>(
      `/requests/${requestId}/versions/${versionId}/submit`,
      {
        method: 'POST',
        body: JSON.stringify({ submission_note: note, comment: note }),
      }
    ),

  approveCartVersion: (
    requestId: string,
    versionId: string,
    payload: {
      comment: string;
      ttl_minutes: number;
      approval_ttl_seconds?: number;
      expected_intent_hash?: string;
    }
  ) =>
    apiRequest<PurchaseRequestDetail | CartVersion>(
      `/requests/${requestId}/versions/${versionId}/approve`,
      {
        method: 'POST',
        body: JSON.stringify({
          comment: payload.comment,
          approval_note: payload.comment,
          ttl_minutes: payload.ttl_minutes,
          approval_ttl_seconds: payload.approval_ttl_seconds ?? payload.ttl_minutes * 60,
          expected_intent_hash: payload.expected_intent_hash,
        }),
      }
    ),

  rejectCartVersion: (requestId: string, versionId: string, reason: string) =>
    apiRequest<PurchaseRequestDetail | CartVersion>(
      `/requests/${requestId}/versions/${versionId}/reject`,
      {
        method: 'POST',
        body: JSON.stringify({
          comment: reason,
          rejection_reason: reason,
        }),
      }
    ),

  // 5. PayPal Sandbox Checkout & Reconciliation
  createPayPalOrder: (
    versionId: string,
    payload: {
      expected_intent_hash?: string;
      execution_mode?: string;
      idempotency_key?: string;
    } = {}
  ) =>
    apiRequest<PayPalOrder & { request_detail?: PurchaseRequestDetail }>(
      `/checkout/${versionId}/create-paypal-order`,
      {
        method: 'POST',
        body: JSON.stringify({
          expected_intent_hash: payload.expected_intent_hash,
          execution_mode: payload.execution_mode || 'PAYPAL_MCP_SANDBOX',
          idempotency_key: payload.idempotency_key || `ilock-create-${versionId}`,
          idempotency_hint: payload.idempotency_key || `ilock-create-${versionId}`,
        }),
      }
    ),

  capturePayPalOrder: (
    versionId: string,
    payload: {
      paypal_order_id?: string;
      expected_intent_hash?: string;
      payer_id?: string;
    } = {}
  ) =>
    apiRequest<{
      paypal_order?: PayPalOrder;
      reconciliation?: ReconciliationRecord;
      payment_state?: string;
      paypal_order_id?: string;
      paypal_capture_id?: string;
      evidence_bundle_id?: string;
    }>(`/checkout/${versionId}/capture-paypal-order`, {
      method: 'POST',
      body: JSON.stringify({
        paypal_order_id: payload.paypal_order_id,
        expected_intent_hash: payload.expected_intent_hash,
        payer_id: payload.payer_id || 'SANDBOX-BUYER-001',
      }),
    }),

  reconcilePayPalOrder: (versionId: string) =>
    apiRequest<ReconciliationRecord>(`/checkout/${versionId}/reconcile`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  // 6. Evidence Bundle & Audit Timeline
  getEvidenceBundle: (requestId: string) =>
    apiRequest<Record<string, unknown>>(`/requests/${requestId}/evidence`),

  getAuditTimeline: async (requestId: string): Promise<{
    chain_verified: boolean;
    events: AuditEvent[];
  }> => {
    const res = await apiRequest<
      AuditEvent[] | { chain_verified?: boolean; events?: AuditEvent[]; audit_events?: AuditEvent[] }
    >(`/requests/${requestId}/timeline`);
    if (Array.isArray(res)) {
      return { chain_verified: true, events: res };
    }
    return {
      chain_verified: res.chain_verified ?? true,
      events: res.events || res.audit_events || [],
    };
  },

  // 7. Interactive Security & Drift Tamper Simulator
  simulateTamper: (payload: {
    request_id?: string;
    cart_version_id?: string;
    scenario: string;
  }) =>
    apiRequest<TamperSimulationResult>('/security/simulate-tamper', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // 8. Discovery Study & Automated Evaluation Suite
  getDiscoveryInterviews: async (): Promise<CoordinatorInterview[]> => {
    const res = await apiRequest<
      CoordinatorInterview[] | { interviews: CoordinatorInterview[] }
    >('/discovery/interviews');
    if (Array.isArray(res)) return res;
    return res.interviews || [];
  },

  runEvaluationSuite: () =>
    apiRequest<EvalSuiteRun>('/evals/run', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
};
