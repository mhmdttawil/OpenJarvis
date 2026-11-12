"""Read-only tool over the Stonepoint / Steelblue Ops Portal (Supabase sp_docs).

Lets the agent answer "what's open with KFM", "did Myriad pay", "what's our
balance", "what did we spend on fuel this month" from the same document table
the portal at stonepointpropertyservices.com/ops reads.

Env vars: ``OPS_SUPABASE_URL`` (https://<ref>.supabase.co), ``OPS_SUPABASE_ANON_KEY``,
``OPS_API_KEY`` (the portal's x-ops-key). Read-only by design: it only issues
GET requests, never writes.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_COLLECTIONS = ("jobs", "invoices", "payments", "bank", "expenses", "meta")


def _get(collection: str, company: str, extra_qs: str = "") -> list[dict[str, Any]]:
    base = os.environ.get("OPS_SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("OPS_SUPABASE_ANON_KEY", "")
    key = os.environ.get("OPS_API_KEY", "")
    if not base or not anon or not key:
        raise RuntimeError("OPS_SUPABASE_URL / OPS_SUPABASE_ANON_KEY / OPS_API_KEY not set")
    coll = collection if company == "stonepoint" else f"steelblue:{collection}"
    url = (
        f"{base}/rest/v1/sp_docs?select=id,data,version&collection=eq."
        f"{urllib.parse.quote(coll)}&limit=2000{extra_qs}"
    )
    req = urllib.request.Request(
        url,
        headers={"apikey": anon, "Authorization": f"Bearer {anon}", "x-ops-key": key},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _slim_job(r: dict[str, Any]) -> dict[str, Any]:
    d = r["data"]
    keep = ("client", "ref", "site", "stage", "ball", "next", "when", "amount", "nte", "invoice", "paidAmount", "paidDate")
    out = {"id": r["id"], **{k: d.get(k) for k in keep if d.get(k) not in (None, "")}}
    hist = d.get("history") or []
    if hist:
        out["last"] = hist[-1]
    return out


@ToolRegistry.register("ops_portal")
class OpsPortalTool(BaseTool):
    """Query the Ops Portal document store (read-only)."""

    tool_id = "ops_portal"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ops_portal",
            description=(
                "Read the Stonepoint / Steelblue Ops Portal: jobs (by stage or who the "
                "ball is with), a single job's full history, open invoices, recent "
                "payments and bank deposits, expenses by category, the bank balance and "
                "the last sync summary. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "enum": [
                            "jobs_open", "jobs_ball_me", "jobs_ball_them", "jobs_by_stage",
                            "job", "invoices_open", "payments_recent", "bank_recent",
                            "expenses_month", "balance", "sync_status", "search",
                        ],
                        "description": "What to fetch.",
                    },
                    "company": {
                        "type": "string",
                        "enum": ["stonepoint", "steelblue"],
                        "description": "Which LLC. Default stonepoint.",
                    },
                    "arg": {
                        "type": "string",
                        "description": (
                            "Extra argument: stage name for jobs_by_stage; job id, WO/PO "
                            "number or site keyword for job/search; YYYY-MM for expenses_month."
                        ),
                    },
                },
                "required": ["query"],
            },
            category="business",
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        t0 = time.time()
        q = str(params.get("query", ""))
        company = str(params.get("company", "stonepoint") or "stonepoint")
        arg = str(params.get("arg", "") or "").strip()
        try:
            out: Any
            if q in ("jobs_open", "jobs_ball_me", "jobs_ball_them", "jobs_by_stage", "job", "search"):
                rows = _get("jobs", company)
                closed = {"paid", "closed"}
                if q == "jobs_open":
                    out = [_slim_job(r) for r in rows if r["data"].get("stage") not in closed]
                elif q == "jobs_ball_me":
                    out = [_slim_job(r) for r in rows if r["data"].get("ball") == "me" and r["data"].get("stage") not in closed]
                elif q == "jobs_ball_them":
                    out = [_slim_job(r) for r in rows if r["data"].get("ball") == "them" and r["data"].get("stage") not in closed]
                elif q == "jobs_by_stage":
                    out = [_slim_job(r) for r in rows if r["data"].get("stage") == arg]
                else:
                    needle = arg.lower().replace("wo ", "").replace("po ", "").lstrip("0")
                    hits = [
                        r for r in rows
                        if needle and (
                            needle in r["id"].lower()
                            or needle in str(r["data"].get("ref", "")).lower().lstrip("0")
                            or needle in str(r["data"].get("site", "")).lower()
                            or needle in str(r["data"].get("client", "")).lower()
                        )
                    ]
                    if q == "job":
                        out = [{"id": r["id"], **r["data"]} for r in hits[:2]]
                        for j in out:
                            j.pop("threadIds", None)
                    else:
                        out = [_slim_job(r) for r in hits[:25]]
                out = sorted(out, key=lambda j: j.get("when") or "") if isinstance(out, list) else out
            elif q == "invoices_open":
                rows = _get("invoices", company)
                out = [
                    {"id": r["id"], **{k: r["data"].get(k) for k in ("client", "amount", "date", "status", "due", "jobId")}}
                    for r in rows if r["data"].get("status") not in ("paid", "rejected", "draft")
                ]
                out.sort(key=lambda i: i.get("date") or "")
            elif q == "payments_recent":
                rows = _get("payments", company)
                out = sorted(
                    [{"id": r["id"], **{k: r["data"].get(k) for k in ("date", "amount", "payer", "method", "invoiceIds", "bankTxnDate")}} for r in rows],
                    key=lambda p: p.get("date") or "", reverse=True,
                )[:15]
            elif q == "bank_recent":
                rows = _get("bank", company)
                out = sorted(
                    [{k: r["data"].get(k) for k in ("date", "desc", "amount", "paymentId")} for r in rows],
                    key=lambda b: b.get("date") or "", reverse=True,
                )[:15]
            elif q == "expenses_month":
                month = arg or time.strftime("%Y-%m")
                rows = [r["data"] for r in _get("expenses", company) if str(r["data"].get("date", "")).startswith(month)]
                by_cat: dict[str, float] = {}
                for e in rows:
                    by_cat[e.get("category") or "Uncategorized"] = round(by_cat.get(e.get("category") or "Uncategorized", 0) + float(e.get("amount") or 0), 2)
                out = {"month": month, "total": round(sum(by_cat.values()), 2), "by_category": by_cat, "count": len(rows)}
            elif q == "balance":
                rows = _get("meta", company, "&id=eq.balance")
                out = rows[0]["data"] if rows else {"error": "no balance doc"}
            elif q == "sync_status":
                rows = _get("meta", company, "&id=eq.sync")
                out = rows[0]["data"] if rows else {"error": "no sync doc"}
            else:
                return ToolResult(tool_name="ops_portal", content=f"unknown query {q}", success=False)
            return ToolResult(
                tool_name="ops_portal",
                content=json.dumps(out, default=str)[:12000],
                success=True,
                latency_seconds=time.time() - t0,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name="ops_portal", content=f"ops_portal failed: {exc}", success=False, latency_seconds=time.time() - t0)
