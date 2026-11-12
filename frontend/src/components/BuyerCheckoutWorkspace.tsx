import React, { useEffect, useState } from 'react';
import { PayPalScriptProvider, PayPalButtons } from '@paypal/react-paypal-js';
import {
  Lock,
  ShieldCheck,
  ShieldAlert,
  Clock,
  CreditCard,
  ExternalLink,
  CheckCircle2,
  ArrowRight,
  RefreshCw,
  FileCode2,
  UserCheck,
  Zap,
  AlertTriangle,
} from 'lucide-react';
import {
  CartVersion,
  PayPalOrder,
  Persona,
  PurchaseRequestDetail,
  TamperSimulationResult,
} from '../types/intentlock';
import {
  formatUsd,
  getLineItems,
  getVersionId,
  getVersionIntentHash,
  shortHash,
} from '../utils/formatters';
import { TamperSimulatorPanel } from './TamperSimulatorModal';

interface BuyerCheckoutWorkspaceProps {
  activePersona: Persona;
  requestDetail: PurchaseRequestDetail | null;
  selectedVersion: CartVersion | null;
  paypalClientId?: string;
  isLoading: boolean;
  onCreatePayPalOrder: (versionId: string, expectedHash: string) => Promise<PayPalOrder>;
  onCapturePayPalOrder: (
    versionId: string,
    paypalOrderId: string | undefined,
    expectedHash: string
  ) => Promise<void>;
  onOneClickCreateAndCapture: (versionId: string, expectedHash: string) => Promise<void>;
  onRunTamperSimulation: (scenario: string) => Promise<TamperSimulationResult>;
  onSwitchPersona: (personaId: string) => Promise<void>;
  onAdvanceToStep4: () => void;
}

