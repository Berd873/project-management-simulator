"""Verify the configured DeepSeek endpoint with real calls (no mocks).

Usage:  .\\.venv\\Scripts\\python.exe scripts/verify_real_provider.py
Writes a JSON evidence record next to this script's parent (real-provider-check.json).
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx
from app import main as app_main  # noqa: F401  imports load .env at module import
from app.agents.contracts import AgentContext, validate_decision, ApprovalDecision
from app.agents.providers import RealProvider
from app.domain import Role

BRIEF = "图书管理系统：馆藏管理、读者管理、借阅与归还、馆藏检索"
evidence = {"base_url": os.environ.get("LLM_BASE_URL"), "model": os.environ.get("LLM_MODEL"),
            "timeout": os.environ.get("LLM_TIMEOUT_SECONDS"), "calls": []}


def record(name, fn):
    started = time.perf_counter()
    try:
        value = fn()
        elapsed = round((time.perf_counter() - started) * 1000)
        evidence["calls"].append({"name": name, "ok": True, "elapsed_ms": elapsed, "result": value})
        print(f"[OK]   {name} ({elapsed} ms)")
        return value
    except Exception as exc:  # noqa: BLE001
        elapsed = round((time.perf_counter() - started) * 1000)
        evidence["calls"].append({"name": name, "ok": False, "elapsed_ms": elapsed,
                                  "error": f"{type(exc).__name__}: {exc}"})
        print(f"[FAIL] {name} ({elapsed} ms): {type(exc).__name__}: {exc}")
        return None


def list_models():
    with httpx.Client(timeout=30) as client:
        response = client.get(os.environ["LLM_BASE_URL"].rstrip("/") + "/models",
                              headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"})
        response.raise_for_status()
        return [m["id"] for m in response.json()["data"]]


record("models", list_models)

provider = RealProvider()

for role, operation in [(Role.SPONSOR, "proposal"), (Role.PROJECT_MANAGER, "proposal"),
                        (Role.REQUIREMENTS_ANALYST, "proposal")]:
    def call(role=role, operation=operation):
        context = AgentContext(project_id="verify", run_id="verify", role=role, brief=BRIEF, operation=operation)
        last = None
        for attempt in range(1, 4):  # same bounded retry the workflow uses
            try:
                decision = validate_decision(provider.generate(context), context)
                return {"role": decision.role.value, "attempts": attempt, "rationale": decision.rationale,
                        "payload_keys": sorted(decision.payload), "payload": decision.payload}
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise last
    record(f"generate:{role.value}", call)

TARGET = {"target_id": "charter-verify", "target_version": 1}


def approve():
    raw = provider.approve(TARGET, {"objectives": ["交付图书管理系统"], "success_criteria": ["范围验收通过"]})
    decision = ApprovalDecision.model_validate(raw)
    if decision.target_id != TARGET["target_id"] or decision.target_version != TARGET["target_version"]:
        raise ValueError("Approval must bind to the exact target version")
    return decision.model_dump()


record("approve", approve)

evidence["ok"] = all(call["ok"] for call in evidence["calls"])
out = Path(r"D:\大三上\软件项目管理\_work\real-provider-check.json")
out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nALL PASSED={evidence['ok']} -> {out}")
sys.exit(0 if evidence["ok"] else 1)
