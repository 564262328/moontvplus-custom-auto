#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MoonTV Core50 automatic source-pool maintenance.

Design goals:
- Reuse only sources already present in MoonTV plus optional user-approved seeds.
- Keep the original active pool as the long-lived Core anchor.
- Expand/maintain up to TARGET_ACTIVE sources (default 50).
- Require consecutive failures before disabling an active source.
- Require consecutive healthy checks before re-enabling a previously disabled source.
- Never delete source records; only toggle disabled and refresh ConfigFile.api_site.
- Back up admin:config before every production write.
- Roll back the config automatically if MoonTV fails its HTTP health check.
- Avoid changing source config while the application image updater is running.
- Write per-run JSON/CSV/summary reports and persistent health streak state.

Default invocation performs maintenance. Use --dry-run to scan and plan without writes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

KV_CONTAINER = os.getenv("MOONTV_KV_CONTAINER", "moontv-kvrocks")
APP_CONTAINER = os.getenv("MOONTV_APP_CONTAINER", "moontv-core")
KV_PORT = os.getenv("MOONTV_KV_PORT", "6666")
ADMIN_KEY = os.getenv("MOONTV_ADMIN_KEY", "admin:config")
HEALTH_URL = os.getenv("MOONTV_HEALTH_URL", "http://127.0.0.1:8080/")
PROJECT_ROOT = Path(os.getenv("MOONTV_PROJECT_ROOT", "/vol2/1000/Docker/moontvplus-custom"))
MAINT_ROOT = Path(os.getenv("MOONTV_SOURCE_MAINT_ROOT", str(PROJECT_ROOT / "source-maintenance")))
BACKUP_ROOT = Path(os.getenv("MOONTV_SOURCE_BACKUP_ROOT", str(PROJECT_ROOT / "source-config-backups")))
UPDATER_LOCK = Path(os.getenv("MOONTV_UPDATE_LOCK", str(PROJECT_ROOT / "auto-update/state/update.lock")))
STATE_FILE = MAINT_ROOT / "state.json"
CORE_FILE = MAINT_ROOT / "core-anchor.json"
PINS_FILE = MAINT_ROOT / "pins.json"
SEEDS_FILE = MAINT_ROOT / "source-seeds.json"
LOCK_DIR = MAINT_ROOT / ".maintenance.lock"

TARGET_ACTIVE = int(os.getenv("MOONTV_SOURCE_TARGET", "50"))
FAIL_THRESHOLD = int(os.getenv("MOONTV_SOURCE_FAIL_THRESHOLD", "2"))
RECOVER_THRESHOLD = int(os.getenv("MOONTV_SOURCE_RECOVER_THRESHOLD", "2"))
WORKERS = int(os.getenv("MOONTV_SOURCE_WORKERS", "10"))
ATTEMPTS = int(os.getenv("MOONTV_SOURCE_ATTEMPTS", "3"))
CONNECT_TIMEOUT = float(os.getenv("MOONTV_SOURCE_CONNECT_TIMEOUT", "4"))
TOTAL_TIMEOUT = float(os.getenv("MOONTV_SOURCE_TOTAL_TIMEOUT", "8"))
KEEP_RUNS = int(os.getenv("MOONTV_SOURCE_KEEP_RUNS", "30"))
MAX_READ = int(os.getenv("MOONTV_SOURCE_MAX_READ", str(1024 * 1024)))
OK_HTTP = {"200", "301", "302", "307", "308"}
UA = "Mozilla/5.0 (MoonTV-Core50-Maintenance/2.0)"


