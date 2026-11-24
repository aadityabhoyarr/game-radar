"""FastAPI Dashboard backend for Game Radar.
Rule 8: Only reads the database; Run now button launches the worker as a subprocess.
Rule 9: No Node build step, no CDN, works offline.
"""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Dict, List, Optional
import urllib.parse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from radar.db import Database

logger = logging.getLogger("radar.api")

app = FastAPI(title="Game Radar Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database()

# Process tracking for worker
_current_worker_proc: Optional[subprocess.Popen] = None
_latest_log_path: Optional[str] = None

class ManualGameUpdate(BaseModel):
    notes: Optional[str] = None
    appmagic_revenue_monthly: Optional[float] = None
    appmagic_downloads_monthly: Optional[float] = None

@app.get("/api/runs")
def get_runs():
    with db.get_connection() as conn:
        runs = conn.execute("SELECT * FROM runs ORDER BY start_time DESC LIMIT 20").fetchall()
        errors = conn.execute("SELECT * FROM run_errors ORDER BY created_at DESC LIMIT 50").fetchall()
        return {
            "runs": [dict(r) for r in runs],
            "errors": [dict(e) for e in errors],
            "worker_running": _current_worker_proc is not None and _current_worker_proc.poll() is None
        }

@app.post("/api/runs/start")
def start_worker_run(mode: str = "standard"):
    global _current_worker_proc, _latest_log_path
    if _current_worker_proc is not None and _current_worker_proc.poll() is None:
        return {"status": "already_running", "message": "Worker run is already active."}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    _latest_log_path = str(logs_dir / f"run_{ts}.log")
    
    cmd = [sys.executable, "-m", "radar", "run", "--mode", mode, "--log-file", _latest_log_path]
    log_file = open(_latest_log_path, "w", encoding="utf-8")
    _current_worker_proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        shell=False
    )
    return {"status": "started", "log_file": _latest_log_path}

@app.get("/api/runs/logs/live")
def get_live_logs():
    global _latest_log_path
    if not _latest_log_path or not Path(_latest_log_path).exists():
        # Fallback to most recent log in logs/
        logs_dir = Path("logs")
        if logs_dir.exists():
            logs = sorted(str(p) for p in logs_dir.glob("*.log"))
            if logs:
                _latest_log_path = logs[-1]
            else:
                return {"lines": [], "running": False}
        else:
            return {"lines": [], "running": False}

    try:
        with open(_latest_log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return {
                "lines": lines[-150:],
                "running": _current_worker_proc is not None and _current_worker_proc.poll() is None,
                "log_file": _latest_log_path
            }
    except Exception as e:
        return {"lines": [f"Error reading log: {e}"], "running": False}

@app.get("/api/games")
def get_games(
    group: str = "all",
    category: Optional[str] = None,
    subgenre: Optional[str] = None,
    min_score: float = 0.0,
    max_age: int = 90,
    confidence: Optional[str] = None,
    hide_big: bool = True,
    hide_hyper: bool = True,
    hide_franchise: bool = True,
    hide_paid: bool = False,
    search: Optional[str] = None
):
    with db.get_connection() as conn:
        latest_run = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'COMPLETED' AND mode IN ('standard', 'full', 'daily') ORDER BY start_time DESC LIMIT 1"
        ).fetchone()
        if not latest_run:
            latest_run = conn.execute(
                "SELECT run_id FROM runs WHERE mode IN ('standard', 'full', 'daily') ORDER BY start_time DESC LIMIT 1"
            ).fetchone()
        if not latest_run:
            return {"games": [], "run_id": None}

        run_id = latest_run["run_id"]
        score_col = f"cm.trend_score_{group}" if group in ["west", "east"] else "cm.trend_score_all"

        query = f"""
        SELECT cm.*, a.title, a.developer, a.category, a.genre, a.released,
               a.age_estimated, a.url as play_url, a.icon, a.notes,
               a.appmagic_revenue_monthly, a.appmagic_downloads_monthly,
               s.real_installs, s.installs_label, s.score, s.ratings
        FROM cohort_metrics cm
        JOIN apps a ON cm.app_id = a.app_id
        LEFT JOIN app_snapshots s ON cm.app_id = s.app_id AND s.run_id = cm.run_id
        WHERE cm.run_id = ?
        """
        rows = conn.execute(query, (run_id,)).fetchall()

    filtered = []
    for r in rows:
        g = dict(r)
        flags = json.loads(g.get("brand_flags") or "{}")
        tags = json.loads(g.get("subgenre_tags") or "[]")
        g["tags"] = tags
        g["flags"] = flags

        # Toggles
        if hide_big and flags.get("big_publisher"):
            continue
        if hide_hyper and flags.get("hypercasual_publisher"):
            continue
        if hide_franchise and flags.get("franchise"):
            continue
        if hide_paid and flags.get("paid_traffic_suspect"):
            continue

        sc = g.get(f"trend_score_{group}") if group in ["west", "east"] else g.get("trend_score_all", 0.0)
        if sc is None or sc < min_score:
            continue

        if g.get("age_days", 90) > max_age:
            continue

        if confidence and g.get("confidence") != confidence:
            continue

        if category and g.get("category") != category:
            continue

        if subgenre and subgenre not in tags:
            continue

        if search:
            q = search.lower()
            t = (g.get("title") or "").lower()
            aid = g["app_id"].lower()
            dev = (g.get("developer") or "").lower()
            if q not in t and q not in aid and q not in dev:
                continue

        g["display_score"] = sc
        filtered.append(g)

    filtered.sort(key=lambda x: x.get("display_score", 0.0), reverse=True)
    return {"games": filtered, "run_id": run_id}

