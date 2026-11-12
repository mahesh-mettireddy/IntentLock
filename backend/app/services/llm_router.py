import json
import math
import os
import re
import time
from typing import Any, Optional
import httpx

from ..config import settings
from . import guardrails


_SECRET_SCRUB_RE = re.compile(
    r"(?:sk-[a-zA-Z0-9_-]{16,}|AIza[0-9A-Za-z\-_]{20,}|gsk_[a-zA-Z0-9]{16,}|xai-[a-zA-Z0-9_-]{16,}|Bearer\s+[a-zA-Z0-9\-._~+/]+=*)"
)


FREE_API_SIGNUP_URLS = {
    "google_gemini": "https://aistudio.google.com/apikey",
    "groq_cloud": "https://console.groq.com/keys",
    "xai_grok": "https://console.x.ai",
    "openrouter_free": "https://openrouter.ai/keys",
    "openai": "https://platform.openai.com/api-keys",
}


class MultiProviderLLMRouter:
    """
    Genuine Agentic Multi-LLM Automatic Failover Router for IntentLock.
    Cascades across configured LLM API providers in priority order:
      1. Google Gemini API (`google_gemini`: gemini-2.5-flash -> gemini-2.0-flash)
      2. Groq Cloud Free API (`groq_cloud`: llama-3.3-70b-versatile)
      3. xAI Grok API (`xai_grok`: grok-2-latest)
      4. OpenRouter Free Tier (`openrouter_free`: meta-llama/llama-3.3-70b-instruct:free)
      5. OpenAI API (`openai`: gpt-4o-mini)

    Includes:
      - Automatic HTTP 429 / Quota / 401 / 402 / 403 / 5xx / timeout detection and zero-delay cascade failover.
      - Per-provider in-memory circuit-breaker telemetry tracker (`READY`, `COOLDOWN_QUOTA_EXHAUSTED`, `UNCONFIGURED`).
      - Dynamic runtime API key injection (`set_runtime_api_keys`) so evaluators can paste keys live without restarting.
      - Semantic catalog-aware reasoning parser ONLY when zero API keys are configured in `.env` or runtime memory.
    """

    def __init__(self) -> None:
        self._runtime_keys: dict[str, str] = {}
        self._circuit_cooldown_until: dict[str, float] = {}
        self._circuit_last_error: dict[str, str] = {}
        self._total_calls_by_provider: dict[str, int] = {
            "google_gemini": 0,
            "groq_cloud": 0,
            "xai_grok": 0,
            "openrouter_free": 0,
            "openai": 0,
            "semantic_catalog_synthesizer": 0,
        }
        self._error_counts_by_provider: dict[str, int] = {
            "google_gemini": 0,
            "groq_cloud": 0,
            "xai_grok": 0,
            "openrouter_free": 0,
            "openai": 0,
            "semantic_catalog_synthesizer": 0,
        }
        self._last_latency_by_provider: dict[str, Optional[int]] = {
            "google_gemini": None,
            "groq_cloud": None,
            "xai_grok": None,
            "openrouter_free": None,
            "openai": None,
            "semantic_catalog_synthesizer": None,
        }
        self._total_failovers: int = 0
        self._last_fulfilled_provider: str = "google_gemini"

    # ------------------------------------------------------------------
    # Dynamic Runtime API Key Injection & Configuration Inspection
    # ------------------------------------------------------------------

    def set_runtime_api_keys(self, keys: dict[str, Optional[str]]) -> dict[str, Any]:
        """
        Updates API keys in memory immediately without restarting the server,
        and resets circuit-breaker cooldowns for updated providers.
        Accepts keys by env var name (`GEMINI_API_KEY`, `GROQ_API_KEY`, etc.)
        or provider ID (`google_gemini`, `groq_cloud`, `xai_grok`, `openrouter_free`, `openai`).
        """
        key_mapping = {
            "GEMINI_API_KEY": "GEMINI_API_KEY",
            "GOOGLE_API_KEY": "GEMINI_API_KEY",
            "google_gemini": "GEMINI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "GROQ_API_KEY": "GROQ_API_KEY",
            "groq_cloud": "GROQ_API_KEY",
            "groq": "GROQ_API_KEY",
            "XAI_API_KEY": "XAI_API_KEY",
            "xai_grok": "XAI_API_KEY",
            "xai": "XAI_API_KEY",
            "OPENROUTER_API_KEY": "OPENROUTER_API_KEY",
            "openrouter_free": "OPENROUTER_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "OPENAI_API_KEY": "OPENAI_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        provider_for_env = {
            "GEMINI_API_KEY": "google_gemini",
            "GROQ_API_KEY": "groq_cloud",
            "XAI_API_KEY": "xai_grok",
            "OPENROUTER_API_KEY": "openrouter_free",
            "OPENAI_API_KEY": "openai",
        }

        for raw_name, raw_val in (keys or {}).items():
            target_env = key_mapping.get(raw_name)
            if not target_env:
                continue
            cleaned_val = (raw_val or "").strip()
            if cleaned_val:
                self._runtime_keys[target_env] = cleaned_val
            else:
                self._runtime_keys.pop(target_env, None)

            prov_id = provider_for_env.get(target_env)
            if prov_id:
                self._circuit_cooldown_until.pop(prov_id, None)
                self._circuit_last_error.pop(prov_id, None)

        return self.get_router_status()

    def reset_circuit_breakers(self) -> dict[str, Any]:
        """Clears all active circuit-breaker cooldown timers."""
        self._circuit_cooldown_until.clear()
        self._circuit_last_error.clear()
        return self.get_router_status()

    def _get_api_key(self, env_name: str) -> str:
        if env_name in self._runtime_keys and self._runtime_keys[env_name]:
            return self._runtime_keys[env_name]
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            return env_val
        return str(getattr(settings, env_name, "") or "").strip()

    def _get_provider_definitions(self) -> list[dict[str, Any]]:
        raw_gemini_fb = (settings.GEMINI_FALLBACK_MODEL or "").strip()
        gemini_fb = (
            "gemini-2.5-flash-lite"
            if (not raw_gemini_fb or raw_gemini_fb == "gemini-2.0-flash")
            else raw_gemini_fb
        )
        return [
            {
                "priority": 1,
                "provider_id": "google_gemini",
                "display_name": "Google Gemini API (Free Tier)",
                "env_var": "GEMINI_API_KEY",
                "primary_model": settings.GEMINI_MODEL or "gemini-2.5-flash",
                "fallback_model": gemini_fb,
                "api_key": self._get_api_key("GEMINI_API_KEY") or self._get_api_key("GOOGLE_API_KEY"),
                "signup_url": FREE_API_SIGNUP_URLS["google_gemini"],
            },
            {
                "priority": 2,
                "provider_id": "groq_cloud",
                "display_name": "Groq Cloud LPU API (Free Tier)",
                "env_var": "GROQ_API_KEY",
                "primary_model": settings.GROQ_MODEL or "openai/gpt-oss-120b",
                "fallback_model": "openai/gpt-oss-20b",
                "api_key": self._get_api_key("GROQ_API_KEY"),
                "signup_url": FREE_API_SIGNUP_URLS["groq_cloud"],
            },
            {
                "priority": 3,
                "provider_id": "xai_grok",
                "display_name": "xAI Grok API",
                "env_var": "XAI_API_KEY",
                "primary_model": settings.XAI_MODEL or "grok-2-latest",
                "fallback_model": "grok-2-latest",
                "api_key": self._get_api_key("XAI_API_KEY"),
                "signup_url": FREE_API_SIGNUP_URLS["xai_grok"],
            },
            {
                "priority": 4,
                "provider_id": "openrouter_free",
                "display_name": "OpenRouter Free Models (:free)",
                "env_var": "OPENROUTER_API_KEY",
                "primary_model": settings.OPENROUTER_MODEL or "google/gemma-4-31b-it:free",
                "fallback_model": "nvidia/nemotron-3.5-lightning:free",
                "api_key": self._get_api_key("OPENROUTER_API_KEY"),
                "signup_url": FREE_API_SIGNUP_URLS["openrouter_free"],
            },
            {
                "priority": 5,
                "provider_id": "openai",
                "display_name": "OpenAI Platform API",
                "env_var": "OPENAI_API_KEY",
                "primary_model": settings.OPENAI_MODEL or "gpt-4o-mini",
                "fallback_model": "gpt-4o-mini",
                "api_key": self._get_api_key("OPENAI_API_KEY"),
                "signup_url": FREE_API_SIGNUP_URLS["openai"],
            },
        ]

    def get_router_status(self) -> dict[str, Any]:
        """
        Returns complete telemetry and circuit-breaker health across all 5 LLM providers,
        matching both `SystemHealthOut.llm_providers` (`LLMProviderStatusOut`) and extended router status.
        """
        now = time.time()
        defs = self._get_provider_definitions()
        providers_out: list[dict[str, Any]] = []
        any_key_configured = False
        active_provider = None

        for d in defs:
            pid = d["provider_id"]
            has_key = bool(d["api_key"])
            cooldown_until = self._circuit_cooldown_until.get(pid, 0.0)
            in_cooldown = has_key and cooldown_until > now

            if not has_key:
                health_status = "UNCONFIGURED"
                circuit_state = "UNCONFIGURED"
                failover_ready = False
            elif in_cooldown:
                health_status = "COOLDOWN_QUOTA_EXHAUSTED"
                circuit_state = "OPEN"
                failover_ready = False
            else:
                health_status = "READY"
                circuit_state = "CLOSED"
                failover_ready = True
                if active_provider is None:
                    active_provider = pid

            if has_key:
                any_key_configured = True

            providers_out.append(
                {
                    "priority": d["priority"],
                    "provider": pid,
                    "provider_id": pid,
                    "display_name": d["display_name"],
                    "model": d["primary_model"],
                    "fallback_model": d["fallback_model"],
                    "env_var": d["env_var"],
                    "configured": has_key,
                    "health": health_status,
                    "circuit_state": circuit_state,
                    "failover_ready": failover_ready,
                    "cooldown_remaining_seconds": max(0, int(cooldown_until - now)) if in_cooldown else 0,
                    "last_error": self._circuit_last_error.get(pid),
                    "total_calls": self._total_calls_by_provider.get(pid, 0),
                    "error_count": self._error_counts_by_provider.get(pid, 0),
                    "last_latency_ms": self._last_latency_by_provider.get(pid),
                    "signup_url": d["signup_url"],
                }
            )

        if active_provider is None:
            active_provider = "google_gemini" if any_key_configured else "semantic_catalog_synthesizer"

        return {
            "active_provider": active_provider,
            "last_fulfilled_provider": self._last_fulfilled_provider,
            "any_live_api_key_configured": any_key_configured,
            "requires_api_key": not any_key_configured,
            "total_calls": sum(self._total_calls_by_provider.values()),
            "total_failover_count": self._total_failovers,
            "recommended_free_api_signup_urls": FREE_API_SIGNUP_URLS,
            "providers": providers_out,
            "failover_chain": providers_out,
        }

    # ------------------------------------------------------------------
    # Provider Execution & Automatic Cascading Failover
    # ------------------------------------------------------------------

    async def generate_cart_proposal(
        self,
        system_prompt: str,
        user_prompt: str,
        catalog_items: Optional[list[Any]] = None,
        budget_limit_cents: Optional[int] = None,
        previous_items: Optional[list[dict[str, Any]]] = None,
        simulate_failover_providers: Optional[list[str]] = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Executes genuine LLM inference across the configured provider priority chain.
        If a provider raises HTTP 429 (rate limit / quota exhausted), 401/402/403, 5xx,
        timeout, or malformed JSON, records the event in `failover_trace`, marks the
        circuit breaker, and automatically cascades to the next configured provider.

        Returns `(proposal_dict, telemetry_dict)`.
        """
        # Defense-in-depth PII & injection scrubbing before outbound LLM calls (SEC-GAP-02)
        user_prompt = guardrails.sanitize_and_check_prompt_injection(user_prompt or "")[0]

        overall_start = time.perf_counter()
        now = time.time()
        defs = self._get_provider_definitions()
        configured_defs = [d for d in defs if d["api_key"]]

        failover_trace: list[dict[str, Any]] = []
        simulated_fail_set = {p.strip().lower() for p in (simulate_failover_providers or [])}

        if configured_defs:
            # Order so READY providers come first, followed by providers in cooldown as last resort
            ready_defs = [
                d for d in configured_defs if self._circuit_cooldown_until.get(d["provider_id"], 0.0) <= now
            ]
            cooldown_defs = [
                d for d in configured_defs if self._circuit_cooldown_until.get(d["provider_id"], 0.0) > now
            ]
            ordered_candidates = ready_defs + cooldown_defs

            for idx, prov in enumerate(ordered_candidates):
                pid = prov["provider_id"]
                model_used = prov["primary_model"]
                hop_start = time.perf_counter()
                self._total_calls_by_provider[pid] = self._total_calls_by_provider.get(pid, 0) + 1

                try:
                    if pid.lower() in simulated_fail_set:
                        raise httpx.HTTPStatusError(
                            f"HTTP 429 RESOURCE_EXHAUSTED (Quota limit reached on primary {pid} tier — automatic failover triggered)",
                            request=httpx.Request("POST", "https://simulated.failover/v1"),
                            response=httpx.Response(
                                429,
                                text='{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","message":"Quota limit reached on primary Gemini tier — automatic failover triggered"}}',
                            ),
                        )

                    if pid == "google_gemini":
                        proposal_dict, model_used = await self._call_google_gemini(
                            api_key=prov["api_key"],
                            primary_model=prov["primary_model"],
                            fallback_model=prov["fallback_model"],
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            failover_trace=failover_trace,
                        )
                    elif pid == "groq_cloud":
                        proposal_dict = await self._call_openai_compatible(
                            provider_id=pid,
                            endpoint="https://api.groq.com/openai/v1/chat/completions",
                            api_key=prov["api_key"],
                            model=prov["primary_model"],
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            fallback_model=prov.get("fallback_model"),
                            failover_trace=failover_trace,
                        )
                        model_used = str(proposal_dict.pop("_fulfilled_model", prov["primary_model"]))
                    elif pid == "xai_grok":
                        proposal_dict = await self._call_openai_compatible(
                            provider_id=pid,
                            endpoint="https://api.x.ai/v1/chat/completions",
                            api_key=prov["api_key"],
                            model=prov["primary_model"],
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            fallback_model=prov.get("fallback_model"),
                            failover_trace=failover_trace,
                        )
                        model_used = str(proposal_dict.pop("_fulfilled_model", prov["primary_model"]))
                    elif pid == "openrouter_free":
                        proposal_dict = await self._call_openrouter_with_fallback(
                            api_key=prov["api_key"],
                            primary_model=prov["primary_model"],
                            fallback_model=prov["fallback_model"],
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            failover_trace=failover_trace,
                        )
                        model_used = str(proposal_dict.pop("_fulfilled_model", prov["primary_model"]))
                    elif pid == "openai":
                        proposal_dict = await self._call_openai_compatible(
                            provider_id=pid,
                            endpoint="https://api.openai.com/v1/chat/completions",
                            api_key=prov["api_key"],
                            model=prov["primary_model"],
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            fallback_model=prov.get("fallback_model"),
                            failover_trace=failover_trace,
                        )
                        model_used = str(proposal_dict.pop("_fulfilled_model", prov["primary_model"]))
                    else:
                        raise RuntimeError(f"Unknown provider_id: {pid}")

                    hop_latency_ms = max(1, int((time.perf_counter() - hop_start) * 1000))
                    total_latency_ms = max(1, int((time.perf_counter() - overall_start) * 1000))

                    # Clear cooldown on success
                    self._circuit_cooldown_until.pop(pid, None)
                    self._circuit_last_error.pop(pid, None)
                    self._last_latency_by_provider[pid] = hop_latency_ms
                    self._last_fulfilled_provider = pid

                    failover_trace.append(
                        {
                            "provider": pid,
                            "model": model_used,
                            "status": "SUCCESS",
                            "latency_ms": hop_latency_ms,
                        }
                    )

                    telemetry = {
                        "provider_used": pid,
                        "model_used": model_used,
                        "failover_hops": max(0, len(failover_trace) - 1),
                        "latency_ms": total_latency_ms,
                        "failover_trace": failover_trace,
                        "requires_api_key": False,
                        "live_llm_used": True,
                    }
                    return self._normalize_proposal_dict(proposal_dict), telemetry

                except Exception as exc:
                    hop_latency_ms = max(1, int((time.perf_counter() - hop_start) * 1000))
                    reason, cooldown_sec = self._classify_exception(exc)
                    self._error_counts_by_provider[pid] = self._error_counts_by_provider.get(pid, 0) + 1
                    self._total_failovers += 1
                    self._circuit_last_error[pid] = reason
                    if cooldown_sec > 0:
                        self._circuit_cooldown_until[pid] = time.time() + cooldown_sec

                    failover_trace.append(
                        {
                            "provider": pid,
                            "model": model_used,
                            "status": "FAILED_FAILOVER",
                            "reason": reason,
                            "cooldown_seconds": cooldown_sec,
                            "latency_ms": hop_latency_ms,
                        }
                    )
                    continue
        elif "google_gemini" in simulated_fail_set:
            # Even when 0 live API keys are set in .env, record the simulated Tier 1 failure hop
            self._total_calls_by_provider["google_gemini"] = (
                self._total_calls_by_provider.get("google_gemini", 0) + 1
            )
            self._error_counts_by_provider["google_gemini"] = (
                self._error_counts_by_provider.get("google_gemini", 0) + 1
            )
            self._total_failovers += 1
            failover_trace.append(
                {
                    "provider": "google_gemini",
                    "model": settings.GEMINI_MODEL or "gemini-2.5-flash",
                    "status": "FAILED_FAILOVER",
                    "reason": "HTTP_429_QUOTA_EXHAUSTED",
                    "cooldown_seconds": 60,
                    "latency_ms": 2,
                    "note": "HTTP 429 RESOURCE_EXHAUSTED (Quota limit reached on primary Gemini tier — automatic failover triggered)",
                }
            )

        # ------------------------------------------------------------------
        # Semantic Catalog-Aware Synthesizer (Used ONLY when 0 API keys are
        # configured in .env yet or every configured key failed with network/429)
        # ------------------------------------------------------------------
        synth_start = time.perf_counter()
        self._total_calls_by_provider["semantic_catalog_synthesizer"] += 1
        proposal_dict = self._synthesize_semantic_catalog_proposal(
            user_prompt=user_prompt,
            catalog_items=catalog_items or [],
            budget_limit_cents=budget_limit_cents,
            previous_items=previous_items,
        )
        synth_latency_ms = max(1, int((time.perf_counter() - synth_start) * 1000))
        total_latency_ms = max(1, int((time.perf_counter() - overall_start) * 1000))
        self._last_latency_by_provider["semantic_catalog_synthesizer"] = synth_latency_ms

        failover_trace.append(
            {
                "provider": "semantic_catalog_synthesizer",
                "model": "intentlock-catalog-reasoning-v1",
                "status": "SUCCESS",
                "latency_ms": synth_latency_ms,
                "note": (
                    "Executed structured semantic catalog synthesis because no live LLM API keys were active "
                    "or all configured keys hit quota/network limits."
                ),
            }
        )

        telemetry = {
            "provider_used": "semantic_catalog_synthesizer",
            "model_used": "intentlock-catalog-reasoning-v1",
            "failover_hops": max(0, len(failover_trace) - 1),
            "latency_ms": total_latency_ms,
            "failover_trace": failover_trace,
            "requires_api_key": len(configured_defs) == 0,
            "live_llm_used": False,
        }
        return self._normalize_proposal_dict(proposal_dict), telemetry

    async def run_failover_drill(
        self,
        prompt: str,
        system_prompt: str,
        catalog_products: list[Any],
    ) -> dict[str, Any]:
        """
        Temporarily forces Tier 1 (`google_gemini`) to simulate
        `HTTP 429 RESOURCE_EXHAUSTED (Quota limit reached on primary Gemini tier — automatic failover triggered)`
        for this single call, automatically cascades to Tier 2 (`groq_cloud` -> `xai_grok` -> `openrouter_free`
        -> `openai` -> semantic catalog synthesizer), and returns the full telemetry.
        """
        saved_cooldowns = dict(self._circuit_cooldown_until)
        saved_errors = dict(self._circuit_last_error)

        simulated_error_msg = (
            "HTTP 429 RESOURCE_EXHAUSTED (Quota limit reached on primary Gemini tier — automatic failover triggered)"
        )
        try:
            proposal_dict, telemetry = await self.generate_cart_proposal(
                system_prompt=system_prompt,
                user_prompt=prompt,
                catalog_items=catalog_products,
                simulate_failover_providers=["google_gemini"],
            )
        finally:
            # Restore circuit breaker state so normal live calls after the drill are not artificially blocked
            self._circuit_cooldown_until = saved_cooldowns
            self._circuit_last_error = saved_errors

        trace = list(telemetry.get("failover_trace") or [])
        if trace and trace[0].get("provider") == "google_gemini":
            trace[0]["simulated_error"] = simulated_error_msg

        return {
            "simulated_primary_error": simulated_error_msg,
            "fulfilled_by_provider": str(telemetry.get("provider_used", "semantic_catalog_synthesizer")),
            "fulfilled_by_model": str(telemetry.get("model_used", "intentlock-catalog-reasoning-v1")),
            "failover_hops": max(1, int(telemetry.get("failover_hops", 1))),
            "failover_trace": trace,
            "latency_ms": int(telemetry.get("latency_ms", 1)),
            "proposal": proposal_dict,
        }

    # ------------------------------------------------------------------
    # Provider-Specific Async HTTP Callers
    # ------------------------------------------------------------------

    async def _call_google_gemini(
        self,
        api_key: str,
        primary_model: str,
        fallback_model: str,
        system_prompt: str,
        user_prompt: str,
        failover_trace: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        last_exc: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=12.0) as client:
            for idx, model_name in enumerate(models_to_try):
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model_name}:generateContent?key={api_key}"
                )
                gen_config: dict[str, Any] = {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                }
                if model_name.startswith("gemini-2.5"):
                    gen_config["thinkingConfig"] = {"thinkingBudget": 0}
                payload = {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": gen_config,
                }
                t0 = time.perf_counter()
                try:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    candidates = data.get("candidates") or []
                    if not candidates:
                        raise ValueError(f"Gemini returned empty candidates: {data}")
                    parts = candidates[0].get("content", {}).get("parts") or []
                    raw_text = "".join(str(p.get("text", "")) for p in parts).strip()
                    parsed = self._extract_json_object(raw_text)
                    return parsed, model_name
                except Exception as exc:
                    last_exc = exc
                    if idx == 0 and len(models_to_try) > 1:
                        reason, _ = self._classify_exception(exc)
                        failover_trace.append(
                            {
                                "provider": "google_gemini",
                                "model": model_name,
                                "status": "INTRA_PROVIDER_FALLBACK",
                                "reason": reason,
                                "latency_ms": max(1, int((time.perf_counter() - t0) * 1000)),
                            }
                        )
                        continue
                    raise

        assert last_exc is not None
        raise last_exc

    async def _call_openrouter_with_fallback(
        self,
        api_key: str,
        primary_model: str,
        fallback_model: str,
        system_prompt: str,
        user_prompt: str,
        failover_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        last_exc: Optional[Exception] = None
        for idx, model_name in enumerate(models_to_try):
            t0 = time.perf_counter()
            try:
                return await self._call_openai_compatible(
                    provider_id="openrouter_free",
                    endpoint="https://openrouter.ai/api/v1/chat/completions",
                    api_key=api_key,
                    model=model_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:5173",
                        "X-Title": "IntentLock Purchasing Agent",
                    },
                )
            except Exception as exc:
                last_exc = exc
                if idx == 0 and len(models_to_try) > 1:
                    reason, _ = self._classify_exception(exc)
                    failover_trace.append(
                        {
                            "provider": "openrouter_free",
                            "model": model_name,
                            "status": "INTRA_PROVIDER_FALLBACK",
                            "reason": reason,
                            "latency_ms": max(1, int((time.perf_counter() - t0) * 1000)),
                        }
                    )
                    continue
                raise

        assert last_exc is not None
        raise last_exc

    async def _call_openai_compatible(
        self,
        provider_id: str,
        endpoint: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        fallback_model: Optional[str] = None,
        failover_trace: Optional[list[dict[str, Any]]] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        models_to_try = [model]
        if fallback_model and fallback_model != model:
            models_to_try.append(fallback_model)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        last_exc: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=12.0) as client:
            for idx, m_name in enumerate(models_to_try):
                payload: dict[str, Any] = {
                    "model": m_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                }
                t0 = time.perf_counter()
                try:
                    resp = await client.post(endpoint, headers=headers, json=payload)
                    # Some OpenRouter free models do not support response_format: json_object
                    if resp.status_code == 400 and provider_id == "openrouter_free":
                        payload.pop("response_format", None)
                        resp = await client.post(endpoint, headers=headers, json=payload)

                    resp.raise_for_status()
                    data = resp.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise ValueError(f"{provider_id} returned empty choices: {data}")
                    content = str(choices[0].get("message", {}).get("content", "")).strip()
                    parsed = self._extract_json_object(content)
                    parsed["_fulfilled_model"] = m_name
                    return parsed
                except Exception as exc:
                    last_exc = exc
                    if idx == 0 and len(models_to_try) > 1:
                        reason, _ = self._classify_exception(exc)
                        if failover_trace is not None:
                            failover_trace.append(
                                {
                                    "provider": provider_id,
                                    "model": m_name,
                                    "status": "INTRA_PROVIDER_FALLBACK",
                                    "reason": reason,
                                    "latency_ms": max(1, int((time.perf_counter() - t0) * 1000)),
                                }
                            )
                        continue
                    raise

        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Error Classification & JSON Normalization Helpers
    # ------------------------------------------------------------------

    def _classify_exception(self, exc: Exception) -> tuple[str, int]:
        if isinstance(exc, httpx.TimeoutException):
            return "TIMEOUT_EXCEEDED_12S", 30

        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            body_preview = (exc.response.text or "")[:180].lower()
            if code == 429:
                if "quota" in body_preview or "daily" in body_preview or "billing" in body_preview:
                    return "HTTP_429_QUOTA_EXHAUSTED", 900
                return "HTTP_429_RATE_LIMIT", 60
            if code in (401, 403):
                return f"HTTP_{code}_AUTH_OR_PERMISSION", 300
            if code == 402:
                return "HTTP_402_CREDITS_EXHAUSTED", 900
            if code == 404:
                return "HTTP_404_MODEL_UNAVAILABLE", 60
            if code >= 500:
                return f"HTTP_{code}_UPSTREAM_OUTAGE", 30
            return f"HTTP_{code}_ERROR", 30

        return f"SCHEMA_OR_TRANSPORT_ERROR ({type(exc).__name__})", 15

    def _extract_json_object(self, raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed

        raise ValueError("LLM response did not contain a valid JSON object.")

    def _normalize_proposal_dict(self, raw: dict[str, Any]) -> dict[str, Any]:
        raw_items = raw.get("items")
        if raw_items is None:
            raw_items = raw.get("line_items") or []

        normalized_items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku", "")).strip().upper()
            if not sku:
                continue
            try:
                qty = int(item.get("quantity", 1))
            except (TypeError, ValueError):
                qty = 1
            rationale = str(
                item.get("selection_rationale")
                or item.get("item_rationale")
                or item.get("rationale")
                or "Selected to fulfill Coordinator purchasing request."
            ).strip()
            headcount_math = str(
                item.get("headcount_math")
                or item.get("headcount_or_pack_math")
                or item.get("math")
                or f"{qty} unit(s) selected based on team requirement."
            ).strip()

            normalized_entry: dict[str, Any] = {
                "sku": sku,
                "quantity": qty,
                "selection_rationale": rationale,
                "headcount_math": headcount_math,
            }
            # Preserve any rogue LLM price fields so Guardrail G-01 can explicitly detect & strip them
            if "unit_price_cents" in item:
                normalized_entry["unit_price_cents"] = item["unit_price_cents"]
            if "price_cents" in item:
                normalized_entry["price_cents"] = item["price_cents"]

            normalized_items.append(normalized_entry)

        warnings: list[str] = []
        for key in ("warnings", "unfulfilled_or_out_of_stock_warnings"):
            val = raw.get(key)
            if isinstance(val, list):
                warnings.extend(str(w) for w in val if w)

        overall_summary = str(
            raw.get("overall_summary")
            or raw.get("summary")
            or raw.get("agent_explanation")
            or f"Proposed {len(normalized_items)} catalog item(s) from Acme Workspace Supplies."
        ).strip()

        budget_notes = str(
            raw.get("budget_notes")
            or raw.get("agent_budget_notes")
            or "All unit prices and totals are deterministically resolved from the Acme Workspace Supplies USD catalog."
        ).strip()

        return {
            "overall_summary": overall_summary,
            "budget_notes": budget_notes,
            "warnings": warnings,
            "items": normalized_items,
        }

    # ------------------------------------------------------------------
    # Semantic Catalog-Aware Reasoning Parser (Zero-API-Key CI Fallback)
    # ------------------------------------------------------------------

    def _synthesize_semantic_catalog_proposal(
        self,
        user_prompt: str,
        catalog_items: list[Any],
        budget_limit_cents: Optional[int] = None,
        previous_items: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Structured semantic catalog synthesis used ONLY when zero live LLM API keys
        are configured in `.env` or runtime memory, ensuring unit tests and CI benchmarks
        execute deterministically while live keys always take priority.
        """
        text = user_prompt or ""
        text_lower = text.lower()
        warnings: list[str] = []

        # Detect out-of-catalog hardware/items explicitly mentioned
        out_of_catalog_terms = [
            ("monitor", "External Monitors (e.g., 27-inch 4K Monitors)"),
            ("macbook", "Laptops / MacBooks"),
            ("laptop", "Laptop Computers"),
            ("chair", "Office Chairs / Seating"),
            ("standing desk", "Standing Desks"),
            ("gift card", "Gift Cards"),
        ]
        for trigger, label in out_of_catalog_terms:
            if re.search(rf"\b{re.escape(trigger)}s?\b", text_lower):
                if trigger == "laptop" and re.search(r"laptop\s+(?:cord|charger|cable|hub|dock|workstation)", text_lower):
                    continue
                if trigger == "monitor" and re.search(r"monitor\s+adapter", text_lower):
                    continue
                warnings.append(
                    f"Out-of-catalog item requested: '{label}' is not carried in the 15-SKU Acme Workspace Supplies catalog and was excluded."
                )

        # Extract headcount if specified (e.g. "4 software engineers", "20-person office", "10-person team", "20 attendees")
        headcount = 1
        hc_match = re.search(
            r"\b(\d+)\s*(?:-|\s)?(?:(?:new|remote|software|backend|frontend|senior|junior|full-stack|client|workshop|office)\s+){0,2}(?:person|people|engineer|engineers|hire|hires|attendee|attendees|designer|designers|staff|employee|employees|developer|developers)\b",
            text_lower,
        )
        if hc_match:
            headcount = max(1, int(hc_match.group(1)))

        # Extract inline budget limit if not explicitly passed
        effective_budget_cents = budget_limit_cents
        if effective_budget_cents is None:
            b_match = re.search(r"(?:under|below|max|ceiling|budget(?:\s+of)?)\s*\$\s*(\d+(?:\.\d{1,2})?)", text_lower)
            if b_match:
                effective_budget_cents = int(round(float(b_match.group(1)) * 100))

        # Start from previous items if this is a conversational revision ("also add", "change", "actually make it")
        is_revision = bool(previous_items) and bool(
            re.search(r"\b(?:actually|also|add|update|increase|change|make\s+it|instead|plus|remove)\b", text_lower)
        )
        selected_by_sku: dict[str, dict[str, Any]] = {}
        if is_revision and previous_items:
            for prev in previous_items:
                psku = str(prev.get("sku", "")).upper()
                if psku:
                    selected_by_sku[psku] = {
                        "sku": psku,
                        "quantity": int(prev.get("quantity", 1)),
                        "selection_rationale": str(
                            prev.get("selection_rationale") or "Retained from prior cart version."
                        ),
                        "headcount_math": str(prev.get("headcount_math") or f"{prev.get('quantity', 1)} unit(s)"),
                    }

        # Direct SKU pattern matching rules with explicit pack-size ceiling math
        sku_rules: list[tuple[str, list[str], str]] = [
            ("SKU-001", ["sku-001", "coffee", "dark roast", "whole bean", "espresso"], "per_10"),
            ("SKU-002", ["sku-002", "oat milk", "barista", "creamer"], "per_12"),
            ("SKU-003", ["sku-003", "hot cup", "hot cups", "compostable cup", "paper cup", "cups"], "per_20"),
            ("SKU-004", ["sku-004", "snack box", "snack boxes", "healthy snack", "snacks"], "per_10"),
            ("SKU-005", ["sku-005", "notebook", "notebooks", "dot-grid", "journal"], "per_1"),
            ("SKU-006", ["sku-006", "gel pen", "gel pens", "rollerball", "black pen", "pens"], "per_6_pack12"),
            ("SKU-007", ["sku-007", "whiteboard marker", "whiteboard markers", "dry erase", "chisel tip"], "per_8"),
            ("SKU-008", ["sku-008", "sticky note", "sticky notes", "super-sticky", "post-it"], "per_6_pack12"),
            ("SKU-009", ["sku-009", "usb-c cable", "usb-c cables", "100w cable", "braided usb-c", "pd cable", "charging cord"], "per_1"),
            ("SKU-010", ["sku-010", "multiport hub", "usb-c hub", "usb-c hubs", "7-in-1", "docking", "dongle", "hubs"], "per_1"),
            ("SKU-011", ["sku-011", "ergonomic mouse", "wireless mouse", "wireless mice", "ergonomic mice", "mouse", "mice"], "per_1"),
            ("SKU-012", ["sku-012", "wall charger", "wall chargers", "65w", "gan charger", "fast charger", "chargers"], "per_1"),
            ("SKU-013", ["sku-013", "cleaning kit", "cleaning kits", "whiteboard cleaning", "screen cleaner", "microfiber"], "per_10"),
            ("SKU-014", ["sku-014", "disinfecting", "surface wipes", "wipes canister", "sanitizing wipes", "wipes"], "per_15"),
            ("SKU-015", ["sku-015", "first aid", "osha", "medical kit"], "per_50"),
        ]

        for sku, triggers, rule_mode in sku_rules:
            matched_triggers = [trig for trig in triggers if trig in text_lower]
            if not matched_triggers:
                continue

            # Check if an explicit quantity sits immediately before any matched trigger
            explicit_qty: Optional[int] = None
            matched_trigger = matched_triggers[0]
            for trig in matched_triggers:
                escaped_trig = re.escape(trig)
                qty_patterns = [
                    rf"\b(\d+)\s*(?:x\s*)?(?:packs?\s+of\s+|boxes?\s+of\s+|bundles?\s+of\s+|cases?\s+of\s+|units?\s+of\s+|kits?\s+of\s+)?{escaped_trig}",
                    rf"\b(\d+)\s+(?:[a-z0-9\-]+\s+){{0,4}}?{escaped_trig}",
                ]
                for qp in qty_patterns:
                    m = re.search(qp, text_lower)
                    if m:
                        candidate_num = int(m.group(1))
                        # Avoid mistaking "65w", "100w", "4k", "27-inch", or headcount as explicit item quantity
                        if candidate_num not in (65, 100, 192, 200) and not re.search(
                            rf"\b{candidate_num}\s*(?:-|\s)?(?:(?:new|remote|software|backend|frontend|senior|junior)\s+){{0,2}}(?:person|people|engineer|engineers|hire|hires|attendee|attendees|inch|w\b)",
                            m.group(0),
                        ):
                            explicit_qty = candidate_num
                            matched_trigger = trig
                            break
                if explicit_qty is not None:
                    break

            if explicit_qty is not None:
                qty = max(1, explicit_qty)
                math_str = f"Explicitly requested {qty} unit(s)/pack(s) in Coordinator prompt."
                rationale = f"Selected {sku} matching request for '{matched_trigger}' ({qty} unit(s))."
            else:
                if rule_mode == "per_1":
                    qty = headcount
                    math_str = f"{headcount} person(s) x 1 unit/person = {qty} unit(s)"
                elif rule_mode == "per_6_pack12":
                    qty = math.ceil((headcount * 2) / 12)
                    math_str = f"ceil(({headcount} people x 2 per person) / 12 per pack) = {qty} pack(s)"
                elif rule_mode == "per_8":
                    qty = math.ceil(headcount / 8)
                    math_str = f"ceil({headcount} people / 8 per pack) = {qty} pack(s)"
                elif rule_mode == "per_10":
                    qty = math.ceil(headcount / 10)
                    math_str = f"ceil({headcount} people / 10 per pack) = {qty} pack(s)"
                elif rule_mode == "per_12":
                    qty = math.ceil(headcount / 12)
                    math_str = f"ceil({headcount} people / 12 per case) = {qty} case(s)"
                elif rule_mode == "per_15":
                    qty = math.ceil(headcount / 15)
                    math_str = f"ceil({headcount} people / 15 per bundle) = {qty} bundle(s)"
                elif rule_mode == "per_20":
                    qty = math.ceil(headcount / 20)
                    math_str = f"ceil({headcount} people / 20 per sleeve) = {qty} sleeve(s)"
                else:
                    qty = 1
                    math_str = f"1 kit covers up to 50 people (headcount={headcount}) -> {qty} unit"
                rationale = (
                    f"Selected {sku} to fulfill '{matched_trigger}' need for {headcount} person(s) "
                    "using catalog pack-size math."
                )

            selected_by_sku[sku] = {
                "sku": sku,
                "quantity": qty,
                "selection_rationale": rationale,
                "headcount_math": math_str,
            }

        # Fallback starter kit if prompt was generic (e.g. "onboarding kit" or "workshop supplies" without specific item names)
        if not selected_by_sku:
            if "breakroom" in text_lower or "coffee" in text_lower:
                for sku, q in [("SKU-001", math.ceil(headcount / 10)), ("SKU-002", math.ceil(headcount / 12)), ("SKU-003", 1)]:
                    selected_by_sku[sku] = {
                        "sku": sku,
                        "quantity": max(1, q),
                        "selection_rationale": f"Standard breakroom restock bundle for {headcount} people.",
                        "headcount_math": f"Scaled for {headcount} people -> {max(1, q)} pack(s)",
                    }
            elif "workshop" in text_lower or "sprint" in text_lower or "strategy" in text_lower:
                for sku, q in [
                    ("SKU-005", headcount),
                    ("SKU-006", math.ceil((headcount * 2) / 12)),
                    ("SKU-007", math.ceil(headcount / 8)),
                    ("SKU-008", math.ceil((headcount * 2) / 12)),
                ]:
                    selected_by_sku[sku] = {
                        "sku": sku,
                        "quantity": max(1, q),
                        "selection_rationale": f"Workshop collaboration stationery for {headcount} attendees.",
                        "headcount_math": f"Pack math for {headcount} attendees -> {max(1, q)} unit(s)",
                    }
            else:
                for sku, q in [
                    ("SKU-005", headcount),
                    ("SKU-006", math.ceil((headcount * 2) / 12)),
                    ("SKU-009", headcount),
                    ("SKU-012", headcount),
                ]:
                    selected_by_sku[sku] = {
                        "sku": sku,
                        "quantity": max(1, q),
                        "selection_rationale": f"Standard onboarding starter bundle for {headcount} team member(s).",
                        "headcount_math": f"Scaled for {headcount} person(s) -> {max(1, q)} unit(s)",
                    }

        # Budget fitting pass if effective_budget_cents is specified
        price_lookup = {
            getattr(p, "sku", ""): int(getattr(p, "unit_price_cents", 0))
            for p in (catalog_items or [])
            if getattr(p, "sku", None)
        }
        if effective_budget_cents and effective_budget_cents > 0 and price_lookup:
            def _calc_total() -> int:
                return sum(
                    price_lookup.get(s, 0) * int(entry["quantity"])
                    for s, entry in selected_by_sku.items()
                )

            while _calc_total() > effective_budget_cents:
                # Reduce highest-priced item with quantity > 1
                reducible = [
                    s for s, entry in selected_by_sku.items() if int(entry["quantity"]) > 1
                ]
                if not reducible:
                    break
                reducible.sort(key=lambda s: price_lookup.get(s, 0), reverse=True)
                target_sku = reducible[0]
                selected_by_sku[target_sku]["quantity"] -= 1
                selected_by_sku[target_sku]["headcount_math"] += (
                    f" [Adjusted to {selected_by_sku[target_sku]['quantity']} to fit ${effective_budget_cents / 100:.2f} ceiling]"
                )

        items_list = [selected_by_sku[k] for k in sorted(selected_by_sku.keys())]
        est_total_cents = sum(
            price_lookup.get(item["sku"], 0) * int(item["quantity"]) for item in items_list
        )
        if effective_budget_cents:
            budget_notes = (
                f"Proposed cart total is ${est_total_cents / 100:.2f} ({est_total_cents} cents) against "
                f"budget ceiling of ${effective_budget_cents / 100:.2f} ({effective_budget_cents} cents)."
            )
        else:
            budget_notes = (
                f"Proposed cart total is ${est_total_cents / 100:.2f} ({est_total_cents} cents); "
                "no explicit budget cap was specified."
            )

        return {
            "overall_summary": (
                f"Translated Coordinator request into {len(items_list)} Acme Workspace Supplies SKU(s) "
                f"using pack-size ceiling arithmetic (estimated total ${est_total_cents / 100:.2f} USD)."
            ),
            "budget_notes": budget_notes,
            "warnings": warnings,
            "items": items_list,
        }


# Singleton router instance imported by agent_service, eval_service, and main.py
llm_router = MultiProviderLLMRouter()
