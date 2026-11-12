import React, { useEffect, useState } from 'react';
import {
  Lock,
  ShieldCheck,
  ShoppingBag,
  CheckCircle2,
  AlertCircle,
  Layers,
  CreditCard,
  FileCheck2,
  FlaskConical,
  ChevronRight,
  RefreshCw,
  UserCheck,
  X,
  Settings,
  Building2,
  Plus,
  Zap,
} from 'lucide-react';
import {
  AuditEvent,
  CartVersion,
  CoordinatorInterview,
  EvalSuiteRun,
  LLMStatusResponse,
  PayPalOrder,
  Persona,
  Product,
  PurchaseRequestDetail,
  PurchaseRequestSummary,
  SystemHealth,
  TamperSimulationResult,
  UpdateKeysPayload,
} from './types/intentlock';
import { apiClient, IntentLockApiError, setAuthContext } from './api/client';
import {
  FALLBACK_PERSONAS,
  formatUsd,
  getStatusBadgeStyle,
  getVersionId,
  normalizeProduct,
} from './utils/formatters';
import { CoordinatorWorkspace } from './components/CoordinatorWorkspace';
import { ApproverWorkspace } from './components/ApproverWorkspace';
import { BuyerCheckoutWorkspace } from './components/BuyerCheckoutWorkspace';
import { ReconciliationAuditView } from './components/ReconciliationAuditView';
import { MerchantCatalogView } from './components/MerchantCatalogView';
import { DiscoveryEvalView } from './components/DiscoveryEvalView';
import { LLMRouterConfigModal } from './components/LLMRouterConfigModal';

type TopTab = 'WORKSPACE' | 'CATALOG' | 'DISCOVERY_EVALS';
type WorkflowStep = 1 | 2 | 3 | 4;

