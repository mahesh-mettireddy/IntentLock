import React, { useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  Lock,
  XCircle,
  GitCompare,
  Clock,
  Hash,
  FileCode2,
  CheckCircle2,
  ArrowRight,
  UserCheck,
  AlertOctagon,
  RefreshCw,
} from 'lucide-react';
import {
  CartVersion,
  Persona,
  PurchaseRequestDetail,
  StructuredApiError,
} from '../types/intentlock';
import {
  computeVersionDiff,
  formatUsd,
  getLineItems,
  getStatusBadgeStyle,
  getVersionId,
  getVersionIntentHash,
} from '../utils/formatters';

interface ApproverWorkspaceProps {
  activePersona: Persona;
  requestDetail: PurchaseRequestDetail | null;
  selectedVersion: CartVersion | null;
  isLoading: boolean;
  onApprove: (
    versionId: string,
    payload: {
      comment: string;
      ttl_minutes: number;
      approval_ttl_seconds: number;
      expected_intent_hash: string;
    }
  ) => Promise<void>;
  onReject: (versionId: string, reason: string) => Promise<void>;
  onSwitchPersona: (personaId: string) => Promise<void>;
  onAdvanceToStep3: () => void;
}

const TTL_OPTIONS = [
  { label: '15 Minutes (Standard P0 Default)', minutes: 15, seconds: 900 },
  { label: '30 Minutes (Extended Window)', minutes: 30, seconds: 1800 },
  { label: '60 Minutes (1 Hour)', minutes: 60, seconds: 3600 },
  { label: '5 Seconds (Demo Expiry Test Mode)', minutes: 1, seconds: 5 },
];