def run(cmd: List[str], *, input_text: Optional[str] = None, check: bool = True, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and p.returncode != 0:
        raise RuntimeError(
            f"Command failed ({p.returncode}): {' '.join(cmd)}\n"
            f"stdout: {p.stdout.strip()}\n"
            f"stderr: {p.stderr.strip()}"
        )
    return p


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return copy.deepcopy(default)


def normalize_api(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    p = urlsplit(url)
    path = p.path or ""
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def container_exists(name: str) -> bool:
    return run(["docker", "inspect", name], check=False).returncode == 0


def app_running() -> bool:
    p = run(["docker", "inspect", APP_CONTAINER, "--format", "{{.State.Running}}"], check=False)
    return p.returncode == 0 and p.stdout.strip() == "true"


def redis_ping() -> bool:
    p = run(["docker", "exec", KV_CONTAINER, "redis-cli", "-p", KV_PORT, "--raw", "PING"], check=False)
    return p.returncode == 0 and p.stdout.strip() == "PONG"


def redis_get(key: str) -> str:
    p = run(["docker", "exec", KV_CONTAINER, "redis-cli", "-p", KV_PORT, "--raw", "GET", key])
    value = p.stdout.rstrip("\n")
    if not value.strip():
        raise RuntimeError(f"Redis key is empty or missing: {key}")
    return value


def redis_set(key: str, value: str) -> None:
    p = run(
        ["docker", "exec", "-i", KV_CONTAINER, "redis-cli", "-p", KV_PORT, "-x", "SET", key],
        input_text=value,
    )
    if p.stdout.strip() != "OK":
        raise RuntimeError(f"Unexpected Redis SET response: {p.stdout!r}")


def health_check(attempts: int = 45, sleep_seconds: float = 2.0) -> Optional[str]:
    for _ in range(attempts):
        p = run(
            ["curl", "-4", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5", HEALTH_URL],
            check=False,
        )
        code = p.stdout.strip()
        if code in OK_HTTP and app_running():
            return code
        time.sleep(sleep_seconds)
    return None


def safe_config_file(admin: Dict[str, Any]) -> Dict[str, Any]:
    raw = admin.get("ConfigFile", "")
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return {}


def detect_format(body: bytes, content_type: str) -> Tuple[str, bool, Optional[int]]:
    text = body.decode("utf-8", errors="ignore").lstrip()
    if not text:
        return "empty", False, None

    ctype = (content_type or "").lower()
    if text.startswith("{") or "json" in ctype:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                count = len(obj.get("list", [])) if isinstance(obj.get("list"), list) else None
                if "code" in obj and ("list" in obj or "class" in obj):
                    return "json/maccms-vod", True, count
                return "json", False, count
        except Exception:
            pass

    if text.startswith("<") or "xml" in ctype or "html" in ctype:
        low = text[:20000].lower()
        if any(tag in low for tag in ("<rss", "<list", "<video", "<vod")):
            return "xml/maccms-like", True, None
        return "xml", False, None

    return "unknown", False, None


def classify_curl_error(stderr: str, returncode: int) -> str:
    low = (stderr or "").lower()
    if returncode == 6 or "could not resolve host" in low:
        return "dns"
    if returncode == 28 or "timed out" in low or "timeout" in low:
        return "timeout"
    if returncode in (35, 51, 53, 58, 60) or "ssl" in low or "tls" in low or "certificate" in low:
        return "tls"
    if returncode == 7 or "failed to connect" in low or "connection refused" in low:
        return "connect"
    if "reset by peer" in low:
        return "reset"
    return "curl"


def curl_probe(url: str) -> Dict[str, Any]:
    started = time.perf_counter()
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="moontv-src-", delete=False) as tmp:
            tmp_name = tmp.name

        marker = "__MOONTV_META__"
        cmd = [
            "curl", "-4", "-L", "-sS", "--compressed",
            "--connect-timeout", str(CONNECT_TIMEOUT),
            "--max-time", str(TOTAL_TIMEOUT),
            "-A", UA,
            "-H", "Accept: application/json,text/xml,text/html,*/*",
            "-o", tmp_name,
            "-w", f"{marker}%{{http_code}}\t%{{content_type}}\t%{{url_effective}}\t%{{time_total}}",
            url,
        ]
        try:
            p = run(cmd, check=False, timeout=TOTAL_TIMEOUT + 3)
        except subprocess.TimeoutExpired:
            return {
                "ok": False, "http_status": 0, "latency_ms": int((time.perf_counter() - started) * 1000),
                "final_url": url, "content_type": "", "format": "", "items": None,
                "error_type": "timeout", "error": "hard subprocess timeout",
            }

        elapsed = int((time.perf_counter() - started) * 1000)
        meta = p.stdout.split(marker)[-1] if marker in p.stdout else ""
        parts = meta.split("\t")
        status = int(parts[0]) if parts and parts[0].isdigit() else 0
        ctype = parts[1] if len(parts) > 1 else ""
        final_url = parts[2] if len(parts) > 2 and parts[2] else url

        body = b""
        try:
            with open(tmp_name, "rb") as fh:
                body = fh.read(MAX_READ)
        except Exception:
            pass

        fmt, maccms, item_count = detect_format(body, ctype)
        ok = p.returncode == 0 and status == 200 and maccms
        return {
            "ok": ok,
            "http_status": status,
            "latency_ms": elapsed,
            "final_url": final_url,
            "content_type": ctype,
            "format": fmt,
            "items": item_count,
            "error_type": "" if p.returncode == 0 else classify_curl_error(p.stderr, p.returncode),
            "error": (p.stderr or "").strip()[:500],
        }
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def check_source(src: Dict[str, Any]) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for _ in range(max(1, ATTEMPTS)):
        attempts.append(curl_probe(src["api"]))

    good = [x for x in attempts if x["ok"]]
    latencies = [int(x.get("latency_ms") or 999999) for x in attempts]
    median_ms = int(statistics.median(latencies)) if latencies else 999999
    success_rate = len(good) / max(1, len(attempts))
    representative = good[-1] if good else attempts[-1]
    healthy = success_rate >= (2 / 3 if ATTEMPTS >= 3 else 1.0)

    if healthy and success_rate == 1.0:
        grade = "A"
    elif healthy:
        grade = "B"
    else:
        grade = "F"

    return {
        **src,
        "normalized_api": normalize_api(src.get("api", "")),
        "host": urlsplit(src.get("api", "")).netloc.lower(),
        "healthy": healthy,
        "grade": grade,
        "success_rate": round(success_rate, 3),
        "median_ms": median_ms,
        "http_status": representative.get("http_status", 0),
        "final_url": representative.get("final_url", src.get("api", "")),
        "content_type": representative.get("content_type", ""),
        "format": representative.get("format", ""),
        "items_in_first_response": representative.get("items"),
        "error_type": "" if healthy else representative.get("error_type", ""),
        "error": "" if healthy else representative.get("error", ""),
        "attempt_ms": ",".join(str(x.get("latency_ms", "")) for x in attempts),
    }


def parse_seed_file(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    obj = load_json(path, [])
    raw: Iterable[Any]
    if isinstance(obj, list):
        raw = obj
    elif isinstance(obj, dict) and isinstance(obj.get("sources"), list):
        raw = obj["sources"]
    elif isinstance(obj, dict) and isinstance(obj.get("api_site"), dict):
        raw = [dict(v, key=k) for k, v in obj["api_site"].items() if isinstance(v, dict)]
    else:
        return []

    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        api = str(item.get("api", "")).strip()
        name = str(item.get("name", "")).strip()
        if not api or not name:
            continue
        out.append({
            "key": str(item.get("key", "")).strip(),
            "name": name,
            "api": api,
            "detail": str(item.get("detail", "") or "").strip(),
            "from": "seed",
            "disabled": True,
        })
    return out


def build_pool(admin: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    current = admin.get("SourceConfig") if isinstance(admin.get("SourceConfig"), list) else []
    by_api: Dict[str, Dict[str, Any]] = {}
    ordered: List[Dict[str, Any]] = []

    for item in current:
        if not isinstance(item, dict):
            continue
        api = normalize_api(str(item.get("api", "")))
        if not api or api in by_api:
            continue
        row = copy.deepcopy(item)
        row["api"] = str(row.get("api", "")).strip()
        row["name"] = str(row.get("name", "")).strip() or str(row.get("key", ""))
        row["detail"] = str(row.get("detail", "") or "").strip()
        row["was_active"] = not bool(row.get("disabled", False))
        row["origin"] = "existing"
        by_api[api] = row
        ordered.append(row)

    for seed in parse_seed_file(SEEDS_FILE):
        api = normalize_api(seed["api"])
        if api in by_api:
            continue
        row = copy.deepcopy(seed)
        row["was_active"] = False
        row["origin"] = "seed"
        by_api[api] = row
        ordered.append(row)

    return ordered, by_api


def load_pins() -> Tuple[set, set]:
    obj = load_json(PINS_FILE, {})
    if isinstance(obj, list):
        return set(str(x) for x in obj), set()
    if not isinstance(obj, dict):
        return set(), set()
    keys = {str(x) for x in obj.get("keys", []) if str(x).strip()}
    apis = {normalize_api(str(x)) for x in obj.get("apis", []) if normalize_api(str(x))}
    return keys, apis


def ensure_core_anchor(pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    if CORE_FILE.exists():
        obj = load_json(CORE_FILE, {})
        if isinstance(obj, dict):
            return obj

    active = [x for x in pool if x.get("was_active")]
    obj = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "description": "Sources active when Core50 automation was first installed; preferred while healthy.",
        "apis": [normalize_api(x.get("api", "")) for x in active if normalize_api(x.get("api", ""))],
        "keys": [str(x.get("key", "")) for x in active if str(x.get("key", "")).strip()],
    }
    atomic_write_json(CORE_FILE, obj)
    return obj


def update_streak_state(rows: List[Dict[str, Any]], old_state: Dict[str, Any]) -> Dict[str, Any]:
    sources_state = old_state.get("sources") if isinstance(old_state.get("sources"), dict) else {}
    now = dt.datetime.now().isoformat(timespec="seconds")

    for row in rows:
        api = row["normalized_api"]
        prev = sources_state.get(api) if isinstance(sources_state.get(api), dict) else {}
        if row["healthy"]:
            success_streak = int(prev.get("success_streak", 0)) + 1
            fail_streak = 0
            last_success = now
            last_failure = prev.get("last_failure")
        else:
            success_streak = 0
            fail_streak = int(prev.get("fail_streak", 0)) + 1
            last_success = prev.get("last_success")
            last_failure = now

        sources_state[api] = {
            "name": row.get("name", ""),
            "key": row.get("key", ""),
            "success_streak": success_streak,
            "fail_streak": fail_streak,
            "last_success": last_success,
            "last_failure": last_failure,
            "last_grade": row.get("grade", ""),
            "last_median_ms": row.get("median_ms"),
            "last_success_rate": row.get("success_rate"),
        }
        row["success_streak"] = success_streak
        row["fail_streak"] = fail_streak

    return {
        "version": 2,
        "updated_at": now,
        "target_active": TARGET_ACTIVE,
        "fail_threshold": FAIL_THRESHOLD,
        "recover_threshold": RECOVER_THRESHOLD,
        "sources": sources_state,
    }


def candidate_priority(row: Dict[str, Any], *, core_apis: set, pinned_keys: set, pinned_apis: set, bootstrap: bool) -> Tuple:
    api = row["normalized_api"]
    key = str(row.get("key", ""))
    pinned = key in pinned_keys or api in pinned_apis
    core = api in core_apis
    was_active = bool(row.get("was_active"))
    healthy = bool(row.get("healthy"))
    fail_streak = int(row.get("fail_streak", 0))
    success_streak = int(row.get("success_streak", 0))

    if pinned:
        eligible = True
    elif was_active:
        eligible = healthy or fail_streak < FAIL_THRESHOLD
    else:
        eligible = healthy and (bootstrap or success_streak >= RECOVER_THRESHOLD)

    row["pinned"] = pinned
    row["core_anchor"] = core
    row["eligible"] = eligible

    # Lower tuple sorts first. Preserve pinned/core/incumbents, then speed.
    return (
        0 if eligible else 1,
        0 if pinned else 1,
        0 if core else 1,
        0 if was_active else 1,
        0 if healthy else 1,
        int(row.get("median_ms") or 999999),
        -int(row.get("items_in_first_response") or 0),
        str(row.get("name", "")),
    )


def choose_sources(rows: List[Dict[str, Any]], core_anchor: Dict[str, Any], pinned_keys: set, pinned_apis: set, bootstrap: bool) -> List[Dict[str, Any]]:
    core_apis = {normalize_api(str(x)) for x in core_anchor.get("apis", []) if normalize_api(str(x))}
    ranked = sorted(rows, key=lambda r: candidate_priority(
        r,
        core_apis=core_apis,
        pinned_keys=pinned_keys,
        pinned_apis=pinned_apis,
        bootstrap=bootstrap,
    ))

    eligible = [r for r in ranked if r.get("eligible")]
    pinned = [r for r in eligible if r.get("pinned")]
    others = [r for r in eligible if not r.get("pinned")]

    selected: List[Dict[str, Any]] = []
    seen = set()
    for row in pinned + others:
        api = row["normalized_api"]
        if api in seen:
            continue
        selected.append(row)
        seen.add(api)
        if len(selected) >= max(TARGET_ACTIVE, len(pinned)):
            break
    return selected


def generated_key(api: str, used: set) -> str:
    base = "auto_" + hashlib.sha1(api.encode("utf-8")).hexdigest()[:10]
    key = base
    i = 2
    while key in used:
        key = f"{base}_{i}"
        i += 1
    return key


def make_admin_plan(admin: Dict[str, Any], selected: List[Dict[str, Any]]) -> Dict[str, Any]:
    current = admin.get("SourceConfig") if isinstance(admin.get("SourceConfig"), list) else []
    by_api: Dict[str, Dict[str, Any]] = {}
    used_keys = set()
    for item in current:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if key:
            used_keys.add(key)
        api = normalize_api(str(item.get("api", "")))
        if api and api not in by_api:
            by_api[api] = item

    active_entries: List[Dict[str, Any]] = []
    selected_apis = set()
    selected_keys = set()
    for row in selected:
        api_norm = row["normalized_api"]
        selected_apis.add(api_norm)
        old = by_api.get(api_norm)
        entry = copy.deepcopy(old) if old else {
            "key": str(row.get("key", "")).strip() or generated_key(api_norm, used_keys | selected_keys)
        }
        key = str(entry.get("key", "")).strip()
        if not key:
            key = generated_key(api_norm, used_keys | selected_keys)
        entry.update({
            "key": key,
            "name": str(row.get("name", "")).strip(),
            "api": str(row.get("api", "")).strip(),
            "detail": str(row.get("detail", "") or "").strip(),
            "from": "config",
            "disabled": False,
        })
        active_entries.append(entry)
        selected_keys.add(key)

    disabled_entries: List[Dict[str, Any]] = []
    for old in current:
        if not isinstance(old, dict):
            continue
        api_norm = normalize_api(str(old.get("api", "")))
        key = str(old.get("key", "")).strip()
        if api_norm in selected_apis or key in selected_keys:
            continue
        entry = copy.deepcopy(old)
        entry["disabled"] = True
        entry["from"] = "custom"
        disabled_entries.append(entry)

    new_admin = copy.deepcopy(admin)
    new_admin["SourceConfig"] = active_entries + disabled_entries

    file_cfg = safe_config_file(admin)
    file_cfg["api_site"] = {
        entry["key"]: {
            "name": entry["name"],
            "api": entry["api"],
            "detail": entry.get("detail", ""),
        }
        for entry in active_entries
    }
    new_admin["ConfigFile"] = json.dumps(file_cfg, ensure_ascii=False, separators=(",", ":"))
    return new_admin


def active_api_set(admin: Dict[str, Any]) -> set:
    sources = admin.get("SourceConfig") if isinstance(admin.get("SourceConfig"), list) else []
    return {
        normalize_api(str(x.get("api", "")))
        for x in sources
        if isinstance(x, dict) and not x.get("disabled", False) and normalize_api(str(x.get("api", "")))
    }


def apply_admin_with_rollback(before_raw: str, after_admin: Dict[str, Any], backup_dir: Path) -> str:
    after_raw = json.dumps(after_admin, ensure_ascii=False, separators=(",", ":"))
    (backup_dir / "admin-config.before.json").write_text(before_raw, encoding="utf-8")
    (backup_dir / "admin-config.after.json").write_text(after_raw, encoding="utf-8")

    stopped = False
    try:
        p = run(["docker", "stop", APP_CONTAINER], check=False)
        if p.returncode != 0:
            raise RuntimeError(f"Could not stop {APP_CONTAINER}: {p.stderr.strip()}")
        stopped = True
        redis_set(ADMIN_KEY, after_raw)
    finally:
        if stopped:
            run(["docker", "start", APP_CONTAINER], check=False)

    code = health_check()
    if code:
        return code

    print("WARNING: new source config failed MoonTV health check; restoring previous admin:config...", file=sys.stderr)
    try:
        run(["docker", "stop", APP_CONTAINER], check=False)
        redis_set(ADMIN_KEY, before_raw)
    finally:
        run(["docker", "start", APP_CONTAINER], check=False)

    rollback_code = health_check()
    if not rollback_code:
        raise RuntimeError("Source config update failed and automatic config rollback did not restore MoonTV health.")
    raise RuntimeError(f"Source config update failed health check; previous admin:config restored successfully (HTTP={rollback_code}).")


def write_reports(run_dir: Path, rows: List[Dict[str, Any]], selected: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_dir / "scan.json", rows)
    atomic_write_json(run_dir / "selected.json", selected)
    atomic_write_json(run_dir / "summary.json", summary)

    fields = [
        "key", "name", "api", "host", "was_active", "healthy", "grade", "success_rate",
        "median_ms", "http_status", "format", "items_in_first_response", "success_streak",
        "fail_streak", "core_anchor", "pinned", "eligible", "error_type", "error", "attempt_ms",
    ]
    with (run_dir / "scan.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    lines = [
        "MoonTV Core50 source maintenance",
        f"time={summary['time']}",
        f"pool={summary['pool_count']}",
        f"healthy_now={summary['healthy_now']}",
        f"active_before={summary['active_before']}",
        f"selected={summary['selected_count']}",
        f"changed={summary['changed']}",
        f"bootstrap={summary['bootstrap']}",
        f"http={summary.get('http', '')}",
        "",
        "Selected sources:",
    ]
    for idx, row in enumerate(selected, 1):
        lines.append(
            f"{idx:02d}. {row.get('name','')} | grade={row.get('grade')} | "
            f"median={row.get('median_ms')}ms | core={row.get('core_anchor')} | "
            f"active_before={row.get('was_active')}"
        )
    (run_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prune_runs() -> None:
    if KEEP_RUNS <= 0 or not MAINT_ROOT.exists():
        return
    dirs = [p for p in MAINT_ROOT.iterdir() if p.is_dir() and p.name[:8].isdigit()]
    dirs.sort(key=lambda p: p.name, reverse=True)
    for old in dirs[KEEP_RUNS:]:
        shutil.rmtree(old, ignore_errors=True)


def acquire_lock() -> None:
    MAINT_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        LOCK_DIR.mkdir()
    except FileExistsError:
        raise SystemExit("Another MoonTV source-maintenance process appears to be running.")
    (LOCK_DIR / "pid").write_text(str(os.getpid()), encoding="ascii")


def release_lock() -> None:
    shutil.rmtree(LOCK_DIR, ignore_errors=True)


def main() -> int:
    global TARGET_ACTIVE
    ap = argparse.ArgumentParser(description="MoonTV Core50 automatic source-pool maintenance")
    ap.add_argument("--dry-run", action="store_true", help="scan and plan but do not change admin:config")
    ap.add_argument("--target", type=int, default=TARGET_ACTIVE, help="target active source count")
    args = ap.parse_args()

    TARGET_ACTIVE = max(1, args.target)

    if UPDATER_LOCK.exists():
        print(f"MoonTV application updater is still running ({UPDATER_LOCK}); source maintenance skipped safely.")
        return 0

    acquire_lock()
    try:
        if not container_exists(KV_CONTAINER):
            raise RuntimeError(f"container not found: {KV_CONTAINER}")
        if not container_exists(APP_CONTAINER):
            raise RuntimeError(f"container not found: {APP_CONTAINER}")
        if not redis_ping():
            raise RuntimeError("Kvrocks PING failed")
        if not app_running():
            raise RuntimeError("MoonTV app container is not running; refusing to alter source config")

        before_raw = redis_get(ADMIN_KEY)
        admin = json.loads(before_raw)
        pool, _ = build_pool(admin)
        if not pool:
            raise RuntimeError("SourceConfig contains no usable sources")

        core_anchor = ensure_core_anchor(pool)
        pinned_keys, pinned_apis = load_pins()
        old_state = load_json(STATE_FILE, {})
        bootstrap = not bool(old_state.get("sources"))

        print("===== MoonTV Core50 source maintenance =====")
        print(f"Pool: {len(pool)} | Current active: {len(active_api_set(admin))} | Target: {TARGET_ACTIVE}")
        print(f"Core anchor: {len(core_anchor.get('apis', []))} | Bootstrap: {bootstrap}")
        print(f"Checks: attempts={ATTEMPTS}, workers={WORKERS}, timeout={TOTAL_TIMEOUT}s")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, WORKERS)) as ex:
            rows = list(ex.map(check_source, pool))

        state = update_streak_state(rows, old_state)
        selected = choose_sources(rows, core_anchor, pinned_keys, pinned_apis, bootstrap)
        selected_apis = {x["normalized_api"] for x in selected}
        before_active = active_api_set(admin)
        changed = before_active != selected_apis

        now = dt.datetime.now()
        stamp = now.strftime("%Y%m%d-%H%M%S")
        run_dir = MAINT_ROOT / stamp
        backup_dir = BACKUP_ROOT / stamp
        healthy_now = sum(1 for x in rows if x.get("healthy"))
        summary = {
            "time": now.isoformat(timespec="seconds"),
            "pool_count": len(rows),
            "healthy_now": healthy_now,
            "active_before": len(before_active),
            "selected_count": len(selected),
            "changed": changed,
            "bootstrap": bootstrap,
            "target": TARGET_ACTIVE,
            "http": "",
        }

        print(f"Healthy now: {healthy_now}/{len(rows)}")
        print(f"Selected: {len(selected)}")
        print(f"Config change needed: {'YES' if changed else 'NO'}")

        if args.dry_run:
            summary["dry_run"] = True
            write_reports(run_dir, rows, selected, summary)
            print(f"DRY RUN ONLY. Report: {run_dir}")
            return 0

        if changed:
            new_admin = make_admin_plan(admin, selected)
            backup_dir.mkdir(parents=True, exist_ok=False)
            code = apply_admin_with_rollback(before_raw, new_admin, backup_dir)
            summary["http"] = code
            print(f"SOURCE POOL UPDATE SUCCESS: active={len(selected)}, HTTP={code}")
            print(f"Rollback copy: {backup_dir / 'admin-config.before.json'}")
        else:
            code = health_check(attempts=3, sleep_seconds=1)
            summary["http"] = code or ""
            print("Source pool already matches the current selection; no app restart needed.")

        # Persist streaks only after a completed maintenance cycle.
        atomic_write_json(STATE_FILE, state)
        write_reports(run_dir, rows, selected, summary)
        (MAINT_ROOT / "latest-run").write_text(str(run_dir) + "\n", encoding="utf-8")
        prune_runs()
        print(f"Report: {run_dir}")
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