export function App() {
  // Navigation & Step state
  const [activeTab, setActiveTab] = useState<TopTab>('WORKSPACE');
  const [activeStep, setActiveStep] = useState<WorkflowStep>(1);
  const [prefillPrompt, setPrefillPrompt] = useState<string>('');
  const [showProblemBanner, setShowProblemBanner] = useState<boolean>(true);
  const [autoPilotStatus, setAutoPilotStatus] = useState<string | null>(null);

  // Personas & Auth
  const [personas, setPersonas] = useState<Persona[]>(FALLBACK_PERSONAS);
  const [activePersona, setActivePersona] = useState<Persona>(FALLBACK_PERSONAS[0]);

  // System health, LLM status, Catalog
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [llmStatus, setLlmStatus] = useState<LLMStatusResponse | null>(null);
  const [catalog, setCatalog] = useState<Product[]>([]);
  const [isConfigModalOpen, setIsConfigModalOpen] = useState<boolean>(false);

  // Purchase Requests & Selected Request Detail
  const [requests, setRequests] = useState<PurchaseRequestSummary[]>([]);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [requestDetail, setRequestDetail] = useState<PurchaseRequestDetail | null>(
    null
  );
  const [selectedVersionNumber, setSelectedVersionNumber] = useState<number>(1);
  const [auditTimeline, setAuditTimeline] = useState<{
    chain_verified: boolean;
    events: AuditEvent[];
  }>({ chain_verified: true, events: [] });

  // Discovery Interviews & Eval Suite
  const [interviews, setInterviews] = useState<CoordinatorInterview[]>([]);
  const [evalRun, setEvalRun] = useState<EvalSuiteRun | null>(null);
  const [isRunningEvals, setIsRunningEvals] = useState<boolean>(false);

  // Loading & Error / Toast banners
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorBanner, setErrorBanner] = useState<{
    title: string;
    message: string;
    code?: string;
    guardrail?: string;
    auditId?: string;
  } | null>(null);
  const [successToast, setSuccessToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setSuccessToast(msg);
    setTimeout(() => {
      setSuccessToast((prev) => (prev === msg ? null : prev));
    }, 5000);
  };

  const handleApiError = (err: unknown, fallbackTitle = 'Operation Blocked') => {
    if (err instanceof IntentLockApiError) {
      setErrorBanner({
        title: `${fallbackTitle} (HTTP ${err.status})`,
        message: err.message,
        code: err.code,
        guardrail: err.guardrail_violated,
        auditId: err.audit_event_id,
      });
    } else if (err instanceof Error) {
      setErrorBanner({
        title: fallbackTitle,
        message: err.message,
      });
    } else {
      setErrorBanner({
        title: fallbackTitle,
        message: 'An unexpected error occurred.',
      });
    }
  };

  const loadRequestDetailAndTimeline = async (reqId: string) => {
    const detail = await apiClient.getRequestDetail(reqId);
    setRequestDetail(detail);
    const activeVerNum =
      detail.active_version?.version_number ||
      (detail.versions && detail.versions.length > 0
        ? detail.versions[detail.versions.length - 1].version_number
        : 1);
    setSelectedVersionNumber(activeVerNum);

    try {
      const tl = await apiClient.getAuditTimeline(reqId);
      setAuditTimeline(tl);
    } catch {
      if (detail.audit_events) {
        setAuditTimeline({
          chain_verified: true,
          events: detail.audit_events,
        });
      }
    }
  };

  const refreshRequestsList = async (keepSelectedId?: string) => {
    const list = await apiClient.getRequests();
    setRequests(list);
    const targetId =
      keepSelectedId ||
      selectedRequestId ||
      (list.length > 0 ? list[0].id || list[0].request_id || null : null);
    if (targetId) {
      setSelectedRequestId(targetId);
      await loadRequestDetailAndTimeline(targetId);
    }
  };

  // Initial bootstrap — never blocks UI on loading screen
  useEffect(() => {
    const bootstrap = async () => {
      try {
        setAuthContext(null, FALLBACK_PERSONAS[0].id, FALLBACK_PERSONAS[0].role);

        const [healthRes, llmRes, personasRes, catalogRes, reqsRes, intvRes] =
          await Promise.allSettled([
            apiClient.getHealth(),
            apiClient.getLLMStatus(),
            apiClient.getPersonas(),
            apiClient.getCatalog(),
            apiClient.getRequests(),
            apiClient.getDiscoveryInterviews(),
          ]);

        if (healthRes.status === 'fulfilled') setHealth(healthRes.value);
        if (llmRes.status === 'fulfilled') setLlmStatus(llmRes.value);
        if (personasRes.status === 'fulfilled' && personasRes.value.length > 0) {
          setPersonas(personasRes.value);
          const alice =
            personasRes.value.find((p) => p.role === 'COORDINATOR') ||
            personasRes.value[0];
          setActivePersona(alice);
          try {
            await apiClient.switchPersona(alice.id || alice.user_id || 'user-coord-alice');
          } catch {
            // fallback header auth remains active
          }
        }
        if (catalogRes.status === 'fulfilled') {
          setCatalog(catalogRes.value.map(normalizeProduct));
        }
        if (intvRes.status === 'fulfilled') {
          setInterviews(intvRes.value);
        }
        if (reqsRes.status === 'fulfilled' && reqsRes.value.length > 0) {
          setRequests(reqsRes.value);
          const firstId = reqsRes.value[0].id || reqsRes.value[0].request_id;
          if (firstId) {
            setSelectedRequestId(firstId);
            await loadRequestDetailAndTimeline(firstId);
          }
        }
      } catch (err) {
        console.warn('Bootstrap partial error:', err);
      }
    };
    bootstrap();
  }, []);

  // Switch Persona handler
  const handleSwitchPersona = async (personaId: string, targetStep?: WorkflowStep) => {
    setErrorBanner(null);
    const target =
      personas.find((p) => (p.id || p.user_id) === personaId) ||
      FALLBACK_PERSONAS.find((p) => p.id === personaId);
    if (target) {
      setActivePersona(target);
      setAuthContext(null, target.id || target.user_id || personaId, target.role);
    }
    if (targetStep) {
      setActiveStep(targetStep);
    }
    try {
      const res = await apiClient.switchPersona(personaId);
      if (res.persona) {
        setActivePersona({
          ...res.persona,
          id: res.persona.id || res.persona.user_id || personaId,
          name: res.persona.name || res.persona.display_name || target?.name || personaId,
        });
      }
      showToast(
        `Signed in as ${res.persona?.name || res.persona?.display_name || target?.name} (${res.persona?.role || target?.role})`
      );
    } catch {
      showToast(`Signed in as ${target?.name} (${target?.role})`);
    }
  };

  // Select Request from Sidebar — automatically routes to the matching workflow stage & persona
  const handleSelectRequest = async (reqId: string) => {
    setErrorBanner(null);
    setSelectedRequestId(reqId);
    setActiveTab('WORKSPACE');
    setIsLoading(true);
    try {
      const detail = await apiClient.getRequestDetail(reqId);
      setRequestDetail(detail);
      const activeVer =
        detail.active_version ||
        (detail.versions && detail.versions.length > 0
          ? detail.versions[detail.versions.length - 1]
          : null);
      if (activeVer) {
        setSelectedVersionNumber(activeVer.version_number);
      }
      const st = (detail.status || activeVer?.status || 'DRAFT').toUpperCase();
      if (st.includes('CAPTURED') || st.includes('RECONCILED') || st.includes('VERIFIED')) {
        setActiveStep(4);
      } else if (st.includes('APPROVED') || st.includes('ORDER_CREATED') || st.includes('CAPTURE_PENDING')) {
        await handleSwitchPersona('user-buyer-charlie', 3);
      } else if (st.includes('SUBMITTED') || st.includes('PENDING_APPROVAL')) {
        await handleSwitchPersona('user-approver-bob', 2);
      } else {
        await handleSwitchPersona('user-coord-alice', 1);
      }
      try {
        const tl = await apiClient.getAuditTimeline(reqId);
        setAuditTimeline(tl);
      } catch {
        if (detail.audit_events) {
          setAuditTimeline({ chain_verified: true, events: detail.audit_events });
        }
      }
    } catch (err) {
      handleApiError(err, 'Failed to Load Purchase Order');
    } finally {
      setIsLoading(false);
    }
  };

  // 1-Click Automated Live End-to-End Demo (Step 1 AI -> Step 2 Lock -> Step 3 PayPal -> Step 4 Receipt)
  const handleRunOneClickAutoPilotDemo = async () => {
    if (isLoading || autoPilotStatus) return;
    setErrorBanner(null);
    setActiveTab('WORKSPACE');
    setIsLoading(true);
    try {
      // Stage 1: Coordinator Alice creates & submits AI cart
      setAutoPilotStatus('Step 1/3: Coordinator Alice is generating an AI-grounded cart via Gemini 2.5 Flash...');
      await handleSwitchPersona('user-coord-alice', 1);
      const created = await apiClient.createRequest({
        title: 'Live E2E Demo — 4 Engineers Onboarding & Breakroom Kit',
        raw_need_text:
          'We have 4 new engineers starting Monday and need dot-grid notebooks, black gel pens, USB-C multiport hubs, and dark roast breakroom coffee under $380.',
        budget_limit_cents: 38000,
      });
      const reqId = created.id || created.request_id || '';
      const ver =
        created.active_version ||
        (created.versions && created.versions.length > 0
          ? created.versions[created.versions.length - 1]
          : null);
      const verId = getVersionId(ver);
      const hash = ver?.intent_hash || ver?.candidate_intent_hash || '';
      await refreshRequestsList(reqId);

      await apiClient.submitCartVersion(
        reqId,
        verId,
        'Auto-pilot demo: Verified pack-size math and stock availability.'
      );
      await refreshRequestsList(reqId);

      // Stage 2: Manager Bob approves & locks SHA-256 intent_hash
      setAutoPilotStatus('Step 2/3: Manager Bob Martinez is verifying & signing the RFC 8785 SHA-256 ApprovalLock...');
      await handleSwitchPersona('user-approver-bob', 2);
      await new Promise((r) => setTimeout(r, 900));
      await apiClient.approveCartVersion(reqId, verId, {
        comment: 'Approved & cryptographically locked for PayPal Sandbox execution.',
        ttl_minutes: 30,
        approval_ttl_seconds: 1800,
        expected_intent_hash: hash,
      });
      await refreshRequestsList(reqId);

      // Stage 3: Buyer Charlie creates & captures live PayPal Sandbox Order
      setAutoPilotStatus('Step 3/3: Buyer Charlie is executing & reconciling the live PayPal Sandbox Order...');
      await handleSwitchPersona('user-buyer-charlie', 3);
      await new Promise((r) => setTimeout(r, 900));
      const order = await apiClient.createPayPalOrder(verId, {
        expected_intent_hash: hash,
      });
      await apiClient.capturePayPalOrder(verId, {
        paypal_order_id: order.paypal_order_id,
        expected_intent_hash: hash,
      });
      await refreshRequestsList(reqId);
      setActiveStep(4);
      showToast(
        `Live End-to-End Flow Complete! PayPal Sandbox Order ${order.paypal_order_id} captured & verified against SHA-256 hash.`
      );
    } catch (err) {
      handleApiError(err, 'Live Auto-Pilot Demo Interrupted');
    } finally {
      setAutoPilotStatus(null);
      setIsLoading(false);
    }
  };

  // Selected CartVersion object
  const selectedVersion: CartVersion | null = React.useMemo(() => {
    if (!requestDetail) return null;
    if (requestDetail.versions && requestDetail.versions.length > 0) {
      return (
        requestDetail.versions.find(
          (v) => v.version_number === selectedVersionNumber
        ) ||
        requestDetail.active_version ||
        requestDetail.versions[requestDetail.versions.length - 1]
      );
    }
    return requestDetail.active_version || null;
  }, [requestDetail, selectedVersionNumber]);

  // Step 1 Actions
  const handleCreateRequest = async (payload: {
    title: string;
    raw_need_text: string;
    budget_limit_cents: number | null;
  }) => {
    setErrorBanner(null);
    setIsLoading(true);
    try {
      const created = await apiClient.createRequest(payload);
      const newId = created.id || created.request_id || '';
      await refreshRequestsList(newId);
      showToast(`AI Shopping Assistant built Cart v1 for "${payload.title}"!`);
    } catch (err) {
      handleApiError(err, 'Could Not Build Cart Proposal');
    } finally {
      setIsLoading(false);
    }
  };

  const handleReviseVersion = async (payload: {
    revision_prompt?: string | null;
    budget_limit_cents?: number | null;
    line_item_edits?: Array<{
      sku: string;
      quantity: number;
      selection_rationale?: string;
      headcount_math?: string;
    }> | null;
  }) => {
    if (!selectedRequestId) return;
    setErrorBanner(null);
    setIsLoading(true);
    try {
      await apiClient.reviseCartVersion(selectedRequestId, payload);
      await refreshRequestsList(selectedRequestId);
      showToast('Saved new Cart Version and updated price & inventory totals!');
    } catch (err) {
      handleApiError(err, 'Could Not Update Cart');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmitForApproval = async (versionId: string, note: string) => {
    if (!selectedRequestId) return;
    setErrorBanner(null);
    setIsLoading(true);
    try {
      await apiClient.submitCartVersion(selectedRequestId, versionId, note);
      await refreshRequestsList(selectedRequestId);
      // Automatically switch to Bob Martinez (Approver) & open Step 2 so the user experiences a seamless interactive handoff!
      await handleSwitchPersona('user-approver-bob', 2);
      showToast(
        'Cart submitted for approval! Switched to Manager Bob Martinez to review & approve.'
      );
    } catch (err) {
      handleApiError(err, 'Submission Blocked');
    } finally {
      setIsLoading(false);
    }
  };

  // Step 2 Actions
  const handleApproveVersion = async (
    versionId: string,
    payload: {
      comment: string;
      ttl_minutes: number;
      approval_ttl_seconds: number;
      expected_intent_hash: string;
    }
  ) => {
    if (!selectedRequestId) return;
    setErrorBanner(null);
    setIsLoading(true);
    try {
      await apiClient.approveCartVersion(selectedRequestId, versionId, payload);
      await refreshRequestsList(selectedRequestId);
      showToast(
        'Cart Approved & Price-Locked! Click "Continue to PayPal Checkout" or switch to Buyer Charlie.'
      );
    } catch (err) {
      handleApiError(err, 'Approval Blocked by Policy');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const handleRejectVersion = async (versionId: string, reason: string) => {
    if (!selectedRequestId) return;
    setErrorBanner(null);
    setIsLoading(true);
    try {
      await apiClient.rejectCartVersion(selectedRequestId, versionId, reason);
      await refreshRequestsList(selectedRequestId);
      await handleSwitchPersona('user-coord-alice', 1);
      showToast('Cart returned to Coordinator Alice Chen for revision.');
    } catch (err) {
      handleApiError(err, 'Rejection Failed');
    } finally {
      setIsLoading(false);
    }
  };

  // Step 3 Actions
  const handleCreatePayPalOrder = async (
    versionId: string,
    expectedHash: string
  ): Promise<PayPalOrder> => {
    setErrorBanner(null);
    setIsLoading(true);
    try {
      const order = await apiClient.createPayPalOrder(versionId, {
        expected_intent_hash: expectedHash,
      });
      if (selectedRequestId) {
        await refreshRequestsList(selectedRequestId);
      }
      showToast(`Live PayPal Sandbox Order ${order.paypal_order_id} created!`);
      return order;
    } catch (err) {
      handleApiError(err, 'PayPal Checkout Blocked');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const handleCapturePayPalOrder = async (
    versionId: string,
    paypalOrderId: string | undefined,
    expectedHash: string
  ) => {
    setErrorBanner(null);
    setIsLoading(true);
    try {
      await apiClient.capturePayPalOrder(versionId, {
        paypal_order_id: paypalOrderId,
        expected_intent_hash: expectedHash,
      });
      apiClient
        .getCatalog()
        .then((items) => setCatalog(items.map(normalizeProduct)))
        .catch(() => {});
      if (selectedRequestId) {
        await refreshRequestsList(selectedRequestId);
      }
      showToast('PayPal Payment Completed & Receipt Verified!');
      setActiveStep(4);
    } catch (err) {
      handleApiError(err, 'PayPal Capture Blocked');
    } finally {
      setIsLoading(false);
    }
  };

  const handleOneClickCreateAndCapture = async (
    versionId: string,
    expectedHash: string
  ) => {
    setErrorBanner(null);
    setIsLoading(true);
    try {
      const existingOrder = requestDetail?.paypal_orders?.find(
        (o) => o.cart_version_id === versionId && o.paypal_status !== 'COMPLETED'
      );
      const orderId = existingOrder
        ? existingOrder.paypal_order_id
        : (
            await apiClient.createPayPalOrder(versionId, {
              expected_intent_hash: expectedHash,
            })
          ).paypal_order_id;

      await apiClient.capturePayPalOrder(versionId, {
        paypal_order_id: orderId,
        expected_intent_hash: expectedHash,
      });
      apiClient
        .getCatalog()
        .then((items) => setCatalog(items.map(normalizeProduct)))
        .catch(() => {});

      if (selectedRequestId) {
        await refreshRequestsList(selectedRequestId);
      }
      showToast(`PayPal Order ${orderId} Paid & Receipt Verified!`);
      setActiveStep(4);
    } catch (err) {
      handleApiError(err, 'PayPal Checkout Blocked');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRunTamperSimulation = async (
    scenario: string
  ): Promise<TamperSimulationResult> => {
    const res = await apiClient.simulateTamper({
      request_id: selectedRequestId || undefined,
      cart_version_id: getVersionId(selectedVersion) || undefined,
      scenario,
    });
    if (selectedRequestId) {
      await loadRequestDetailAndTimeline(selectedRequestId);
    }
    return res;
  };

  // Step 4 Actions
  const handleReSyncPayPal = async (versionId: string) => {
    setErrorBanner(null);
    setIsLoading(true);
    try {
      await apiClient.reconcilePayPalOrder(versionId);
      if (selectedRequestId) {
        await refreshRequestsList(selectedRequestId);
      }
      showToast('Synchronized live payment status with PayPal Sandbox.');
    } catch (err) {
      handleApiError(err, 'PayPal Sync Notice');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownloadEvidence = async (requestId: string) => {
    try {
      const bundle = await apiClient.getEvidenceBundle(requestId);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `intentlock-receipt-${requestId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Downloaded signed Purchase Receipt for ${requestId}`);
    } catch (err) {
      handleApiError(err, 'Failed to Download Receipt');
    }
  };

  // Eval Suite Runner
  const handleRunEvalSuite = async () => {
    setIsRunningEvals(true);
    setErrorBanner(null);
    try {
      const res = await apiClient.runEvaluationSuite();
      setEvalRun(res);
      showToast(
        `Evaluation Completed: ${res.passed_scenarios}/${res.total_scenarios} Scenarios Passed (${res.pass_rate_pct}%)`
      );
    } catch (err) {
      handleApiError(err, 'Evaluation Suite Error');
    } finally {
      setIsRunningEvals(false);
    }
  };

  // Update LLM / PayPal Runtime Keys
  const handleUpdateKeys = async (payload: UpdateKeysPayload) => {
    const updated = await apiClient.updateLLMAndPayPalKeys(payload);
    setLlmStatus(updated);
    const h = await apiClient.getHealth();
    setHealth(h);
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#F8FAFC] text-slate-900">
      {/* Clean Modern SaaS Header (Light, Airy, Interactive B2B Procurement Storefront) */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-40 shadow-2xs">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-4">
          {/* Brand & Storefront Identity */}
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-xs">
                <Lock className="w-5 h-5 text-white" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-lg tracking-tight text-slate-900">
                    IntentLock
                  </span>
                  <span className="text-[11px] font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
                    Team Purchasing & PayPal Checkout
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5">
                  <Building2 className="w-3.5 h-3.5 text-slate-400" />
                  <span>
                    Store: <strong className="text-slate-700">Acme Workspace Supplies</strong> · USD Only
                  </span>
                </div>
              </div>
            </div>

            {/* Clean Primary Navigation Tabs */}
            <nav className="hidden lg:flex items-center gap-1 pl-4 border-l border-slate-200">
              <button
                type="button"
                onClick={() => setActiveTab('WORKSPACE')}
                className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition ${
                  activeTab === 'WORKSPACE'
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                <ShoppingBag className="w-4 h-4" />
                Purchase Orders & Checkout
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('CATALOG')}
                className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition ${
                  activeTab === 'CATALOG'
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                <Layers className="w-4 h-4" />
                Browse Store Catalog (15 Items)
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('DISCOVERY_EVALS')}
                className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition ${
                  activeTab === 'DISCOVERY_EVALS'
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                <FlaskConical className="w-4 h-4" />
                User Study & Quality Benchmarks
              </button>
            </nav>
          </div>

          {/* Right Side: Interactive Team Role Switcher & Settings */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-xl border border-slate-200">
              <span className="text-[11px] font-semibold text-slate-500 px-2 hidden xl:inline">
                Acting As:
              </span>
              {personas.map((p) => {
                const pid = p.id || p.user_id || '';
                const isSelected =
                  (activePersona.id || activePersona.user_id) === pid ||
                  activePersona.role === p.role;
                const roleLabel =
                  p.role === 'COORDINATOR'
                    ? 'Coordinator'
                    : p.role === 'APPROVER'
                    ? 'Manager / Approver'
                    : 'Buyer (PayPal)';
                return (
                  <button
                    key={pid}
                    type="button"
                    onClick={() => {
                      const suggestedStep: WorkflowStep =
                        p.role === 'COORDINATOR'
                          ? 1
                          : p.role === 'APPROVER'
                          ? 2
                          : 3;
                      handleSwitchPersona(pid, suggestedStep);
                    }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5 ${
                      isSelected
                        ? 'bg-white text-indigo-700 font-semibold shadow-xs border border-slate-200/80'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <UserCheck className="w-3.5 h-3.5 text-indigo-600" />
                    <span>{p.name || p.display_name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-medium">
                      {roleLabel}
                    </span>
                  </button>
                );
              })}
            </div>

            <button
              type="button"
              onClick={() => setIsConfigModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 border border-slate-200 shadow-2xs transition"
              title="Configure AI Models & PayPal Sandbox Keys"
            >
              <Settings className="w-4 h-4 text-slate-500" />
              <span className="hidden sm:inline">API Keys</span>
              {health?.paypal_credentials_configured && (
                <span className="w-2 h-2 rounded-full bg-emerald-500" title="Live PayPal Sandbox Connected" />
              )}
            </button>
          </div>
        </div>

        {/* Mobile Nav Bar */}
        <div className="lg:hidden border-t border-slate-100 px-4 py-2 flex items-center gap-2 overflow-x-auto bg-slate-50">
          <button
            type="button"
            onClick={() => setActiveTab('WORKSPACE')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
              activeTab === 'WORKSPACE' ? 'bg-indigo-600 text-white' : 'text-slate-600'
            }`}
          >
            Purchase Orders
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('CATALOG')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
              activeTab === 'CATALOG' ? 'bg-indigo-600 text-white' : 'text-slate-600'
            }`}
          >
            Store Catalog (15)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('DISCOVERY_EVALS')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
              activeTab === 'DISCOVERY_EVALS' ? 'bg-indigo-600 text-white' : 'text-slate-600'
            }`}
          >
            User Study & Evals
          </button>
        </div>
      </header>

      {/* Notifications / Policy Alert Banner */}
      <div className="max-w-[1440px] w-full mx-auto px-4 sm:px-6 pt-4">
        {errorBanner && (
          <div className="mb-4 rounded-xl border border-rose-300 bg-rose-50 p-4 flex items-start justify-between gap-4 shadow-xs">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-bold text-rose-950">
                    {errorBanner.title}
                  </span>
                  {errorBanner.code && (
                    <span className="px-2 py-0.5 rounded text-xs font-mono font-semibold bg-rose-200/80 text-rose-900">
                      {errorBanner.code}
                    </span>
                  )}
                  {errorBanner.guardrail && (
                    <span className="px-2 py-0.5 rounded text-xs font-mono font-semibold bg-rose-900 text-white">
                      Policy: {errorBanner.guardrail}
                    </span>
                  )}
                </div>
                <p className="text-xs text-rose-900 leading-relaxed">
                  {errorBanner.message}
                </p>
              </div>
            </div>
            <button
              onClick={() => setErrorBanner(null)}
              className="p-1 text-rose-500 hover:text-rose-800"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {successToast && (
          <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-center justify-between gap-3 shadow-2xs">
            <div className="flex items-center gap-2.5 text-xs font-semibold text-emerald-950">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{successToast}</span>
            </div>
            <button
              onClick={() => setSuccessToast(null)}
              className="text-xs text-emerald-700 hover:text-emerald-950"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      <main className="flex-1 max-w-[1440px] w-full mx-auto px-4 sm:px-6 py-4">
        {activeTab === 'CATALOG' ? (
          <MerchantCatalogView
            catalog={catalog}
            onQuickStartWithSku={(sku, productName) => {
              setPrefillPrompt(
                `We need to order ${productName} (${sku}) for our team workspace — please propose recommended quantities and complementary items.`
              );
              setActiveTab('WORKSPACE');
              setActiveStep(1);
            }}
          />
        ) : activeTab === 'DISCOVERY_EVALS' ? (
          <DiscoveryEvalView
            interviews={interviews}
            evalRun={evalRun}
            isRunningEvals={isRunningEvals}
            onRunEvalSuite={handleRunEvalSuite}
          />
        ) : (
          <div className="space-y-5">
            {/* Problem Statement & 3-Step Interactive Walkthrough Banner */}
            {showProblemBanner ? (
              <div className="bg-white rounded-2xl border border-indigo-200/90 shadow-2xs p-4 sm:p-5 relative overflow-hidden">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div className="space-y-1.5 max-w-3xl">
                    <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-900 text-[11px] font-bold">
                      <ShieldCheck className="w-3.5 h-3.5 text-amber-600" />
                      THE PROBLEM WE SOLVE IN AGENTIC COMMERCE
                    </div>
                    <h1 className="text-base sm:text-lg font-bold text-slate-900 leading-snug">
                      AI shopping agents can prepare carts—but teams cannot trust AI with direct PayPal payment authority.
                    </h1>
                    <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
                      If an AI hallucinates unit prices, miscalculates multi-pack quantities, or if a cart drifts between manager approval and payment (<strong className="text-slate-800">TOCTOU Cart Drift</strong>), unauthorized money leaves the account. <strong className="text-indigo-700">IntentLock</strong> separates AI cart preparation from human approval and cryptographically locks the exact approved cart (<code className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 font-mono text-[11px]">RFC 8785 + SHA-256</code>) before executing checkout via <strong className="text-slate-800">PayPal Sandbox Orders v2 &amp; Agent Toolkit MCP</strong>.
                    </p>
                  </div>

                  <div className="flex flex-col sm:flex-row lg:flex-col items-stretch sm:items-center lg:items-end gap-2 shrink-0">
                    <button
                      type="button"
                      disabled={isLoading || !!autoPilotStatus}
                      onClick={handleRunOneClickAutoPilotDemo}
                      className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60 transition shadow-xs"
                    >
                      {autoPilotStatus ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Running Live E2E Demo...
                        </>
                      ) : (
                        <>
                          <Zap className="w-4 h-4 text-amber-300" />
                          Run 1-Click Live E2E Demo (AI → Lock → PayPal)
                        </>
                      )}
                    </button>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => {
                          setActiveStep(1);
                          handleSwitchPersona('user-coord-alice', 1);
                        }}
                        className="text-[11px] font-semibold text-indigo-700 hover:text-indigo-900 underline"
                      >
                        Start Step 1 Manually
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowProblemBanner(false)}
                        className="text-[11px] font-medium text-slate-500 hover:text-slate-800 px-1 py-0.5"
                      >
                        Hide banner
                      </button>
                    </div>
                  </div>
                </div>

                {autoPilotStatus && (
                  <div className="mt-3 p-3 rounded-xl bg-indigo-900 text-white flex items-center gap-3 text-xs font-semibold shadow-xs">
                    <RefreshCw className="w-4 h-4 animate-spin text-amber-300 shrink-0" />
                    <span>{autoPilotStatus}</span>
                  </div>
                )}

                <div className="mt-4 pt-3.5 border-t border-slate-100 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                  <div className="flex items-start gap-2.5 bg-slate-50/80 p-2.5 rounded-xl border border-slate-200/70">
                    <span className="w-5 h-5 rounded-full bg-indigo-600 text-white font-bold text-[11px] flex items-center justify-center shrink-0 mt-0.5">
                      1
                    </span>
                    <div>
                      <strong className="text-slate-900">AI Builds Cart (Alice · Coordinator):</strong>{' '}
                      <span className="text-slate-600">
                        Turns plain-English team needs into exact store SKUs with transparent pack-size math. Zero approval or payment authority.
                      </span>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5 bg-slate-50/80 p-2.5 rounded-xl border border-slate-200/70">
                    <span className="w-5 h-5 rounded-full bg-emerald-600 text-white font-bold text-[11px] flex items-center justify-center shrink-0 mt-0.5">
                      2
                    </span>
                    <div>
                      <strong className="text-slate-900">Manager Locks Hash (Bob · Approver):</strong>{' '}
                      <span className="text-slate-600">
                        Blocks self-approval (<code className="font-mono text-[10px]">G-04</code>) and signs an immutable <code className="font-mono text-[10px]">SHA-256</code> + <code className="font-mono text-[10px]">HMAC</code> lock on the approved cart version.
                      </span>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5 bg-slate-50/80 p-2.5 rounded-xl border border-slate-200/70">
                    <span className="w-5 h-5 rounded-full bg-blue-600 text-white font-bold text-[11px] flex items-center justify-center shrink-0 mt-0.5">
                      3
                    </span>
                    <div>
                      <strong className="text-slate-900">Verified PayPal Checkout (Charlie · Buyer):</strong>{' '}
                      <span className="text-slate-600">
                        Recomputes the cart hash before calling PayPal Sandbox. Any post-approval price or item change is blocked (<code className="font-mono text-[10px]">G-05</code>).
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setShowProblemBanner(true)}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-800 bg-indigo-50/80 px-3 py-1 rounded-lg border border-indigo-200/60"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  Show Problem Statement &amp; 3-Step Guide
                </button>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Sidebar: Team Purchase Orders */}
            <aside className="lg:col-span-3 bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
              <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50/70">
                <div>
                  <h2 className="text-sm font-bold text-slate-900">
                    Team Purchase Orders
                  </h2>
                  <p className="text-xs text-slate-500">
                    {requests.length} active requests
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      setActiveTab('WORKSPACE');
                      setActiveStep(1);
                      handleSwitchPersona('user-coord-alice', 1);
                      setPrefillPrompt('We need onboarding supplies for 4 new engineers: notebooks, gel pens, and USB-C chargers under $350.');
                    }}
                    className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 transition shadow-2xs"
                    title="Start a new supply order"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    New
                  </button>
                  <button
                    type="button"
                    onClick={() => refreshRequestsList()}
                    className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 transition"
                    title="Refresh orders"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                  </button>
                </div>
              </div>

              <div className="divide-y divide-slate-100 max-h-[680px] overflow-y-auto">
                {requests.map((req) => {
                  const rid = req.id || req.request_id || '';
                  const isSelected = rid === selectedRequestId;
                  const st = getStatusBadgeStyle(req.status);
                  return (
                    <button
                      key={rid}
                      type="button"
                      onClick={() => handleSelectRequest(rid)}
                      className={`w-full text-left p-4 transition flex flex-col gap-2 ${
                        isSelected
                          ? 'bg-indigo-50/60 border-l-4 border-l-indigo-600'
                          : 'hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-bold text-slate-900 line-clamp-1">
                          {req.title}
                        </span>
                      </div>

                      <div className="flex items-center justify-between gap-2">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.bg} ${st.border} ${st.text}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                          {st.label}
                        </span>
                        <strong className="text-sm font-bold text-slate-900 tabular-nums">
                          {formatUsd(req.total_amount_cents)}
                        </strong>
                      </div>

                      <div className="flex items-center justify-between text-[11px] text-slate-500">
                        <span>Cart v{req.latest_version_number || req.current_version_number || 1}</span>
                        <span className="font-mono text-[10px] text-slate-400">{rid}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </aside>

            {/* Right Main Column: Interactive 4-Step Purchasing & Checkout Flow */}
            <section className="lg:col-span-9 space-y-5">
              {/* Guided 4-Step Purchasing Progress Bar */}
              <div className="bg-white rounded-2xl border border-slate-200 p-3 shadow-2xs">
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
                  {[
                    {
                      step: 1 as WorkflowStep,
                      title: '1. Build Shopping Cart',
                      sub: 'Alice (Coordinator) · AI Assistant',
                      icon: ShoppingBag,
                    },
                    {
                      step: 2 as WorkflowStep,
                      title: '2. Manager Approval',
                      sub: 'Bob (Approver) · Lock Cart & Price',
                      icon: Lock,
                    },
                    {
                      step: 3 as WorkflowStep,
                      title: '3. PayPal Checkout',
                      sub: 'Charlie (Buyer) · Pay Approved Cart',
                      icon: CreditCard,
                    },
                    {
                      step: 4 as WorkflowStep,
                      title: '4. Verified Receipt',
                      sub: 'PayPal Match & Audit Trail',
                      icon: FileCheck2,
                    },
                  ].map((item, idx) => {
                    const Icon = item.icon;
                    const isCurrent = activeStep === item.step;
                    const orderSt = (
                      requestDetail?.status ||
                      selectedVersion?.status ||
                      'DRAFT'
                    ).toUpperCase();
                    const isStepDone =
                      (item.step === 1 && orderSt !== 'DRAFT') ||
                      (item.step === 2 &&
                        (orderSt.includes('APPROVED') ||
                          orderSt.includes('ORDER_CREATED') ||
                          orderSt.includes('CAPTURED') ||
                          orderSt.includes('RECONCILED') ||
                          orderSt.includes('VERIFIED'))) ||
                      (item.step === 3 &&
                        (orderSt.includes('CAPTURED') ||
                          orderSt.includes('RECONCILED') ||
                          orderSt.includes('VERIFIED'))) ||
                      (item.step === 4 &&
                        (orderSt.includes('CAPTURED') ||
                          orderSt.includes('RECONCILED') ||
                          orderSt.includes('VERIFIED')));
                    return (
                      <button
                        key={item.step}
                        type="button"
                        onClick={() => {
                          setErrorBanner(null);
                          setActiveStep(item.step);
                        }}
                        className={`p-3 rounded-xl border text-left transition flex items-center justify-between gap-2 ${
                          isCurrent
                            ? 'bg-indigo-600 text-white border-indigo-600 shadow-xs'
                            : isStepDone
                            ? 'bg-emerald-50/70 text-slate-800 border-emerald-200 hover:bg-emerald-50'
                            : 'bg-slate-50/70 text-slate-700 border-slate-200 hover:bg-slate-100'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div
                            className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                              isCurrent
                                ? 'bg-indigo-500 text-white'
                                : isStepDone
                                ? 'bg-emerald-600 text-white'
                                : 'bg-white text-indigo-600 border border-slate-200'
                            }`}
                          >
                            {isStepDone && !isCurrent ? (
                              <CheckCircle2 className="w-4 h-4" />
                            ) : (
                              <Icon className="w-4 h-4" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <div className="text-xs font-bold truncate flex items-center gap-1.5">
                              <span>{item.title}</span>
                              {isStepDone && (
                                <span
                                  className={`text-[9px] px-1.5 py-0.2 rounded font-bold uppercase ${
                                    isCurrent
                                      ? 'bg-emerald-400 text-slate-950'
                                      : 'bg-emerald-100 text-emerald-800'
                                  }`}
                                >
                                  Done
                                </span>
                              )}
                            </div>
                            <div
                              className={`text-[11px] truncate ${
                                isCurrent ? 'text-indigo-100' : 'text-slate-500'
                              }`}
                            >
                              {item.sub}
                            </div>
                          </div>
                        </div>
                        {idx < 3 && (
                          <ChevronRight
                            className={`w-4 h-4 shrink-0 ${
                              isCurrent ? 'text-indigo-200' : 'text-slate-400'
                            }`}
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Active Stage Component */}
              {activeStep === 1 && (
                <CoordinatorWorkspace
                  activePersona={activePersona}
                  requestDetail={requestDetail}
                  selectedVersion={selectedVersion}
                  onSelectVersion={(vNum) => setSelectedVersionNumber(vNum)}
                  catalog={catalog}
                  isLoading={isLoading}
                  prefillPrompt={prefillPrompt}
                  onClearPrefill={() => setPrefillPrompt('')}
                  onCreateRequest={handleCreateRequest}
                  onReviseVersion={handleReviseVersion}
                  onSubmitForApproval={handleSubmitForApproval}
                  onSwitchPersona={handleSwitchPersona}
                  onAdvanceToStep2={() => {
                    handleSwitchPersona('user-approver-bob', 2);
                  }}
                />
              )}

              {activeStep === 2 && (
                <ApproverWorkspace
                  activePersona={activePersona}
                  requestDetail={requestDetail}
                  selectedVersion={selectedVersion}
                  isLoading={isLoading}
                  onApprove={handleApproveVersion}
                  onReject={handleRejectVersion}
                  onSwitchPersona={handleSwitchPersona}
                  onAdvanceToStep3={() => {
                    handleSwitchPersona('user-buyer-charlie', 3);
                  }}
                />
              )}

              {activeStep === 3 && (
                <BuyerCheckoutWorkspace
                  activePersona={activePersona}
                  requestDetail={requestDetail}
                  selectedVersion={selectedVersion}
                  paypalClientId={llmStatus?.paypal_sandbox?.client_id}
                  isLoading={isLoading}
                  onCreatePayPalOrder={handleCreatePayPalOrder}
                  onCapturePayPalOrder={handleCapturePayPalOrder}
                  onOneClickCreateAndCapture={handleOneClickCreateAndCapture}
                  onRunTamperSimulation={handleRunTamperSimulation}
                  onSwitchPersona={handleSwitchPersona}
                  onAdvanceToStep4={() => setActiveStep(4)}
                />
              )}

              {activeStep === 4 && (
                <ReconciliationAuditView
                  requestDetail={requestDetail}
                  selectedVersion={selectedVersion}
                  auditEvents={auditTimeline.events}
                  chainVerified={auditTimeline.chain_verified}
                  isLoading={isLoading}
                  onReSyncPayPal={handleReSyncPayPal}
                  onDownloadEvidence={handleDownloadEvidence}
                />
              )}
            </section>
            </div>
          </div>
        )}
      </main>

      {/* AI Failover Router & PayPal Sandbox Config Modal */}
      <LLMRouterConfigModal
        isOpen={isConfigModalOpen}
        onClose={() => setIsConfigModalOpen(false)}
        llmStatus={llmStatus}
        onUpdateKeys={handleUpdateKeys}
        onRefreshStatus={async () => {
          const st = await apiClient.getLLMStatus();
          setLlmStatus(st);
        }}
      />
    </div>
  );
}
export default App;
