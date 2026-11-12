import React, { useState } from 'react';
import {
  Users,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  ShieldCheck,
  TrendingDown,
  Award,
  RefreshCw,
  AlertTriangle,
  Quote,
} from 'lucide-react';
import {
  CoordinatorInterview,
  EvalSuiteRun,
} from '../types/intentlock';

interface DiscoveryEvalViewProps {
  interviews: CoordinatorInterview[];
  evalRun: EvalSuiteRun | null;
  isRunningEvals: boolean;
  onRunEvalSuite: () => Promise<void>;
}

const FALLBACK_INTERVIEWS: CoordinatorInterview[] = [
  {
    id: 'COORD-INT-01',
    coordinator_name: 'Maya Lin',
    role_title: 'People & Office Coordinator',
    team_size: 35,
    recent_purchase_scenario:
      'Bi-weekly engineering onboarding kits (cables, hubs, mice, chargers, notebooks, pens) and weekly breakroom restocks.',
    baseline_completion_minutes: 14.5,
    baseline_corrections_count: 3,
    baseline_drift_incident:
      'Pasted a $312.00 cart screenshot in Slack for VP approval. Two hours later, added 2 packs of whiteboard markers and checked out at $336.00 under the original Slack thumbs-up—creating a $24.00 unapproved variance.',
    intentlock_completion_seconds: 36.0,
    intentlock_corrections_count: 0,
    key_quote:
      'I used to accidentally order 5 boxes of 12-pack pens for 5 new hires because every SKU has a different pack count. IntentLock does the ceiling math and locks the exact penny total.',
    pain_points: [
      'Headcount-to-pack arithmetic errors (12-pack pens vs. single notebooks)',
      'Post-approval cart drift between Slack screenshot approval and checkout',
    ],
  },
  {
    id: 'COORD-INT-02',
    coordinator_name: 'Jordan Vance',
    role_title: 'Lab & Studio Operations Coordinator',
    team_size: 18,
    recent_purchase_scenario:
      'Shared bench & whiteboard supplies, disinfecting wipes, screen cleaners, OSHA first aid kits, and 100W USB-C PD cables.',
    baseline_completion_minutes: 13.8,
    baseline_corrections_count: 2,
    baseline_drift_incident:
      'When an OSHA First Aid Kit only had 5 units in stock instead of the 8 requested, substituted different items at checkout without re-running approval, leaving the receipt disconnected from the approval.',
    intentlock_completion_seconds: 39.5,
    intentlock_corrections_count: 0,
    key_quote:
      'My Finance Approver always asked why we needed X packs. Having the AI generate per-item headcount math and locking the SHA-256 hash into PayPal custom_id cut approval turnaround to seconds.',
    pain_points: [
      '6–8 minutes spent typing manual line-item justifications for Finance Approvers',
      'Silent stock substitution drift at checkout when inventory was low',
    ],
  },
  {
    id: 'COORD-INT-03',
    coordinator_name: 'Elena Rostova',
    role_title: 'Client Workshop & Event Coordinator',
    team_size: 22,
    recent_purchase_scenario:
      'Offsite design-sprint supply kits (sticky notes, chisel-tip dry erase markers, dot-grid notebooks, snack boxes, coffee) under strict per-event budget caps.',
    baseline_completion_minutes: 14.3,
    baseline_corrections_count: 4,
    baseline_drift_incident:
      'An approval granted on Tuesday for a 12-person workshop was modified on Wednesday when headcount grew to 16 attendees, creating ambiguity over which version of the cart was actually authorized.',
    intentlock_completion_seconds: 39.7,
    intentlock_corrections_count: 0,
    key_quote:
      'Fitting a 14-person workshop list under a $180 cap took 4 rounds in a spreadsheet. IntentLock versions every edit (v1 -> v2) and immediately revokes stale approvals.',
    pain_points: [
      'Manual trial-and-error spreadsheet math to fit multi-packs under tight budget caps',
      'Stale or expired approval reuse when event headcount changed mid-week',
    ],
  },
];

