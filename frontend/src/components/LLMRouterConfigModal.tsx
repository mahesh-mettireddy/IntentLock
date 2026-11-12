import React, { useEffect, useState } from 'react';
import {
  Cpu,
  KeyRound,
  CreditCard,
  CheckCircle2,
  AlertCircle,
  X,
  RefreshCw,
  ArrowRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import {
  FailoverDrillResponse,
  LLMProviderStatus,
  LLMStatusResponse,
  UpdateKeysPayload,
} from '../types/intentlock';
import { apiClient } from '../api/client';

interface LLMRouterConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  llmStatus: LLMStatusResponse | null;
  onUpdateKeys: (payload: UpdateKeysPayload) => Promise<void>;
  onRefreshStatus: () => Promise<void>;
}

const DEFAULT_CHAIN: LLMProviderStatus[] = [
  {
    priority: 1,
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    configured: true,
    circuit_state: 'CLOSED',
    last_latency_ms: 540,
  },
  {
    priority: 2,
    provider: 'groq',
    model: 'llama-3.3-70b-versatile',
    configured: true,
    circuit_state: 'CLOSED',
    last_latency_ms: null,
  },
  {
    priority: 3,
    provider: 'xai',
    model: 'grok-2-latest',
    configured: false,
    circuit_state: 'CLOSED',
    last_latency_ms: null,
  },
  {
    priority: 4,
    provider: 'openrouter',
    model: 'openai/gpt-4o-mini',
    configured: true,
    circuit_state: 'CLOSED',
    last_latency_ms: null,
  },
  {
    priority: 5,
    provider: 'deterministic_fallback',
    model: 'intentlock-rule-synthesizer-v1',
    configured: true,
    circuit_state: 'ALWAYS_READY',
    last_latency_ms: 4,
  },
];