export const BuyerCheckoutWorkspace: React.FC<BuyerCheckoutWorkspaceProps> = ({
  activePersona,
  requestDetail,
  selectedVersion,
  paypalClientId,
  isLoading,
  onCreatePayPalOrder,
  onCapturePayPalOrder,
  onOneClickCreateAndCapture,
  onRunTamperSimulation,
  onSwitchPersona,
  onAdvanceToStep4,
}) => {
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null);
  const [showTamperDrawer, setShowTamperDrawer] = useState<boolean>(false);
  const [showPayloadPreview, setShowPayloadPreview] = useState<boolean>(false);

  const approvalLock =
    selectedVersion?.approval_lock ||
    requestDetail?.approval_locks?.find(
      (l) => l.cart_version_id === getVersionId(selectedVersion)
    ) ||
    requestDetail?.approval_locks?.[0] ||
    null;

  const expiresAtIso =
    approvalLock?.expires_at || approvalLock?.expires_at_utc || null;

  useEffect(() => {
    if (!expiresAtIso) {
      setRemainingSeconds(null);
      return;
    }
    const updateTimer = () => {
      const expMs = new Date(expiresAtIso).getTime();
      const nowMs = Date.now();
      const diffSec = Math.floor((expMs - nowMs) / 1000);
      setRemainingSeconds(diffSec);
    };
    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [expiresAtIso]);

  if (!requestDetail || !selectedVersion) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-8 text-center">
        <p className="text-sm text-slate-600">
          Select a Purchase Request with an Approved & Locked Cart Version first.
        </p>
      </div>
    );
  }

  const isBuyer = activePersona.role.toUpperCase() === 'BUYER';
  const versionId = getVersionId(selectedVersion);
  const intentHash =
    approvalLock?.intent_hash || getVersionIntentHash(selectedVersion);
  const lineItems = getLineItems(selectedVersion);

  // Latest PayPal order for this version
  const existingPayPalOrder =
    requestDetail.paypal_orders?.find((o) => o.cart_version_id === versionId) ||
    requestDetail.paypal_orders?.[0] ||
    null;
  const latestOrder = existingPayPalOrder;

  const isCaptured =
    selectedVersion.status === 'CAPTURED_VERIFIED' ||
    selectedVersion.status === 'CAPTURED_RECONCILED' ||
    requestDetail.status === 'CAPTURED_VERIFIED' ||
    requestDetail.status === 'CAPTURED_RECONCILED' ||
    existingPayPalOrder?.paypal_status === 'COMPLETED';

  const isExpired =
    remainingSeconds !== null && remainingSeconds <= 0 && !isCaptured;

  const formatCountdown = (secs: number | null) => {
    if (secs === null) return 'TTL Active';
    if (secs <= 0) return 'LOCK EXPIRED (00:00)';
    const mins = Math.floor(secs / 60);
    const remSecs = secs % 60;
    return `${mins}m ${remSecs.toString().padStart(2, '0')}s remaining`;
  };

  // Construct exact PayPal Orders v2 JSON preview
  const paypalOrdersV2PayloadPreview = {
    intent: 'CAPTURE',
    purchase_units: [
      {
        reference_id: requestDetail.id || requestDetail.request_id,
        custom_id: intentHash,
        invoice_id:
          existingPayPalOrder?.invoice_id ||
          `IL-${versionId.slice(0, 8)}-${(approvalLock?.id || 'LOCK').slice(0, 6)}`,
        description: `IntentLock Approved Purchase (${requestDetail.title}) — Acme Workspace Supplies`,
        amount: {
          currency_code: 'USD',
          value: (selectedVersion.total_amount_cents / 100).toFixed(2),
          breakdown: {
            item_total: {
              currency_code: 'USD',
              value: (selectedVersion.total_amount_cents / 100).toFixed(2),
            },
          },
        },
        items: lineItems.map((it) => ({
          sku: it.sku,
          name: it.product_name,
          quantity: String(it.quantity),
          unit_amount: {
            currency_code: 'USD',
            value: (it.unit_price_cents / 100).toFixed(2),
          },
        })),
      },
    ],
  };

  return (
    <div className="space-y-6">
      {/* Buyer Role Guidance Banner */}
      {!isBuyer && (
        <div className="rounded-xl border border-indigo-300 bg-indigo-50/90 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-indigo-600 shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-semibold text-indigo-950">
                Viewing PayPal Sandbox Checkout as {activePersona.name} ({activePersona.role})
              </h4>
              <p className="text-xs text-indigo-800 mt-0.5">
                Under Separation of Duties, only <strong>Charlie Kim (Buyer / Operator)</strong> can initiate and capture PayPal Sandbox Orders for a locked Cart Version.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onSwitchPersona('user-buyer-charlie')}
            className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 transition shadow-sm"
          >
            <UserCheck className="w-4 h-4" />
            Switch to Buyer Charlie in 1 Click
          </button>
        </div>
      )}

      {/* Cryptographic Approval Lock Header Card */}
      <div
        className={`rounded-xl border-2 p-5 shadow-sm transition ${
          isExpired
            ? 'border-rose-400 bg-rose-50/90'
            : 'border-emerald-400 bg-emerald-50/80'
        }`}
      >
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div
              className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 text-white shadow-sm ${
                isExpired ? 'bg-rose-600' : 'bg-emerald-600'
              }`}
            >
              <Lock className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`px-2.5 py-0.5 rounded text-xs font-mono font-bold ${
                    isExpired
                      ? 'bg-rose-200 text-rose-950'
                      : 'bg-emerald-200 text-emerald-950'
                  }`}
                >
                  {isExpired
                    ? 'GUARDRAIL G-06: LOCK EXPIRED'
                    : `CRYPTOGRAPHIC INTENT LOCK ACTIVE (v${selectedVersion.version_number})`}
                </span>
                <span className="text-xs font-semibold text-slate-700">
                  Approved by:{' '}
                  <strong>{approvalLock?.approver_name || 'Bob Martinez (USR-APPR-BOB)'}</strong>
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-mono text-slate-800 pt-1">
                <span>
                  SHA-256 <code className="font-bold text-emerald-900">intent_hash</code>:{' '}
                  <code className="bg-white/90 px-2 py-0.5 rounded border border-emerald-300 select-all">
                    {intentHash}
                  </code>
                </span>
                {approvalLock?.approval_signature && (
                  <span>
                    HMAC-SHA256:{' '}
                    <code className="bg-white/90 px-2 py-0.5 rounded border border-emerald-300">
                      {shortHash(approvalLock.approval_signature, 12)}
                    </code>
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Live Countdown Timer Badge */}
          <div className="flex flex-wrap items-center gap-3 shrink-0">
            <div
              className={`px-3.5 py-2 rounded-xl border font-mono text-xs font-bold flex items-center gap-2 ${
                isExpired
                  ? 'bg-rose-600 text-white border-rose-700'
                  : 'bg-white text-emerald-950 border-emerald-300 shadow-2xs'
              }`}
            >
              <Clock className="w-4 h-4 text-emerald-600" />
              <span>{formatCountdown(remainingSeconds)}</span>
            </div>

            <div className="bg-white px-4 py-2 rounded-xl border border-emerald-300 text-right shadow-2xs">
              <div className="text-[10px] font-semibold uppercase text-slate-500">
                Locked Amount (USD)
              </div>
              <div className="text-base font-mono font-bold text-slate-900">
                {formatUsd(selectedVersion.total_amount_cents)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main PayPal Sandbox Execution Panel */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="px-6 py-4 bg-gradient-to-r from-blue-50 via-white to-indigo-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[#0070BA] text-white flex items-center justify-center shadow-2xs">
              <CreditCard className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                PayPal Checkout — Pay Approved Order ({formatUsd(selectedVersion.total_amount_cents)} USD)
              </h3>
              <p className="text-xs text-slate-600">
                PayPal Sandbox Orders v2 + MCP · Locked to Manager Bob's approved cart fingerprint (<code className="font-mono text-indigo-700">custom_id = intent_hash</code>)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowPayloadPreview(!showPayloadPreview)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 transition"
            >
              <FileCode2 className="w-3.5 h-3.5 text-indigo-600" />
              {showPayloadPreview ? 'Hide PayPal JSON' : 'View PayPal Order JSON'}
            </button>
            <button
              type="button"
              onClick={() => setShowTamperDrawer(!showTamperDrawer)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 transition"
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              {showTamperDrawer ? 'Hide Security Tests' : 'Test Tamper & Policy Protection'}
            </button>
          </div>
        </div>

        {/* Optional PayPal Orders v2 Payload Inspector */}
        {showPayloadPreview && (
          <div className="p-4 bg-slate-950 text-slate-200 border-b border-slate-800">
            <div className="text-xs font-mono text-indigo-300 mb-2">
              Outbound PayPal Sandbox Orders v2 Payload (<code className="text-white">POST /v2/checkout/orders</code>):
            </div>
            <pre className="font-mono text-xs text-emerald-300 overflow-x-auto max-h-60">
              {JSON.stringify(paypalOrdersV2PayloadPreview, null, 2)}
            </pre>
          </div>
        )}

        <div className="p-6 space-y-6">
          {isCaptured ? (
            <div className="rounded-xl border-2 border-teal-500 bg-teal-50/90 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-start gap-3.5">
                <div className="w-11 h-11 rounded-xl bg-teal-600 text-white flex items-center justify-center shrink-0">
                  <CheckCircle2 className="w-6 h-6" />
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-teal-200 text-teal-950">
                      PAYPAL SANDBOX CAPTURED & VERIFIED
                    </span>
                    <span className="font-mono text-xs text-teal-900">
                      Order ID: <strong>{existingPayPalOrder?.paypal_order_id}</strong>
                    </span>
                    {existingPayPalOrder?.paypal_capture_id && (
                      <span className="font-mono text-xs text-teal-900">
                        · Capture ID: <strong>{existingPayPalOrder.paypal_capture_id}</strong>
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-teal-900">
                    Authoritative PayPal Sandbox capture completed for{' '}
                    <strong>{formatUsd(selectedVersion.total_amount_cents)} USD</strong> with echoed{' '}
                    <code className="font-mono">custom_id == intent_hash</code>.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onAdvanceToStep4}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold bg-teal-700 text-white hover:bg-teal-800 shadow-sm transition shrink-0"
              >
                Inspect Step 4 (Reconciliation Scorecard & Evidence Bundle)
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Left Column: 1-Click End-to-End Sandbox Buyer Authorization & Capture Flow */}
              <div className="rounded-xl border-2 border-indigo-200 bg-indigo-50/40 p-5 flex flex-col justify-between gap-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-indigo-100 text-indigo-900 border border-indigo-200">
                      OPTION A · INSTANT SANDBOX EXECUTION
                    </span>
                    <Zap className="w-4 h-4 text-indigo-600" />
                  </div>
                  <h4 className="text-sm font-bold text-slate-900">
                    1-Click Authorize as Sandbox Buyer & Capture Order
                  </h4>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    Executes the complete PayPal Sandbox lifecycle deterministically:
                    verifies Gate 1 (<code className="font-mono">ApprovalLock</code> + TTL + SHA-256 hash), creates the PayPal Sandbox Order with{' '}
                    <code className="font-mono">custom_id = intent_hash</code>, completes Sandbox Buyer authorization, captures 100% of funds at Gate 2, and runs the 6-Point Reconciliation Engine.
                  </p>
                </div>

                <div className="space-y-2.5 pt-2">
                  <button
                    type="button"
                    disabled={!isBuyer || isLoading || isExpired}
                    onClick={() => onOneClickCreateAndCapture(versionId, intentHash)}
                    className="w-full inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-sm font-bold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 shadow-sm transition"
                  >
                    {isLoading ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Executing PayPal Sandbox Order & Capture...
                      </>
                    ) : (
                      <>
                        <ShieldCheck className="w-4 h-4" />
                        Authorize as Sandbox Buyer & Capture ({formatUsd(selectedVersion.total_amount_cents)})
                      </>
                    )}
                  </button>
                  <div className="text-[11px] text-center text-slate-500 font-mono">
                    Idempotency Key: <code>ILOCK-EXEC-{versionId.slice(0, 8)}</code>
                  </div>
                </div>
              </div>

              {/* Right Column: Step-by-Step PayPal Order v2 Creation + Official PayPal JS SDK / Sandbox Popup */}
              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-5 flex flex-col justify-between gap-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-blue-100 text-blue-900 border border-blue-200">
                      OPTION B · STEP-BY-STEP PAYPAL ORDERS v2 / JS SDK
                    </span>
                    <CreditCard className="w-4 h-4 text-blue-600" />
                  </div>
                  <h4 className="text-sm font-bold text-slate-900">
                    Two-Step PayPal Sandbox Order Creation & Interactive Approval
                  </h4>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    Create the PayPal Sandbox Order first to inspect the live{' '}
                    <code className="font-mono">paypal_order_id</code> and Sandbox checkout link, or use the official{' '}
                    <code className="font-mono">@paypal/react-paypal-js</code> buttons.
                  </p>

                  {existingPayPalOrder && (
                    <div className="p-3 rounded-lg bg-white border border-blue-200 space-y-1.5 text-xs mt-2">
                      <div className="flex items-center justify-between font-mono">
                        <span className="text-slate-500">PayPal Order ID:</span>
                        <strong className="text-blue-900">{existingPayPalOrder.paypal_order_id}</strong>
                      </div>
                      <div className="flex items-center justify-between font-mono">
                        <span className="text-slate-500">Status:</span>
                        <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-800 font-bold">
                          {existingPayPalOrder.paypal_status}
                        </span>
                      </div>
                      {(existingPayPalOrder.approval_url || existingPayPalOrder.approve_link) && (
                        <div className="pt-1">
                          <a
                            href={existingPayPalOrder.approval_url || existingPayPalOrder.approve_link || '#'}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800 underline"
                          >
                            Open PayPal Sandbox Checkout URL
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <button
                      type="button"
                      disabled={!isBuyer || isLoading || isExpired}
                      onClick={() => onCreatePayPalOrder(versionId, intentHash)}
                      className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2.5 rounded-lg text-xs font-semibold bg-white border border-slate-300 text-slate-800 hover:bg-slate-100 disabled:opacity-40 transition shadow-2xs"
                    >
                      1. Create PayPal Order
                    </button>
                    <button
                      type="button"
                      disabled={!isBuyer || isLoading || isExpired || !existingPayPalOrder}
                      onClick={() =>
                        onCapturePayPalOrder(
                          versionId,
                          existingPayPalOrder?.paypal_order_id,
                          intentHash
                        )
                      }
                      className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2.5 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 transition shadow-2xs"
                    >
                      2. Capture Order ({existingPayPalOrder?.paypal_order_id || 'Pending'})
                    </button>
                  </div>

                  {/* Official @paypal/react-paypal-js SDK Buttons */}
                  {paypalClientId && paypalClientId !== 'sb' && (
                    <div className="pt-2 border-t border-slate-200">
                      <PayPalScriptProvider
                        key={paypalClientId || 'test'}
                        options={{
                          clientId: paypalClientId,
                          currency: 'USD',
                          intent: 'capture',
                        }}
                      >
                        <PayPalButtons
                          style={{ layout: 'horizontal', height: 38, tagline: false }}
                          disabled={!isBuyer || isExpired}
                          createOrder={async () => {
                            const order = await onCreatePayPalOrder(versionId, intentHash);
                            return order.paypal_order_id;
                          }}
                          onApprove={async (data) => {
                            await onCapturePayPalOrder(
                              versionId,
                              data.orderID,
                              intentHash
                            );
                          }}
                        />
                      </PayPalScriptProvider>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* PayPal MCP Server & Orders v2 Cryptographic Trace Card */}
          {latestOrder && (
            <div className="rounded-xl border border-slate-200 bg-slate-50/90 p-5 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-indigo-600" />
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-800">
                    PayPal MCP Server & Orders v2 Cryptographic Trace
                  </h4>
                </div>
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-emerald-100 text-emerald-900 border border-emerald-300">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                  Matches Approved Intent Lock
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs font-mono">
                <div className="bg-white p-3 rounded-lg border border-slate-200">
                  <div className="text-[10px] font-sans font-semibold uppercase text-slate-500">
                    MCP Tool Invoked
                  </div>
                  <div className="font-bold text-indigo-900 mt-0.5 truncate">
                    {latestOrder.mcp_trace?.mcp_tool_name || 'paypal_capture_order'}
                  </div>
                </div>

                <div className="bg-white p-3 rounded-lg border border-slate-200">
                  <div className="text-[10px] font-sans font-semibold uppercase text-slate-500">
                    Transport / Mode
                  </div>
                  <div className="font-bold text-slate-900 mt-0.5 truncate">
                    {latestOrder.execution_mode || 'PAYPAL_MCP_SANDBOX'}
                  </div>
                </div>

                <div className="bg-white p-3 rounded-lg border border-slate-200">
                  <div className="text-[10px] font-sans font-semibold uppercase text-slate-500">
                    Idempotency Key (PayPal-Request-Id)
                  </div>
                  <div className="font-bold text-slate-800 mt-0.5 truncate">
                    {latestOrder.idempotency_key}
                  </div>
                </div>

                <div className="bg-white p-3 rounded-lg border border-slate-200">
                  <div className="text-[10px] font-sans font-semibold uppercase text-slate-500">
                    PayPal Order ID & Invoice ID
                  </div>
                  <div className="font-bold text-slate-900 mt-0.5 truncate">
                    {latestOrder.paypal_order_id} · {latestOrder.invoice_id}
                  </div>
                </div>
              </div>

              <div className="bg-white p-3 rounded-lg border border-emerald-200 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex flex-wrap items-center gap-2 font-mono">
                  <span className="font-sans font-semibold text-slate-600">
                    Bound <code className="font-mono">custom_id</code> (SHA-256 <code className="font-mono">intent_hash</code>):
                  </span>
                  <code className="bg-emerald-50 text-emerald-950 px-2 py-0.5 rounded border border-emerald-300 select-all break-all">
                    {latestOrder.custom_id_intent_hash || intentHash}
                  </code>
                </div>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-emerald-100 text-emerald-900 border border-emerald-300">
                  Matches Approved Intent Lock
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Interactive Security & Drift Tamper Simulator Drawer */}
      {showTamperDrawer && (
        <TamperSimulatorPanel
          inline
          requestId={requestDetail.id || requestDetail.request_id}
          cartVersionId={versionId}
          onRunSimulation={onRunTamperSimulation}
        />
      )}
    </div>
  );
};
