import React, { useEffect, useState } from 'react';
import {
  Sparkles,
  Plus,
  Minus,
  Trash2,
  Send,
  AlertTriangle,
  CheckCircle2,
  Hash,
  FileCode2,
  Layers,
  RefreshCw,
  ShoppingBag,
  Info,
  ShieldCheck,
  ArrowRight,
  Cpu,
} from 'lucide-react';
import {
  CartLineItem,
  CartVersion,
  Persona,
  Product,
  PurchaseRequestDetail,
} from '../types/intentlock';
import {
  formatUsd,
  getLineItems,
  getStatusBadgeStyle,
  getVersionId,
  getVersionIntentHash,
  PRESET_REQUEST_SCENARIOS,
  shortHash,
} from '../utils/formatters';

interface CoordinatorWorkspaceProps {
  activePersona: Persona;
  requestDetail: PurchaseRequestDetail | null;
  selectedVersion: CartVersion | null;
  onSelectVersion: (versionNumber: number) => void;
  catalog: Product[];
  isLoading: boolean;
  prefillPrompt?: string;
  onClearPrefill?: () => void;
  onCreateRequest: (payload: {
    title: string;
    raw_need_text: string;
    budget_limit_cents: number | null;
  }) => Promise<void>;
  onReviseVersion: (payload: {
    revision_prompt?: string | null;
    budget_limit_cents?: number | null;
    line_item_edits?: Array<{
      sku: string;
      quantity: number;
      selection_rationale?: string;
      headcount_math?: string;
    }> | null;
  }) => Promise<void>;
  onSubmitForApproval: (versionId: string, note: string) => Promise<void>;
  onSwitchPersona: (personaId: string) => Promise<void>;
  onAdvanceToStep2: () => void;
}