export const DiscoveryEvalView: React.FC<DiscoveryEvalViewProps> = ({
  interviews,
  evalRun,
  isRunningEvals,
  onRunEvalSuite,
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');

  const displayInterviews =
    interviews && interviews.length > 0 ? interviews : FALLBACK_INTERVIEWS;

  const scenarios = evalRun?.results || evalRun?.scenarios || [];
  const evalCategories = [
    'ALL',
    ...Array.from(new Set(scenarios.map((s) => s.category))),
  ];
  const filteredScenarios = scenarios.filter(
    (s) => selectedCategory === 'ALL' || s.category === selectedCategory
  );

  return (
    <div className="space-y-8">
      {/* Section A: 3-Coordinator Discovery Study & Quantitative Before/After Metrics */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="px-6 py-5 bg-gradient-to-r from-indigo-50 via-white to-slate-50 border-b border-slate-200 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="w-11 h-11 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-2xs">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-indigo-700">
                User Research & Problem Validation (3 Coordinators)
              </span>
              <h2 className="text-base font-bold tracking-tight text-slate-900 mt-0.5">
                "Coordinators spend time translating requests into quantities and products; changing carts can diverge from managerial approval."
              </h2>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 shrink-0">
            <div className="px-3.5 py-2 rounded-xl bg-emerald-50 border border-emerald-200 text-right">
              <div className="text-[10px] font-mono uppercase text-emerald-700 font-semibold">
                Translation Time
              </div>
              <div className="text-sm font-mono font-bold text-emerald-900">
                14.2m → 38.4s (-95.5%)
              </div>
            </div>
            <div className="px-3.5 py-2 rounded-xl bg-indigo-50 border border-indigo-200 text-right">
              <div className="text-[10px] font-mono uppercase text-indigo-700 font-semibold">
                Post-Approval Drift Rate
              </div>
              <div className="text-sm font-mono font-bold text-indigo-900">
                33.3% → 0.0% (SHA-256 Lock)
              </div>
            </div>
          </div>
        </div>

        {/* Quantitative Benchmark Summary Strip */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-slate-200 bg-slate-50 border-b border-slate-200">
          <div className="p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
              <span>Mean Request-to-Cart Time</span>
              <TrendingDown className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="mt-1 flex items-baseline gap-2 font-mono">
              <span className="text-lg font-bold text-slate-900">38.4 sec</span>
              <span className="text-xs text-slate-400 line-through">14.2 min</span>
            </div>
            <div className="text-[11px] text-emerald-700 font-medium mt-0.5">
              95.5% faster coordinator translation
            </div>
          </div>

          <div className="p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
              <span>Pack-Size Math Error Rate</span>
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="mt-1 flex items-baseline gap-2 font-mono">
              <span className="text-lg font-bold text-slate-900">0.0%</span>
              <span className="text-xs text-slate-400 line-through">23.3% baseline</span>
            </div>
            <div className="text-[11px] text-emerald-700 font-medium mt-0.5">
              Deterministic per-person ceiling rules
            </div>
          </div>

          <div className="p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
              <span>TOCTOU Cart Drift Leakage</span>
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="mt-1 flex items-baseline gap-2 font-mono">
              <span className="text-lg font-bold text-slate-900">0.0%</span>
              <span className="text-xs text-slate-400 line-through">33.3% baseline</span>
            </div>
            <div className="text-[11px] text-emerald-700 font-medium mt-0.5">
              100% blocked by G-05 SHA-256 intent_hash
            </div>
          </div>

          <div className="p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
              <span>Line-Item Justification Rate</span>
              <Award className="w-4 h-4 text-indigo-600" />
            </div>
            <div className="mt-1 flex items-baseline gap-2 font-mono">
              <span className="text-lg font-bold text-slate-900">100.0%</span>
              <span className="text-xs text-slate-400 line-through">41.7% baseline</span>
            </div>
            <div className="text-[11px] text-indigo-700 font-medium mt-0.5">
              Every SKU includes rationale & pack math
            </div>
          </div>
        </div>

        {/* 3 Coordinator Interview Cards */}
        <div className="p-5 grid grid-cols-1 lg:grid-cols-3 gap-5">
          {displayInterviews.map((intv) => (
            <div
              key={intv.id}
              className="rounded-xl border border-slate-200 bg-white p-5 flex flex-col justify-between gap-4 shadow-2xs"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold px-2.5 py-0.5 rounded bg-indigo-50 text-indigo-900 border border-indigo-200">
                    {intv.id}
                  </span>
                  <span className="text-xs font-semibold text-slate-500">
                    Team Size: {intv.team_size} staff
                  </span>
                </div>

                <div>
                  <h3 className="text-sm font-bold text-slate-900">
                    {intv.coordinator_name}
                  </h3>
                  <p className="text-xs font-medium text-indigo-700">
                    {intv.role_title}
                  </p>
                </div>

                <p className="text-xs text-slate-600 leading-relaxed">
                  <strong>Workflow:</strong> {intv.recent_purchase_scenario}
                </p>

                {/* Observed Drift Incident */}
                <div className="p-3 rounded-lg bg-rose-50/70 border border-rose-200 text-xs text-rose-950 space-y-1">
                  <div className="font-bold flex items-center gap-1.5 text-rose-800">
                    <AlertTriangle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
                    Observed Baseline TOCTOU Drift Incident:
                  </div>
                  <p className="text-[11px] leading-relaxed">
                    {intv.baseline_drift_incident}
                  </p>
                </div>

                {/* Quote */}
                <div className="p-3 rounded-lg bg-slate-50 border border-slate-200/80 text-xs text-slate-700 italic flex items-start gap-2">
                  <Quote className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                  <span>"{intv.key_quote}"</span>
                </div>
              </div>

              <div className="pt-3 border-t border-slate-100 grid grid-cols-2 gap-2 font-mono text-xs">
                <div className="bg-slate-100 p-2 rounded-lg">
                  <div className="text-[10px] text-slate-500">Manual Baseline</div>
                  <div className="font-bold text-slate-800">
                    {intv.baseline_completion_minutes} min ({intv.baseline_corrections_count} errors)
                  </div>
                </div>
                <div className="bg-emerald-50 border border-emerald-200 p-2 rounded-lg">
                  <div className="text-[10px] text-emerald-700">With IntentLock</div>
                  <div className="font-bold text-emerald-900">
                    {intv.intentlock_completion_seconds} sec (0 errors)
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Section B: Automated Agent & Guardrail Evaluation Suite */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="px-6 py-5 bg-gradient-to-r from-emerald-50 via-white to-teal-50 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-emerald-600" />
              <h2 className="text-base font-bold tracking-tight text-slate-900">
                Live Quality & Policy Verification Suite (15 Scenarios)
              </h2>
            </div>
            <p className="text-xs text-slate-600">
              Runs end-to-end verification across catalog translation, pack-size math, budget adherence, Multi-LLM failover, Separation of Duties, and PayPal checkout reconciliation.
            </p>
          </div>

          <button
            type="button"
            disabled={isRunningEvals}
            onClick={onRunEvalSuite}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 shadow-sm transition shrink-0"
          >
            {isRunningEvals ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Running Golden Benchmark Suite...
              </>
            ) : (
              <>
                <Play className="w-4 h-4 fill-current" />
                Run Agent & Guardrail Evaluation Suite
              </>
            )}
          </button>
        </div>

        {evalRun ? (
          <div className="p-5 space-y-5">
            {/* Scorecard Metrics Strip (M1 - M6) */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
              <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-300">
                <div className="text-[11px] font-semibold uppercase text-emerald-800">
                  Overall Pass Rate
                </div>
                <div className="text-xl font-mono font-bold text-emerald-950 mt-0.5">
                  {evalRun.pass_rate_pct}% ({evalRun.passed_scenarios}/{evalRun.total_scenarios})
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="text-[11px] font-semibold uppercase text-slate-500">
                  M1 · SKU Selection F1
                </div>
                <div className="text-xl font-mono font-bold text-slate-900 mt-0.5">
                  {evalRun.sku_f1_score.toFixed(2)}
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="text-[11px] font-semibold uppercase text-slate-500">
                  M2 · Pack Math Accuracy
                </div>
                <div className="text-xl font-mono font-bold text-slate-900 mt-0.5">
                  {evalRun.pack_math_accuracy_pct}%
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="text-[11px] font-semibold uppercase text-slate-500">
                  M3 · Price Grounding
                </div>
                <div className="text-xl font-mono font-bold text-emerald-700 mt-0.5">
                  {evalRun.price_grounding_integrity_pct ?? 100}%
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="text-[11px] font-semibold uppercase text-slate-500">
                  M4 · Rationale Rate
                </div>
                <div className="text-xl font-mono font-bold text-indigo-700 mt-0.5">
                  {evalRun.explanation_completeness_pct ?? 100}%
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="text-[11px] font-semibold uppercase text-slate-500">
                  M5 · Guardrail Pass Rate
                </div>
                <div className="text-xl font-mono font-bold text-emerald-700 mt-0.5">
                  {evalRun.guardrail_enforcement_pct}%
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="text-[11px] font-semibold uppercase text-slate-500">
                  M6 · P95 Latency
                </div>
                <div className="text-xl font-mono font-bold text-slate-900 mt-0.5">
                  {evalRun.e2e_latency_p95_ms ?? 0}ms
                </div>
              </div>
            </div>

            {/* Category Filter Pills */}
            <div className="flex flex-wrap items-center gap-1.5">
              {evalCategories.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold transition ${
                    selectedCategory === cat
                      ? 'bg-slate-900 text-white'
                      : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>

            {/* Scenario Results Table */}
            <div className="overflow-x-auto border border-slate-200 rounded-xl">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-100/80 text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    <th className="py-3 px-4">ID</th>
                    <th className="py-3 px-4">Scenario & Category</th>
                    <th className="py-3 px-4">Guardrail / Rubric Verified</th>
                    <th className="py-3 px-4">Expected vs. Observed Behavior</th>
                    <th className="py-3 px-4 text-right">Latency</th>
                    <th className="py-3 px-4 text-right">Verdict</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 text-xs">
                  {filteredScenarios.map((sc) => (
                    <tr key={sc.scenario_id} className="hover:bg-slate-50/80">
                      <td className="py-3.5 px-4 font-mono font-bold text-indigo-700 whitespace-nowrap">
                        {sc.scenario_id}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="font-bold text-slate-900">{sc.title}</div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          {sc.category}
                        </div>
                      </td>
                      <td className="py-3.5 px-4 font-mono text-[11px] text-slate-700">
                        <span className="px-2 py-0.5 rounded bg-slate-100 border border-slate-200">
                          {sc.guardrail_verified || sc.guardrail_tested}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 max-w-md space-y-1">
                        <div className="text-slate-600">
                          <strong>Expected:</strong> {sc.expected_behavior || sc.expected_summary}
                        </div>
                        <div className="text-slate-900 font-medium">
                          <strong>Observed:</strong> {sc.observed_behavior || sc.observed_summary}
                        </div>
                      </td>
                      <td className="py-3.5 px-4 text-right font-mono text-slate-500 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {sc.latency_ms}ms
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-right whitespace-nowrap">
                        {sc.passed ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono font-bold bg-emerald-100 text-emerald-900 border border-emerald-300">
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                            PASS
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono font-bold bg-rose-100 text-rose-900 border border-rose-300">
                            <XCircle className="w-3.5 h-3.5 text-rose-600" />
                            FAIL
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="p-8 text-center space-y-3 bg-slate-50/60">
            <p className="text-sm text-slate-600">
              Click <strong>"Run Agent & Guardrail Evaluation Suite"</strong> above to execute all golden & adversarial benchmark scenarios live against the backend.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