export const ApproverWorkspace: React.FC<ApproverWorkspaceProps> = ({
  activePersona,
  requestDetail,
  selectedVersion,
  isLoading,
  onApprove,
  onReject,
  onSwitchPersona,
  onAdvanceToStep3,
}) => {
  const [selectedTtlIdx, setSelectedTtlIdx] = useState<number>(0);
  const [comment, setComment] = useState<string>(
    'Verified headcount pack math, SKU quantities, and budget compliance. Approved & locked.'
  );
  const [sodTestError, setSodTestError] = useState<StructuredApiError | null>(null);
  const [isTestingSod, setIsTestingSod] = useState<boolean>(false);

  if (!requestDetail || !selectedVersion) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-8 text-center">
        <p className="text-sm text-slate-600">
          Select or create a Purchase Request in Step 1 first to inspect and lock its Cart Version.
        </p>
      </div>
    );
  }

  const isApprover = activePersona.role.toUpperCase() === 'APPROVER';
  const isSelfCoordinator =
    activePersona.id === requestDetail.coordinator_id ||
    activePersona.role.toUpperCase() === 'COORDINATOR';

  const versionId = getVersionId(selectedVersion);
  const intentHash = getVersionIntentHash(selectedVersion);
  const lineItems = getLineItems(selectedVersion);
  const statusStyle = getStatusBadgeStyle(selectedVersion.status);

  // Find previous version (v_{n-1}) if version_number > 1
  const versions = requestDetail.versions || [];
  const prevVersion =
    versions.find((v) => v.version_number === selectedVersion.version_number - 1) ||
    null;
  const diff = computeVersionDiff(prevVersion, selectedVersion);

  const budgetCents =
    requestDetail.budget_limit_cents ?? requestDetail.budget_ceiling_cents ?? null;
  const withinBudget =
    budgetCents === null || selectedVersion.total_amount_cents <= budgetCents;

  const selectedTtl = TTL_OPTIONS[selectedTtlIdx];

  const handleTestSelfApprovalBlock = async () => {
    setIsTestingSod(true);
    setSodTestError(null);
    try {
      await onApprove(versionId, {
        comment: 'Coordinator attempting self-approval test (G-04)',
        ttl_minutes: selectedTtl.minutes,
        approval_ttl_seconds: selectedTtl.seconds,
        expected_intent_hash: intentHash,
      });
    } catch (err: any) {
      setSodTestError({
        status: err.status || 403,
        code: err.code || 'GUARDRAIL_G04_SOD_SELF_APPROVAL_FORBIDDEN',
        message:
          err.message ||
          'Guardrail G-04 Violation: Separation of Duties forbids a Coordinator from approving their own purchase request.',
        guardrail_violated: err.guardrail_violated || 'G-04_SEPARATION_OF_DUTIES',
        audit_event_id: err.audit_event_id,
      });
    } finally {
      setIsTestingSod(false);
    }
  };

  const handleApproveClick = async () => {
    setSodTestError(null);
    await onApprove(versionId, {
      comment: comment.trim() || 'Approved after line-item and budget review.',
      ttl_minutes: selectedTtl.minutes,
      approval_ttl_seconds: selectedTtl.seconds,
      expected_intent_hash: intentHash,
    });
  };

  const handleRejectClick = async () => {
    setSodTestError(null);
    const reason =
      comment.trim() ||
      'Rejected by Approver: please revise quantities to stay well within team budget.';
    await onReject(versionId, reason);
  };

  const isAlreadyLocked =
    selectedVersion.status === 'APPROVED_LOCKED' ||
    Boolean(selectedVersion.approval_lock && selectedVersion.approval_lock.decision === 'APPROVED');

  return (
    <div className="space-y-6">
      {/* Separation of Duties (G-04) Banner */}
      {!isApprover || isSelfCoordinator ? (
        <div className="rounded-xl border-2 border-rose-400 bg-rose-50 p-5 shadow-sm space-y-4">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
            <div className="flex items-start gap-3.5">
              <div className="w-10 h-10 rounded-xl bg-rose-100 border border-rose-300 flex items-center justify-center shrink-0">
                <ShieldAlert className="w-5 h-5 text-rose-700" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-rose-200 text-rose-900">
                    GUARDRAIL G-04 ENFORCED
                  </span>
                  <h3 className="text-sm font-bold text-rose-950">
                    Separation of Duties (SoD) — Self-Approval Blocked
                  </h3>
                </div>
                <p className="text-xs text-rose-900 mt-1 leading-relaxed">
                  You are currently acting as <strong>{activePersona.name} ({activePersona.role})</strong>. Under Guardrail{' '}
                  <code className="font-mono font-semibold">G-04</code>, the requesting Coordinator (or Buyer) is cryptographically and role-blocked from approving their own Cart Version. Switch to <strong>Bob Martinez (Approver)</strong> to sign the lock—or click{' '}
                  <em>"Try Self-Approving (Trigger Backend 403)"</em> to verify live backend enforcement!
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2.5 shrink-0">
              <button
                type="button"
                disabled={isTestingSod || isLoading}
                onClick={handleTestSelfApprovalBlock}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold bg-white border border-rose-400 text-rose-900 hover:bg-rose-100 transition shadow-2xs"
              >
                <AlertOctagon className="w-4 h-4 text-rose-600" />
                {isTestingSod
                  ? 'Testing Backend 403...'
                  : 'Try Self-Approving (Trigger Backend 403)'}
              </button>
              <button
                type="button"
                onClick={() => onSwitchPersona('user-approver-bob')}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 transition shadow-sm"
              >
                <UserCheck className="w-4 h-4" />
                Switch to Approver Bob in 1 Click
              </button>
            </div>
          </div>

          {/* Live Backend 403 Rejection Proof Box */}
          {sodTestError && (
            <div className="rounded-lg bg-slate-900 text-slate-100 p-4 border border-rose-500/50 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 text-xs font-mono font-bold text-rose-400">
                  <XCircle className="w-4 h-4" />
                  LIVE BACKEND HTTP {sodTestError.status} BLOCKED — {sodTestError.code}
                </span>
                {sodTestError.audit_event_id && (
                  <span className="font-mono text-[11px] text-slate-400">
                    Audit Event Logged: {sodTestError.audit_event_id}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-200 font-mono">
                {sodTestError.message}
              </p>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50/80 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-600 text-white flex items-center justify-center shrink-0">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-indigo-950">
                Authorized Approver Session — {activePersona.name} ({activePersona.department})
              </h3>
              <p className="text-xs text-indigo-800">
                Separation of Duties verified (<code className="font-mono">approver_id != coordinator_id</code>). You may inspect and cryptographically lock Cart Version <code className="font-mono font-bold">v{selectedVersion.version_number}</code>.
              </p>
            </div>
          </div>
          <span className="font-mono text-xs font-semibold px-3 py-1 rounded-full bg-indigo-100 text-indigo-900 border border-indigo-300">
            RBAC: APPROVER VERIFIED
          </span>
        </div>
      )}

      {/* Version Diff Inspector (v_{n-1} -> v_n) */}
      {diff.hasPrevious && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
          <div className="px-5 py-3.5 bg-amber-50/80 border-b border-amber-200 text-slate-900 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <GitCompare className="w-4 h-4 text-amber-700" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-amber-950">
                What Changed Since Previous Cart (v{diff.prevVersionNum} → v{diff.currVersionNum})
              </h3>
            </div>
            <div className="flex items-center gap-3 font-mono text-xs">
              <span className="text-slate-600">
                v{diff.prevVersionNum}: {formatUsd(diff.oldTotalCents)}
              </span>
              <span className="text-slate-400">→</span>
              <span className="text-slate-900 font-bold">
                v{diff.currVersionNum}: {formatUsd(diff.newTotalCents)}
              </span>
              <span
                className={`px-2 py-0.5 rounded font-bold ${
                  diff.netDeltaCents > 0
                    ? 'bg-amber-200/70 text-amber-950 border border-amber-300'
                    : diff.netDeltaCents < 0
                    ? 'bg-emerald-200/70 text-emerald-950 border border-emerald-300'
                    : 'bg-slate-200 text-slate-700'
                }`}
              >
                {diff.netDeltaCents >= 0 ? '+' : ''}
                {formatUsd(diff.netDeltaCents)}
              </span>
            </div>
          </div>

          <div className="p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 bg-slate-50/60">
            {diff.items.map((d) => (
              <div
                key={d.sku}
                className={`p-3 rounded-lg border text-xs flex flex-col justify-between gap-1.5 ${
                  d.change === 'ADDED'
                    ? 'bg-emerald-50/70 border-emerald-300 text-emerald-950'
                    : d.change === 'REMOVED'
                    ? 'bg-rose-50/70 border-rose-300 text-rose-950'
                    : d.change === 'MODIFIED'
                    ? 'bg-amber-50/70 border-amber-300 text-amber-950'
                    : 'bg-white border-slate-200 text-slate-700'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-bold">{d.sku}</span>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                      d.change === 'ADDED'
                        ? 'bg-emerald-200 text-emerald-900'
                        : d.change === 'REMOVED'
                        ? 'bg-rose-200 text-rose-900'
                        : d.change === 'MODIFIED'
                        ? 'bg-amber-200 text-amber-900'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {d.change}
                  </span>
                </div>
                <div className="font-semibold truncate">{d.product_name}</div>
                <div className="font-mono text-[11px] flex items-center justify-between pt-1 border-t border-black/5">
                  <span>
                    Qty: {d.oldQty} → <strong>{d.newQty}</strong>
                  </span>
                  <span>
                    {d.deltaCents >= 0 ? '+' : ''}
                    {formatUsd(d.deltaCents)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Immutable Snapshot Inspection Card */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4 bg-slate-50/70">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="font-mono text-xs font-bold px-2.5 py-1 rounded bg-indigo-100 text-indigo-900">
                CartVersion v{selectedVersion.version_number}
              </span>
              <h3 className="text-base font-bold text-slate-900">
                {requestDetail.title}
              </h3>
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${statusStyle.bg} ${statusStyle.border} ${statusStyle.text}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`} />
                {statusStyle.label}
              </span>
            </div>
            <p className="text-xs text-slate-600 mt-1">
              Requested by <strong>{requestDetail.coordinator_name || 'Alice Chen'}</strong> · Merchant:{' '}
              <strong>Acme Workspace Supplies (USD)</strong>
            </p>
          </div>

          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-[11px] font-semibold uppercase text-slate-500">
                Snapshot Total
              </div>
              <div className="text-xl font-mono font-bold text-slate-900">
                {formatUsd(selectedVersion.total_amount_cents)}
              </div>
            </div>
            {budgetCents !== null && (
              <div
                className={`px-3 py-1.5 rounded-lg border text-xs font-semibold ${
                  withinBudget
                    ? 'bg-emerald-50 border-emerald-300 text-emerald-900'
                    : 'bg-rose-50 border-rose-300 text-rose-900'
                }`}
              >
                <div>Budget Cap: {formatUsd(budgetCents)}</div>
                <div className="font-mono text-[11px]">
                  {withinBudget ? '✓ WITHIN BUDGET' : '⚠ EXCEEDS CAP'}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Read-Only Line Item Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-100/80 text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                <th className="py-3 px-4">SKU</th>
                <th className="py-3 px-4">Product & Pack Description</th>
                <th className="py-3 px-4">AI Explanation & Headcount Math</th>
                <th className="py-3 px-4 text-right">Unit Price</th>
                <th className="py-3 px-4 text-center">Locked Qty</th>
                <th className="py-3 px-4 text-right">Line Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 text-sm">
              {lineItems.map((it) => (
                <tr key={it.sku} className="hover:bg-slate-50/60">
                  <td className="py-3 px-4 font-mono text-xs font-semibold text-indigo-700">
                    {it.sku}
                  </td>
                  <td className="py-3 px-4">
                    <div className="font-semibold text-slate-900">
                      {it.product_name}
                    </div>
                    <div className="text-xs text-slate-500">{it.pack_size_desc}</div>
                  </td>
                  <td className="py-3 px-4 max-w-md">
                    <div className="text-xs text-slate-700">
                      {it.selection_rationale}
                    </div>
                    {it.headcount_math && (
                      <div className="text-[11px] font-mono text-indigo-700 mt-0.5">
                        {it.headcount_math}
                      </div>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right font-mono tabular-nums text-slate-700">
                    {formatUsd(it.unit_price_cents)}
                  </td>
                  <td className="py-3 px-4 text-center font-mono font-bold text-slate-900">
                    {it.quantity}
                  </td>
                  <td className="py-3 px-4 text-right font-mono font-semibold tabular-nums text-slate-900">
                    {formatUsd(it.line_total_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Collapsible Cryptographic Fingerprint Details */}
        <details className="group border-t border-slate-200 bg-slate-50/70">
          <summary className="px-5 py-3 cursor-pointer flex items-center justify-between text-xs font-semibold text-slate-700 hover:bg-slate-100/80 transition list-none">
            <div className="flex items-center gap-2">
              <Hash className="w-4 h-4 text-indigo-600" />
              <span>
                View Cryptographic Price & Cart Lock Details (SHA-256 <code className="font-mono text-indigo-700">{intentHash.slice(0, 16)}…</code>)
              </span>
            </div>
            <span className="text-[11px] text-indigo-600 group-open:rotate-180 transition">
              ▼ Expand Technical Details
            </span>
          </summary>

          <div className="p-5 bg-slate-900 text-slate-100 border-t border-slate-800 space-y-3">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-slate-950/80 p-3.5 rounded-lg border border-slate-800 space-y-1.5">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  SHA-256 <code className="font-mono text-emerald-300">intent_hash</code> (v{selectedVersion.version_number}):
                </div>
                <code className="block font-mono text-xs text-emerald-300 break-all select-all">
                  {intentHash}
                </code>
                {selectedVersion.approval_lock && (
                  <div className="pt-2 border-t border-slate-800 mt-2">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      HMAC-SHA256 <code className="font-mono text-indigo-300">approval_signature</code>:
                    </div>
                    <code className="block font-mono text-xs text-indigo-300 break-all select-all mt-0.5">
                      {selectedVersion.approval_lock.approval_signature}
                    </code>
                  </div>
                )}
              </div>

              <div className="bg-slate-950/80 p-3.5 rounded-lg border border-slate-800">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  <FileCode2 className="w-3.5 h-3.5 text-indigo-400" />
                  Canonical JSON Payload (Deterministic Input to SHA-256):
                </div>
                <pre className="font-mono text-[11px] text-slate-300 overflow-x-auto max-h-28">
                  {typeof selectedVersion.canonical_payload_json === 'string'
                    ? selectedVersion.canonical_payload_json
                    : JSON.stringify(selectedVersion.canonical_payload_json)}
                </pre>
              </div>
            </div>
          </div>
        </details>

        {/* Cryptographic Lock Minting Action Panel */}
        <div className="p-5 bg-white border-t border-slate-200 space-y-4">
          {isAlreadyLocked ? (
            <div className="rounded-xl border-2 border-emerald-400 bg-emerald-50/90 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-600 text-white flex items-center justify-center shrink-0">
                  <Lock className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-emerald-200 text-emerald-950">
                      APPROVED_LOCKED
                    </span>
                    <h4 className="text-sm font-bold text-emerald-950">
                      Cart Version v{selectedVersion.version_number} is Cryptographically Locked
                    </h4>
                  </div>
                  <p className="text-xs text-emerald-900 mt-1">
                    Signed by <strong>{selectedVersion.approval_lock?.approver_name || 'Bob Martinez'}</strong> · Expires at{' '}
                    <code className="font-mono">
                      {selectedVersion.approval_lock?.expires_at ||
                        selectedVersion.approval_lock?.expires_at_utc}
                    </code>
                    . Ready for Step 3 PayPal Sandbox Checkout by Buyer Charlie.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onAdvanceToStep3}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold bg-emerald-700 text-white hover:bg-emerald-800 shadow-sm transition shrink-0"
              >
                Proceed to Step 3 (PayPal Sandbox Checkout)
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Expiry TTL Selector */}
                <div>
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-2">
                    <Clock className="w-3.5 h-3.5 text-indigo-600" />
                    Select Approval Lock Expiry Window (TTL — Guardrail G-06):
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {TTL_OPTIONS.map((opt, idx) => (
                      <button
                        key={opt.label}
                        type="button"
                        onClick={() => setSelectedTtlIdx(idx)}
                        className={`px-3 py-2 rounded-lg text-xs font-medium border text-left transition flex items-center justify-between ${
                          selectedTtlIdx === idx
                            ? 'bg-indigo-50 border-indigo-500 text-indigo-950 font-semibold shadow-2xs'
                            : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                        }`}
                      >
                        <span>{opt.label}</span>
                        {selectedTtlIdx === idx && (
                          <CheckCircle2 className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Managerial Comment / Rejection Reason */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-2">
                    Approver Decision Note / Rejection Feedback:
                  </label>
                  <textarea
                    rows={3}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Enter approval sign-off note or rejection reason..."
                    className="w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100">
                <div className="text-xs text-slate-500">
                  Locking mints an HMAC-SHA256 signature binding <code className="font-mono">v{selectedVersion.version_number}</code> +{' '}
                  <code className="font-mono">{formatUsd(selectedVersion.total_amount_cents)}</code> + TTL.
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    disabled={!isApprover || isSelfCoordinator || isLoading}
                    onClick={handleRejectClick}
                    className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-xs font-semibold border border-rose-300 text-rose-700 bg-white hover:bg-rose-50 disabled:opacity-40 transition"
                  >
                    <XCircle className="w-4 h-4" />
                    Reject Version v{selectedVersion.version_number}
                  </button>

                  <button
                    type="button"
                    disabled={!isApprover || isSelfCoordinator || isLoading}
                    onClick={handleApproveClick}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40 shadow-sm transition"
                  >
                    {isLoading ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Minting SHA-256 Lock...
                      </>
                    ) : (
                      <>
                        <Lock className="w-4 h-4" />
                        Approve & Lock Intent (v{selectedVersion.version_number})
                      </>
                    )}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
