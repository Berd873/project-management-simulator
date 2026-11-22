"""Export the latest completed simulation as local report material."""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from app.services.planning import Plan
from app.services.project_export import export_project_xml


root = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=True)
connection = sqlite3.connect(root / "simulator.db")
connection.row_factory = sqlite3.Row


def rows(query, parameters=()):
    return [dict(row) for row in connection.execute(query, parameters)]


projects = rows("SELECT * FROM projects WHERE status='completed' ORDER BY created_at DESC")
if not projects:
    raise SystemExit("No completed project is available")
project = projects[0]
run = rows("SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC", (project["id"],))[0]
project_id, run_id = project["id"], run["id"]
artifacts = rows("SELECT kind,version,author,payload FROM artifacts WHERE project_id=? ORDER BY kind,version", (project_id,))
for artifact in artifacts:
    artifact["payload"] = json.loads(artifact["payload"])
baselines = rows("SELECT version,effective_day,content,content_hash FROM baselines WHERE project_id=? ORDER BY version", (project_id,))
for baseline in baselines:
    baseline["content"] = json.loads(baseline["content"])
changes = rows("SELECT reason,status,impact FROM change_requests WHERE run_id=?", (run_id,))
for change in changes:
    change["impact"] = json.loads(change["impact"])
ticks = rows("SELECT day,metrics,events,assignments,snapshot FROM simulation_ticks WHERE run_id=? ORDER BY day", (run_id,))
for tick in ticks:
    for key in ("metrics", "events", "assignments", "snapshot"):
        tick[key] = json.loads(tick[key])
traces = rows("SELECT node,role,provider,valid,elapsed_ms,error,output FROM agent_executions WHERE run_id=? ORDER BY node,attempt", (run_id,))
for trace in traces:
    trace["output"] = json.loads(trace["output"])
approvals = rows("SELECT a.status,a.decision,b.kind,b.version FROM approvals a JOIN artifacts b ON b.id=a.target_id WHERE a.run_id=? ORDER BY b.created_at", (run_id,))
for approval in approvals:
    approval["decision"] = json.loads(approval["decision"]) if approval["decision"] else None
material = {"project": project, "run": run, "artifacts": artifacts, "baselines": baselines,
            "changes": changes, "ticks": ticks, "traces": traces, "approvals": approvals}
(output / "report-data.json").write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
plan = Plan.model_validate(baselines[-1]["content"]["plan"])
(output / "图书管理项目计划.xml").write_bytes(export_project_xml(plan, project["name"], date(2026, 11, 16), project_id))
print(f"Exported run {run_id}: {len(ticks)-1} workdays, {len(traces)} role calls, baseline V{plan.version}")