@app.get("/api/game/{app_id}")
def get_game_detail(app_id: str):
    with db.get_connection() as conn:
        app_row = conn.execute("SELECT * FROM apps WHERE app_id = ?", (app_id,)).fetchone()
        if not app_row:
            raise HTTPException(status_code=404, detail="App not found")

        # Snapshots
        snaps = conn.execute(
            "SELECT date, real_installs, score, ratings FROM app_snapshots WHERE app_id = ? ORDER BY date ASC",
            (app_id,)
        ).fetchall()

        # Review daily
        reviews = conn.execute(
            "SELECT date, SUM(count) as cnt FROM review_daily WHERE app_id = ? GROUP BY date ORDER BY date ASC LIMIT 90",
            (app_id,)
        ).fetchall()

        # Chart appearances
        charts = conn.execute(
            "SELECT date, country, collection, category, rank FROM chart_entries WHERE app_id = ? ORDER BY date DESC, rank ASC",
            (app_id,)
        ).fetchall()

        # Latest cohort metric
        metric = conn.execute(
            "SELECT * FROM cohort_metrics WHERE app_id = ? ORDER BY date DESC LIMIT 1",
            (app_id,)
        ).fetchone()

        # Backfill meta
        bmeta = conn.execute("SELECT * FROM backfill_meta WHERE app_id = ?", (app_id,)).fetchone()

    # Meta Ad Library URL pattern
    app_title = app_row["title"] or app_id
    encoded_name = urllib.parse.quote(app_title)
    meta_ad_url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ALL&q={encoded_name}&search_type=keyword_unordered"
    androidrank_url = f"https://androidrank.org/details?id={app_id}"
    appmagic_url = "https://appmagic.rocks/"

    return {
        "app": dict(app_row),
        "snapshots": [dict(s) for s in snaps],
        "reviews": [dict(r) for r in reviews],
        "charts": [dict(c) for c in charts],
        "metric": dict(metric) if metric else None,
        "backfill": dict(bmeta) if bmeta else None,
        "links": {
            "play_store": app_row["url"] or f"https://play.google.com/store/apps/details?id={app_id}",
            "meta_ad_library": meta_ad_url,
            "androidrank": androidrank_url,
            "appmagic": appmagic_url
        }
    }

@app.post("/api/game/{app_id}/manual")
def update_manual_fields(app_id: str, update: ManualGameUpdate):
    with db.get_connection() as conn:
        conn.execute(
            """UPDATE apps SET
               notes = COALESCE(?, notes),
               appmagic_revenue_monthly = COALESCE(?, appmagic_revenue_monthly),
               appmagic_downloads_monthly = COALESCE(?, appmagic_downloads_monthly)
               WHERE app_id = ?""",
            (update.notes, update.appmagic_revenue_monthly, update.appmagic_downloads_monthly, app_id)
        )
        conn.commit()
    return {"status": "updated", "app_id": app_id}

@app.get("/api/subgenres")
def get_subgenres():
    with db.get_connection() as conn:
        latest = conn.execute("SELECT run_id FROM runs WHERE status = 'COMPLETED' ORDER BY start_time DESC LIMIT 1").fetchone()
        if not latest:
            return {"subgenres": []}
        run_id = latest["run_id"]
        rows = conn.execute(
            "SELECT * FROM subgenre_scores WHERE run_id = ? ORDER BY group_name, build_now_score DESC",
            (run_id,)
        ).fetchall()
        res = [dict(r) for r in rows]
        for r in res:
            r["evidence_games"] = json.loads(r.get("evidence_games_json") or "[]")
        return {"subgenres": res, "run_id": run_id}

@app.get("/api/niches")
def get_niches():
    with db.get_connection() as conn:
        kws = conn.execute("SELECT * FROM keywords ORDER BY opportunity_score DESC LIMIT 50").fetchall()
        trends = conn.execute("SELECT * FROM trends_cache ORDER BY slope_12w DESC LIMIT 50").fetchall()
        return {
            "keywords": [dict(k) for k in kws],
            "trends": [dict(t) for t in trends]
        }

@app.get("/api/reports")
def list_reports():
    reports_dir = Path("reports")
    if not reports_dir.exists():
        return {"reports": []}
    files = []
    for fp in reports_dir.iterdir():
        if fp.is_file():
            files.append({
                "name": fp.name,
                "size_kb": round(fp.stat().st_size / 1024.0, 1),
                "modified": datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc).isoformat()
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"reports": files}

@app.get("/api/reports/view/{filename}")
def view_report_file(filename: str):
    safe_name = Path(filename).name
    fp = Path("reports") / safe_name
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    if safe_name.endswith(".html"):
        return FileResponse(str(fp), media_type="text/html")
    elif safe_name.endswith(".txt"):
        return FileResponse(str(fp), media_type="text/plain")
    elif safe_name.endswith(".csv"):
        return FileResponse(str(fp), media_type="text/csv")
    return FileResponse(str(fp))

# Serve web directory
if Path("web").exists():
    app.mount("/static", StaticFiles(directory="web"), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = Path("web") / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Game Radar Dashboard Web UI</h1>"

def find_free_port(start_port: int = 8765) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port

def start_dashboard(host: str = "127.0.0.1", port: int = 8765):
    free_port = find_free_port(port)
    print(f"[DASHBOARD] Starting FastAPI Dashboard on http://{host}:{free_port}...")
    uvicorn.run(app, host=host, port=free_port, log_level="info")