export const LLMRouterConfigModal: React.FC<LLMRouterConfigModalProps> = ({
  isOpen,
  onClose,
  llmStatus,
  onUpdateKeys,
  onRefreshStatus,
}) => {
  const [geminiKey, setGeminiKey] = useState('');
  const [groqKey, setGroqKey] = useState('');
  const [xaiKey, setXaiKey] = useState('');
  const [openrouterKey, setOpenrouterKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [paypalClientId, setPaypalClientId] = useState('');
  const [paypalClientSecret, setPaypalClientSecret] = useState('');
  const [simulateFailover, setSimulateFailover] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  const [isRunningDrill, setIsRunningDrill] = useState(false);
  const [drillResult, setDrillResult] = useState<FailoverDrillResponse | null>(null);

  useEffect(() => {
    if (llmStatus?.simulate_primary_failure !== undefined) {
      setSimulateFailover(Boolean(llmStatus.simulate_primary_failure));
    }
  }, [llmStatus?.simulate_primary_failure]);

  if (!isOpen) return null;

  const handleRunDrill = async () => {
    setIsRunningDrill(true);
    try {
      const res = await apiClient.runFailoverDrill();
      setDrillResult(res);
      await onRefreshStatus();
    } finally {
      setIsRunningDrill(false);
    }
  };

  const chain =
    llmStatus?.failover_chain ||
    llmStatus?.providers ||
    llmStatus?.llm_providers ||
    DEFAULT_CHAIN;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSavedNotice(null);
    try {
      const payload: UpdateKeysPayload = {
        simulate_primary_failure: simulateFailover,
      };
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
      if (groqKey.trim()) payload.groq_api_key = groqKey.trim();
      if (xaiKey.trim()) payload.xai_api_key = xaiKey.trim();
      if (openrouterKey.trim()) payload.openrouter_api_key = openrouterKey.trim();
      if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();
      if (paypalClientId.trim()) payload.paypal_client_id = paypalClientId.trim();
      if (paypalClientSecret.trim())
        payload.paypal_client_secret = paypalClientSecret.trim();

      await onUpdateKeys(payload);
      setSavedNotice(
        'Runtime API keys & failover settings updated in backend memory.'
      );
      setGeminiKey('');
      setGroqKey('');
      setXaiKey('');
      setOpenrouterKey('');
      setOpenaiKey('');
      setPaypalClientSecret('');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-2xs p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-4xl w-full overflow-hidden my-8">
        {/* Header */}
        <div className="px-6 py-4 bg-slate-900 text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-indigo-500/20 border border-indigo-400/30 flex items-center justify-center">
              <Cpu className="w-5 h-5 text-indigo-300" />
            </div>
            <div>
              <h3 className="text-sm font-bold">
                Multi-LLM Automatic Failover Router & PayPal Sandbox Configuration
              </h3>
              <p className="text-xs text-slate-300">
                Inspect circuit-breaker health or paste runtime API keys (Google Gemini → Groq Cloud → xAI Grok → OpenRouter / OpenAI) & PayPal Sandbox credentials.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6 max-h-[82vh] overflow-y-auto">
          {/* Failover Chain Visual Status */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Ordered Multi-LLM Failover Chain & Circuit Breakers
              </h4>
              <button
                type="button"
                onClick={onRefreshStatus}
                className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Refresh Status
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
              {chain.map((item, idx) => {
                const isActive =
                  llmStatus?.active_provider?.toLowerCase() ===
                  item.provider.toLowerCase();
                return (
                  <div
                    key={item.provider}
                    className={`rounded-xl border p-3 flex flex-col justify-between gap-2 relative ${
                      isActive
                        ? 'bg-indigo-50/70 border-indigo-400 ring-2 ring-indigo-500/15'
                        : 'bg-slate-50 border-slate-200'
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-200 text-slate-800">
                          Tier {item.priority || idx + 1}
                        </span>
                        <span
                          className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            item.circuit_state === 'OPEN'
                              ? 'bg-rose-100 text-rose-800'
                              : 'bg-emerald-100 text-emerald-800'
                          }`}
                        >
                          {item.circuit_state}
                        </span>
                      </div>
                      <div className="font-bold text-xs text-slate-900 capitalize mt-1">
                        {item.provider.replace('_', ' ')}
                      </div>
                      <div className="font-mono text-[10px] text-slate-500 truncate">
                        {item.model}
                      </div>
                    </div>

                    <div className="pt-2 border-t border-slate-200/80 flex items-center justify-between text-[10px] font-mono">
                      <span
                        className={
                          item.configured ? 'text-emerald-700 font-semibold' : 'text-amber-700'
                        }
                      >
                        {item.configured ? '✓ Ready' : '○ Key Optional'}
                      </span>
                      {item.last_latency_ms !== null && item.last_latency_ms !== undefined && (
                        <span className="text-slate-500">{item.last_latency_ms}ms</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Runtime Key Configuration Form */}
          <form onSubmit={handleSave} className="space-y-5 border-t border-slate-200 pt-5">
            {savedNotice && (
              <div className="rounded-lg bg-emerald-50 border border-emerald-300 p-3 flex items-center gap-2 text-xs font-semibold text-emerald-900">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{savedNotice}</span>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* LLM Provider Keys */}
              <div className="space-y-3 bg-slate-50 p-4 rounded-xl border border-slate-200">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
                  <KeyRound className="w-4 h-4 text-indigo-600" />
                  <span>Runtime LLM Provider API Keys (Optional Override)</span>
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                    Tier 1: Google Gemini API Key (GEMINI_API_KEY)
                  </label>
                  <input
                    type="password"
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                    placeholder="AIzaSy... (Leave blank to keep existing key)"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                    Tier 2: Groq Cloud API Key (GROQ_API_KEY)
                  </label>
                  <input
                    type="password"
                    value={groqKey}
                    onChange={(e) => setGroqKey(e.target.value)}
                    placeholder="gsk_... (Fast Llama-3.3-70B failover)"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                    Tier 3: xAI Grok API Key (XAI_API_KEY)
                  </label>
                  <input
                    type="password"
                    value={xaiKey}
                    onChange={(e) => setXaiKey(e.target.value)}
                    placeholder="xai-... (Optional)"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                    Tier 4: OpenRouter / OpenAI API Key
                  </label>
                  <input
                    type="password"
                    value={openrouterKey}
                    onChange={(e) => setOpenrouterKey(e.target.value)}
                    placeholder="sk-or-v1-... or sk-..."
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono"
                  />
                </div>
              </div>

              {/* PayPal Sandbox & Failover Simulation */}
              <div className="space-y-4 bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between">
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
                    <CreditCard className="w-4 h-4 text-blue-600" />
                    <span>PayPal Sandbox Orders v2 / MCP Credentials</span>
                  </div>

                  <p className="text-[11px] text-slate-600 leading-relaxed">
                    Connected Merchant: <strong>Acme Workspace Supplies (MERCH-ACME-001)</strong> · Currency Lock: <strong>USD</strong>.
                  </p>

                  <div>
                    <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                      PayPal Sandbox Client ID (PAYPAL_CLIENT_ID)
                    </label>
                    <input
                      type="text"
                      value={paypalClientId}
                      onChange={(e) => setPaypalClientId(e.target.value)}
                      placeholder="Paste Sandbox Client ID to enable live REST / JS SDK..."
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                      PayPal Sandbox Client Secret (PAYPAL_CLIENT_SECRET)
                    </label>
                    <input
                      type="password"
                      value={paypalClientSecret}
                      onChange={(e) => setPaypalClientSecret(e.target.value)}
                      placeholder="Paste Sandbox Secret..."
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono"
                    />
                  </div>
                </div>

                {/* Simulate Primary Provider 429 Toggle & Live Failover Drill */}
                <div className="p-3 rounded-lg bg-amber-50 border border-amber-300 space-y-2">
                  <label className="flex items-center gap-2 text-xs font-bold text-amber-950 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={simulateFailover}
                      onChange={(e) => setSimulateFailover(e.target.checked)}
                      className="rounded border-amber-400 text-indigo-600 focus:ring-indigo-500"
                    />
                    <span>Simulate Tier-1 HTTP 429 Rate Limit (Test Auto-Failover)</span>
                  </label>
                  <p className="text-[11px] text-amber-800">
                    Forces Tier 1 (Google Gemini) to simulate HTTP 429 quota exhaustion and automatically route to Tier 2/3.
                  </p>
                  <button
                    type="button"
                    disabled={isRunningDrill}
                    onClick={handleRunDrill}
                    className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-900 text-white hover:bg-amber-950 disabled:opacity-50 transition"
                  >
                    <Zap className="w-3.5 h-3.5 text-amber-300" />
                    {isRunningDrill
                      ? 'Executing HTTP 429 Failover Drill...'
                      : 'Run Live HTTP 429 Failover Drill'}
                  </button>
                  {drillResult && (
                    <div className="p-2.5 rounded-lg bg-white border border-amber-300 text-[11px] font-mono space-y-1 text-slate-800">
                      <div className="font-bold text-emerald-700">
                        ✓ {drillResult.drill_status} ({drillResult.latency_ms}ms)
                      </div>
                      <div className="text-rose-700">
                        1. {drillResult.simulated_primary_error}
                      </div>
                      <div className="text-indigo-800 font-semibold">
                        2. Fulfilled by: {drillResult.fulfilled_by_provider} ({drillResult.fulfilled_by_model}) · Total ${drillResult.total_amount_usd} USD
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <ShieldCheck className="w-4 h-4 text-emerald-600" />
                <span>
                  Keys are held only in local server memory for this session and never logged.
                </span>
              </div>
              <div className="flex items-center gap-2.5">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-lg text-xs font-semibold border border-slate-300 text-slate-700 hover:bg-slate-100"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm transition"
                >
                  {isSaving ? 'Applying...' : 'Apply Runtime Configuration'}
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