export const CoordinatorWorkspace: React.FC<CoordinatorWorkspaceProps> = ({
  activePersona,
  requestDetail,
  selectedVersion,
  onSelectVersion,
  catalog,
  isLoading,
  prefillPrompt,
  onClearPrefill,
  onCreateRequest,
  onReviseVersion,
  onSubmitForApproval,
  onSwitchPersona,
  onAdvanceToStep2,
}) => {
  const [isComposingNew, setIsComposingNew] = useState<boolean>(!requestDetail);
  const [title, setTitle] = useState<string>(
    PRESET_REQUEST_SCENARIOS[0].title
  );
  const [needText, setNeedText] = useState<string>(
    PRESET_REQUEST_SCENARIOS[0].need
  );
  const [budgetDollars, setBudgetDollars] = useState<string>(
    PRESET_REQUEST_SCENARIOS[0].budgetDollars
  );

  // Revision state
  const [revisionPrompt, setRevisionPrompt] = useState<string>('');
  const [submissionNote, setSubmissionNote] = useState<string>(
    'Verified headcount and pack-size quantities against team onboarding list. Ready for approval.'
  );
  const [selectedAddSku, setSelectedAddSku] = useState<string>('SKU-001');
  const [showCanonicalModal, setShowCanonicalModal] = useState<boolean>(false);

  // Local editable line items copy when editing quantities manually
  const [editedItems, setEditedItems] = useState<CartLineItem[] | null>(null);

  useEffect(() => {
    if (prefillPrompt && prefillPrompt.trim()) {
      setIsComposingNew(true);
      setTitle('Catalog Quick-Start Supply Request');
      setNeedText(prefillPrompt.trim());
      setBudgetDollars('350.00');
      onClearPrefill?.();
    }
  }, [prefillPrompt, onClearPrefill]);

  const currentItems = editedItems || getLineItems(selectedVersion);
  const hasUnsavedItemEdits = editedItems !== null;

  const isCoordinator = activePersona.role.toUpperCase() === 'COORDINATOR';

  const handleLoadPreset = (preset: typeof PRESET_REQUEST_SCENARIOS[0]) => {
    setIsComposingNew(true);
    setTitle(preset.title);
    setNeedText(preset.need);
    setBudgetDollars(preset.budgetDollars);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!needText.trim()) return;
    const budgetCents = budgetDollars
      ? Math.round(parseFloat(budgetDollars) * 100)
      : null;
    await onCreateRequest({
      title: title.trim() || 'Team Workspace Supply Request',
      raw_need_text: needText.trim(),
      budget_limit_cents: budgetCents && !isNaN(budgetCents) ? budgetCents : null,
    });
    setIsComposingNew(false);
    setEditedItems(null);
  };

  const handleQtyDelta = (sku: string, delta: number) => {
    const base = editedItems ? [...editedItems] : getLineItems(selectedVersion).map((x) => ({ ...x }));
    const idx = base.findIndex((i) => i.sku === sku);
    if (idx === -1) return;
    const newQty = base[idx].quantity + delta;
    if (newQty <= 0) {
      base.splice(idx, 1);
    } else {
      const catProduct = catalog.find((p) => p.sku === sku);
      const maxStock = catProduct?.stock_available ?? 50;
      const clampedQty = Math.min(newQty, maxStock);
      base[idx] = {
        ...base[idx],
        quantity: clampedQty,
        line_total_cents: clampedQty * base[idx].unit_price_cents,
      };
    }
    setEditedItems(base);
  };

  const handleRemoveItem = (sku: string) => {
    const base = editedItems ? [...editedItems] : getLineItems(selectedVersion).map((x) => ({ ...x }));
    const filtered = base.filter((i) => i.sku !== sku);
    if (filtered.length === 0) return; // keep at least 1 item
    setEditedItems(filtered);
  };

  const handleAddCatalogSku = () => {
    const product = catalog.find((p) => p.sku === selectedAddSku);
    if (!product) return;
    const base = editedItems ? [...editedItems] : getLineItems(selectedVersion).map((x) => ({ ...x }));
    const existingIdx = base.findIndex((i) => i.sku === product.sku);
    if (existingIdx >= 0) {
      const nextQty = Math.min(base[existingIdx].quantity + 1, product.stock_available);
      base[existingIdx] = {
        ...base[existingIdx],
        quantity: nextQty,
        line_total_cents: nextQty * product.unit_price_cents,
      };
    } else {
      base.push({
        sku: product.sku,
        product_name: product.name,
        pack_size_desc: product.pack_size_desc,
        unit_price_cents: product.unit_price_cents,
        unit_price_usd: (product.unit_price_cents / 100).toFixed(2),
        quantity: 1,
        line_total_cents: product.unit_price_cents,
        line_total_usd: (product.unit_price_cents / 100).toFixed(2),
        selection_rationale: `Manually added by Coordinator (${activePersona.name})`,
        headcount_math: product.recommended_rule || '1 pack manually selected',
      });
    }
    setEditedItems(base);
  };

  const handleSaveManualRevision = async () => {
    if (!editedItems || editedItems.length === 0) return;
    await onReviseVersion({
      revision_prompt: `Coordinator adjusted line item quantities manually (${editedItems.length} SKUs).`,
      budget_limit_cents: requestDetail?.budget_limit_cents ?? requestDetail?.budget_ceiling_cents ?? null,
      line_item_edits: editedItems.map((it) => ({
        sku: it.sku,
        quantity: it.quantity,
        selection_rationale: it.selection_rationale,
        headcount_math: it.headcount_math,
      })),
    });
    setEditedItems(null);
  };

  const handleNaturalLanguageRevision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!revisionPrompt.trim()) return;
    await onReviseVersion({
      revision_prompt: revisionPrompt.trim(),
      budget_limit_cents: requestDetail?.budget_limit_cents ?? requestDetail?.budget_ceiling_cents ?? null,
      line_item_edits: null,
    });
    setRevisionPrompt('');
    setEditedItems(null);
  };

  const computedTotalCents = currentItems.reduce(
    (acc, item) => acc + item.unit_price_cents * item.quantity,
    0
  );
  const budgetLimitCents =
    requestDetail?.budget_limit_cents ?? requestDetail?.budget_ceiling_cents ?? null;
  const isWithinBudget =
    budgetLimitCents === null || computedTotalCents <= budgetLimitCents;

  const warnings =
    selectedVersion?.agent_warnings || selectedVersion?.guardrail_warnings || [];
  const versionId = getVersionId(selectedVersion);
  const intentHash = getVersionIntentHash(selectedVersion);
  const statusStyle = getStatusBadgeStyle(selectedVersion?.status);

  return (
    <div className="space-y-6">
      {/* Role Guidance Banner if not Alice */}
      {!isCoordinator && (
        <div className="rounded-xl border border-amber-300 bg-amber-50/90 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-semibold text-amber-900">
                Viewing Coordinator Workspace as {activePersona.name} ({activePersona.role})
              </h4>
              <p className="text-xs text-amber-800 mt-0.5">
                In IntentLock, only the <strong>Coordinator</strong> role can create requests, revise cart versions, or submit proposals for approval.
              </p>
            </div>
          </div>
          <button
            onClick={() => onSwitchPersona('user-coord-alice')}
            className="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold bg-amber-800 text-white hover:bg-amber-900 transition shadow-sm"
          >
            Switch to Alice (Coordinator)
          </button>
        </div>
      )}

      {/* Top Composer Toggle / New Request Form */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="px-6 py-4 bg-gradient-to-r from-indigo-50 via-white to-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-2xs">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">
                AI Shopping Cart Builder — Acme Workspace Supplies
              </h2>
              <p className="text-xs text-slate-600">
                Tell the assistant what supplies your team needs. It picks the right items, calculates pack quantities, and checks live inventory.
              </p>
            </div>
          </div>
          {requestDetail && (
            <button
              type="button"
              onClick={() => setIsComposingNew(!isComposingNew)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-white hover:bg-slate-50 text-indigo-700 border border-indigo-200 shadow-2xs transition"
            >
              <Plus className="w-3.5 h-3.5" />
              {isComposingNew ? 'Close Form' : 'Start New Supply Order'}
            </button>
          )}
        </div>

        {(isComposingNew || !requestDetail) && (
          <form onSubmit={handleCreateSubmit} className="p-5 space-y-4 bg-slate-50/50">
            {/* Quick-Load Scenario Chips */}
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                1-Click Realistic Team Supply Scenarios (Click to Load):
              </label>
              <div className="flex flex-wrap gap-2">
                {PRESET_REQUEST_SCENARIOS.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => handleLoadPreset(preset)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition text-left ${
                      needText === preset.need
                        ? 'bg-indigo-50 border-indigo-400 text-indigo-900 shadow-sm'
                        : 'bg-white border-slate-200 text-slate-700 hover:border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="md:col-span-3">
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Purchase Request Title
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g., Monday Engineering Onboarding & Breakroom Restock"
                  className="w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Budget Ceiling ($ USD)
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-sm font-mono text-slate-400">
                    $
                  </span>
                  <input
                    type="number"
                    step="0.01"
                    min="1"
                    max="5000"
                    value={budgetDollars}
                    onChange={(e) => setBudgetDollars(e.target.value)}
                    placeholder="450.00"
                    className="w-full rounded-lg border border-slate-300 bg-white pl-7 pr-3 py-2 text-sm font-mono text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                  />
                </div>
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Informal Natural Language Need (Headcount, Items, Constraints)
              </label>
              <textarea
                rows={3}
                value={needText}
                onChange={(e) => setNeedText(e.target.value)}
                placeholder="Describe what your team needs..."
                className="w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                required
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <ShieldCheck className="w-4 h-4 text-emerald-600" />
                <span>
                  Guardrail <strong>G-01</strong> enforces authoritative SQLite catalog pricing · <strong>G-02</strong> enforces live warehouse stock bounds.
                </span>
              </div>
              <button
                type="submit"
                disabled={isLoading || !isCoordinator}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 transition shadow-sm"
              >
                {isLoading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Synthesizing Grounded Cart Proposal...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Generate Inventory-Checked Cart Proposal (v1)
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Active Request & Cart Version Inspector */}
      {requestDetail && selectedVersion && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          {/* Request Header & Version Switcher */}
          <div className="p-5 border-b border-slate-200 bg-slate-50/70 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-mono text-xs font-semibold px-2.5 py-0.5 rounded bg-slate-200 text-slate-800">
                  {requestDetail.id || requestDetail.request_id}
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
              <p className="text-xs text-slate-600 italic">
                "{requestDetail.raw_need_text || requestDetail.natural_language_need}"
              </p>
            </div>

            {/* Version Tabs (v1, v2, ...) */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-slate-500 flex items-center gap-1 mr-1">
                <Layers className="w-3.5 h-3.5" />
                Immutable Versions:
              </span>
              {(requestDetail.versions || [selectedVersion]).map((ver) => {
                const isSelected = ver.version_number === selectedVersion.version_number;
                const isLatest =
                  ver.version_number ===
                  Math.max(...(requestDetail.versions || [selectedVersion]).map((v) => v.version_number));
                return (
                  <button
                    key={ver.id || ver.version_number}
                    type="button"
                    onClick={() => {
                      setEditedItems(null);
                      onSelectVersion(ver.version_number);
                    }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border transition flex items-center gap-1.5 ${
                      isSelected
                        ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                        : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    <span>v{ver.version_number}</span>
                    <span
                      className={`text-[10px] px-1.5 py-0.2 rounded ${
                        isSelected
                          ? 'bg-indigo-500 text-indigo-100'
                          : isLatest
                          ? 'bg-amber-100 text-amber-800'
                          : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      {ver.status === 'SUPERSEDED'
                        ? 'Superseded'
                        : ver.status === 'APPROVED_LOCKED'
                        ? 'Locked'
                        : isLatest
                        ? 'Current'
                        : ver.status}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* AI Agent Executive Explanation & Telemetry Banner */}
          <div className="p-5 border-b border-slate-200 bg-indigo-50/40 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-indigo-100 text-indigo-900 border border-indigo-200">
                  <Cpu className="w-3.5 h-3.5 text-indigo-700" />
                  AI Agent Translation Rationale (v{selectedVersion.version_number})
                </span>
                <span className="font-mono text-xs text-slate-600 bg-white px-2.5 py-1 rounded border border-slate-200">
                  Provider: <strong>{selectedVersion.llm_provider_used}</strong> ({selectedVersion.llm_model_used})
                </span>
                {selectedVersion.llm_latency_ms ? (
                  <span className="font-mono text-xs text-slate-500">
                    {selectedVersion.llm_latency_ms}ms
                  </span>
                ) : null}
                {selectedVersion.llm_failover_hops > 0 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300">
                    Auto-Failover Triggered ({selectedVersion.llm_failover_hops} hop)
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-600">
                  Merchant: <strong className="text-slate-900">Acme Workspace Supplies (MERCH-ACME-001)</strong>
                </span>
              </div>
            </div>

            <p className="text-sm text-slate-800 leading-relaxed bg-white p-3.5 rounded-lg border border-indigo-100 shadow-2xs">
              {selectedVersion.agent_summary ||
                selectedVersion.agent_explanation ||
                'Grounded informal request against Acme Workspace Supplies 15-SKU catalog using deterministic per-person pack rules.'}
            </p>

            {selectedVersion.agent_budget_notes && (
              <div className="flex items-center gap-2 text-xs text-slate-700 bg-white/80 px-3 py-2 rounded-lg border border-slate-200">
                <Info className="w-4 h-4 text-indigo-600 shrink-0" />
                <span>
                  <strong>Budget & Math Note:</strong> {selectedVersion.agent_budget_notes}
                </span>
              </div>
            )}

            {/* Guardrail / Constraint Warnings (G-01, G-02, G-03) */}
            {warnings.length > 0 && (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3.5 space-y-1.5">
                <div className="flex items-center gap-2 text-xs font-bold text-amber-900 uppercase tracking-wider">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                  Deterministic Guardrail & Inventory Notices ({warnings.length})
                </div>
                <ul className="list-disc list-inside text-xs text-amber-900 space-y-1">
                  {warnings.map((w, idx) => (
                    <li key={idx} className="leading-relaxed">
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Line Items Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-100/80 text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                  <th className="py-3 px-4">SKU</th>
                  <th className="py-3 px-4">Product & Pack Size</th>
                  <th className="py-3 px-4">AI Selection & Pack-Math Rationale</th>
                  <th className="py-3 px-4 text-right">Unit Price</th>
                  <th className="py-3 px-4 text-center">Quantity</th>
                  <th className="py-3 px-4 text-right">Line Total</th>
                  <th className="py-3 px-4 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 text-sm">
                {currentItems.map((item) => {
                  const catalogProd = catalog.find((p) => p.sku === item.sku);
                  const stockAvail = catalogProd?.stock_available ?? 25;
                  return (
                    <tr key={item.sku} className="hover:bg-slate-50/80 transition">
                      <td className="py-3.5 px-4 align-top font-mono text-xs font-semibold text-indigo-700 whitespace-nowrap">
                        {item.sku}
                      </td>
                      <td className="py-3.5 px-4 align-top">
                        <div className="font-semibold text-slate-900">
                          {item.product_name}
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          {item.pack_size_desc || catalogProd?.pack_size_desc}
                        </div>
                        <div className="inline-flex items-center gap-1.5 mt-1 text-[11px] font-mono text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          In Stock: {stockAvail} units
                        </div>
                      </td>
                      <td className="py-3.5 px-4 align-top max-w-md">
                        <p className="text-xs text-slate-700 leading-relaxed">
                          {item.selection_rationale || 'Matched to team supply requirement.'}
                        </p>
                        {item.headcount_math && (
                          <div className="mt-1 text-[11px] font-mono text-indigo-800 bg-indigo-50/70 px-2 py-0.5 rounded border border-indigo-200/70 inline-block">
                            Math: {item.headcount_math}
                          </div>
                        )}
                      </td>
                      <td className="py-3.5 px-4 align-top text-right font-mono tabular-nums text-slate-700 whitespace-nowrap">
                        {formatUsd(item.unit_price_cents)}
                      </td>
                      <td className="py-3.5 px-4 align-top text-center whitespace-nowrap">
                        <div className="inline-flex items-center rounded-lg border border-slate-300 bg-white p-0.5 shadow-2xs">
                          <button
                            type="button"
                            disabled={!isCoordinator || isLoading}
                            onClick={() => handleQtyDelta(item.sku, -1)}
                            className="p-1 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded disabled:opacity-40"
                            title="Decrease quantity"
                          >
                            <Minus className="w-3.5 h-3.5" />
                          </button>
                          <span className="px-3 font-mono text-xs font-bold tabular-nums text-slate-900">
                            {item.quantity}
                          </span>
                          <button
                            type="button"
                            disabled={!isCoordinator || isLoading || item.quantity >= stockAvail}
                            onClick={() => handleQtyDelta(item.sku, 1)}
                            className="p-1 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded disabled:opacity-40"
                            title="Increase quantity"
                          >
                            <Plus className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                      <td className="py-3.5 px-4 align-top text-right font-mono font-semibold tabular-nums text-slate-900 whitespace-nowrap">
                        {formatUsd(item.unit_price_cents * item.quantity)}
                      </td>
                      <td className="py-3.5 px-4 align-top text-center">
                        <button
                          type="button"
                          disabled={!isCoordinator || isLoading || currentItems.length <= 1}
                          onClick={() => handleRemoveItem(item.sku)}
                          className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition disabled:opacity-30"
                          title="Remove SKU from cart"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Manual Add Item & Total Summary Bar */}
          <div className="p-4 bg-slate-50 border-t border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-4">
            {/* Add Catalog Item Control */}
            <div className="flex flex-wrap items-center gap-2">
              <ShoppingBag className="w-4 h-4 text-slate-500" />
              <span className="text-xs font-semibold text-slate-700">
                Add Catalog SKU:
              </span>
              <select
                value={selectedAddSku}
                onChange={(e) => setSelectedAddSku(e.target.value)}
                disabled={!isCoordinator || isLoading}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-800 focus:border-indigo-500 focus:outline-none"
              >
                {catalog.map((prod) => (
                  <option key={prod.sku} value={prod.sku}>
                    {prod.sku} — {prod.name} (${prod.unit_price_usd}, Stock: {prod.stock_available})
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!isCoordinator || isLoading}
                onClick={handleAddCatalogSku}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-slate-300 text-slate-800 hover:bg-slate-100 disabled:opacity-40 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Item
              </button>
            </div>

            {/* Totals & Budget Check */}
            <div className="flex flex-wrap items-center gap-4">
              {budgetLimitCents !== null && (
                <div className="text-xs">
                  <span className="text-slate-500">Budget Cap: </span>
                  <span className="font-mono font-semibold text-slate-800">
                    {formatUsd(budgetLimitCents)}
                  </span>
                  <span
                    className={`ml-2 px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                      isWithinBudget
                        ? 'bg-emerald-100 text-emerald-800'
                        : 'bg-rose-100 text-rose-800'
                    }`}
                  >
                    {isWithinBudget
                      ? `${formatUsd(budgetLimitCents - computedTotalCents)} under cap`
                      : `${formatUsd(computedTotalCents - budgetLimitCents)} over cap`}
                  </span>
                </div>
              )}

              <div className="flex items-baseline gap-2 bg-white px-4 py-2 rounded-lg border border-slate-200 shadow-2xs">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Cart Total (USD):
                </span>
                <span className="text-lg font-mono font-bold tabular-nums text-slate-900">
                  {formatUsd(computedTotalCents)}
                </span>
                <span className="text-[11px] font-mono text-slate-400">
                  ({computedTotalCents} cents)
                </span>
              </div>
            </div>
          </div>

          {/* Unsaved Quantity Edits Banner -> Mint New Immutable Version v(n+1) */}
          {hasUnsavedItemEdits && (
            <div className="px-5 py-3.5 bg-amber-50 border-t border-amber-300 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-2.5 text-xs text-amber-900">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                <span>
                  <strong>Immutable Versioning Active:</strong> Saving your quantity adjustments will NOT overwrite{' '}
                  <code className="font-mono font-bold">v{selectedVersion.version_number}</code>. It will mint a new immutable{' '}
                  <code className="font-mono font-bold">
                    v{(requestDetail.versions?.length || selectedVersion.version_number) + 1}
                  </code>{' '}
                  with a fresh SHA-256 <code className="font-mono">intent_hash</code> and supersede any prior approval lock.
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setEditedItems(null)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-100"
                >
                  Discard Edits
                </button>
                <button
                  type="button"
                  disabled={isLoading || !isCoordinator}
                  onClick={handleSaveManualRevision}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-amber-700 text-white hover:bg-amber-800 shadow-sm transition"
                >
                  <Layers className="w-3.5 h-3.5" />
                  Save Revision as Immutable Version v
                  {(requestDetail.versions?.length || selectedVersion.version_number) + 1}
                </button>
              </div>
            </div>
          )}

          {/* Conversational AI Revision Bar (v_n -> v_{n+1}) */}
          <form
            onSubmit={handleNaturalLanguageRevision}
            className="p-4 bg-slate-100/70 border-t border-slate-200 flex flex-col sm:flex-row items-stretch sm:items-center gap-3"
          >
            <div className="flex-1 relative">
              <input
                type="text"
                value={revisionPrompt}
                onChange={(e) => setRevisionPrompt(e.target.value)}
                disabled={!isCoordinator || isLoading}
                placeholder={`Ask the AI Agent to revise v${selectedVersion.version_number} (e.g., "Add 2 microfiber whiteboard cleaning kits and increase notebooks to 6")...`}
                className="w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
            </div>
            <button
              type="submit"
              disabled={!isCoordinator || isLoading || !revisionPrompt.trim()}
              className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-slate-800 text-white hover:bg-slate-900 disabled:opacity-40 transition shrink-0"
            >
              <Sparkles className="w-3.5 h-3.5 text-indigo-300" />
              Revise via AI Agent (Mints v
              {(requestDetail.versions?.length || selectedVersion.version_number) + 1})
            </button>
          </form>

          {/* Canonical SHA-256 Intent Hash Preview & Submit for Approval Footer */}
          <div className="p-5 bg-white border-t border-slate-200 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-700">
                  <Hash className="w-3.5 h-3.5 text-indigo-600" />
                  RFC 8785 Canonical SHA-256 <code className="font-mono">intent_hash</code> (v{selectedVersion.version_number}):
                </span>
                <code className="font-mono text-xs bg-slate-100 text-slate-800 px-2.5 py-1 rounded border border-slate-300 select-all">
                  {intentHash}
                </code>
                <button
                  type="button"
                  onClick={() => setShowCanonicalModal(true)}
                  className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 underline"
                >
                  <FileCode2 className="w-3.5 h-3.5" />
                  Inspect Canonical JSON
                </button>
              </div>
              <p className="text-[11px] text-slate-500">
                Any change to SKU, quantity, unit price, merchant, or currency produces a completely different SHA-256 digest.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {selectedVersion.status === 'DRAFT' || selectedVersion.status === 'REJECTED' ? (
                <>
                  <input
                    type="text"
                    value={submissionNote}
                    onChange={(e) => setSubmissionNote(e.target.value)}
                    placeholder="Submission note for Approver Bob..."
                    className="rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-800 w-64"
                  />
                  <button
                    type="button"
                    disabled={!isCoordinator || isLoading || hasUnsavedItemEdits}
                    onClick={() => onSubmitForApproval(versionId, submissionNote)}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 shadow-sm transition"
                  >
                    <Send className="w-4 h-4" />
                    Submit Version v{selectedVersion.version_number} for Approval
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </>
              ) : (
                <div className="flex items-center gap-3">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 px-3 py-2 rounded-lg border border-emerald-200">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    Version v{selectedVersion.version_number} is {selectedVersion.status}
                  </span>
                  <button
                    type="button"
                    onClick={onAdvanceToStep2}
                    className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm transition"
                  >
                    Continue to Step 2 (Review & Lock)
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Canonical RFC 8785 JSON Modal */}
      {showCanonicalModal && selectedVersion && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-2xs p-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-xl max-w-2xl w-full overflow-hidden">
            <div className="px-5 py-4 bg-slate-900 text-white flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileCode2 className="w-4 h-4 text-indigo-400" />
                <h3 className="text-sm font-semibold">
                  RFC 8785 Canonical JSON Snapshot — Version v{selectedVersion.version_number}
                </h3>
              </div>
              <button
                onClick={() => setShowCanonicalModal(false)}
                className="text-xs text-slate-400 hover:text-white"
              >
                Close [ESC]
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase mb-1">
                  Computed 64-Character SHA-256 Digest (intent_hash):
                </div>
                <code className="block font-mono text-xs bg-emerald-50 text-emerald-900 p-2.5 rounded-lg border border-emerald-200 break-all select-all">
                  {intentHash}
                </code>
                <p className="text-[11px] text-slate-600 mt-1.5 leading-relaxed">
                  <strong>Guardrail G-05 (TOCTOU Cryptographic Drift Protection):</strong> Any change to SKUs, quantities, or integer-cent prices alters this 64-character SHA-256 fingerprint and immediately invalidates prior approvals.
                </p>
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase mb-1">
                  Canonical Deterministic Payload (Formatted JSON — Sorted Keys, Integer Cents):
                </div>
                <pre className="font-mono text-xs bg-slate-900 text-slate-100 p-4 rounded-lg overflow-x-auto max-h-60">
                  {typeof selectedVersion.canonical_payload_json === 'string'
                    ? (() => {
                        try {
                          return JSON.stringify(
                            JSON.parse(selectedVersion.canonical_payload_json),
                            null,
                            2
                          );
                        } catch {
                          return selectedVersion.canonical_payload_json;
                        }
                      })()
                    : JSON.stringify(selectedVersion.canonical_payload_json, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase mb-1">
                  Raw RFC 8785 Canonical String (Exact Bytes Hashed via SHA-256):
                </div>
                <code className="block font-mono text-[11px] bg-slate-100 text-slate-800 p-2.5 rounded-lg border border-slate-300 break-all max-h-24 overflow-y-auto select-all">
                  {typeof selectedVersion.canonical_payload_json === 'string'
                    ? selectedVersion.canonical_payload_json
                    : JSON.stringify(selectedVersion.canonical_payload_json)}
                </code>
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => setShowCanonicalModal(false)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold bg-slate-800 text-white hover:bg-slate-900"
                >
                  Close Inspector
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
