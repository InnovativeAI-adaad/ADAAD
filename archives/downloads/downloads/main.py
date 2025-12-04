#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADAAD main.py — Enhanced Autonomous Orchestrator (BEAST-MODE ready, Pydroid3-friendly)

Drop-in replacement: robust, self-healing, cryovant-backed, dream+beast+dna integrated,
warm pool preloader, quarantining and repair flows, sandboxed execution and safe fallbacks.

Usage:
    python3 main.py          # run orchestrator (daemon loop)
    python3 main.py --once   # run one full orchestrator cycle then exit
    python3 main.py --cli    # interactive CLI (list/create/repair/inspect)
"""
from __future__ import annotations
import sys, os, time, json, uuid, shutil, tempfile, random, traceback, hashlib, hmac
from multiprocessing import Process
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

# ---------------------------
# Configurable root / discovery
# ---------------------------
DEFAULT_APP_HOME = "/storage/emulated/0/ADAAD"
APP_HOME = os.environ.get("ADAAD_HOME", DEFAULT_APP_HOME)

# candidate parent folders to find core/
_CANDIDATES = [
    APP_HOME,
    os.path.join(APP_HOME, "ADAAD"),
    os.path.join(APP_HOME, "src"),
    os.path.join(APP_HOME, "app"),
]

def locate_core_dir() -> Path:
    # check common candidates
    for base in _CANDIDATES:
        cand = Path(base) / "core"
        if cand.is_dir():
            return cand.resolve()
    # shallow walk depth=2
    for root, dirs, files in os.walk(APP_HOME):
        rel = os.path.relpath(root, APP_HOME)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > 2:
            dirs[:] = []
            continue
        if "core" in dirs:
            return Path(root) / "core"
    # fallback: ensure core exists
    c = Path(APP_HOME) / "core"
    c.mkdir(parents=True, exist_ok=True)
    return c.resolve()

DIR_CORE = locate_core_dir()
CORE_PARENT = DIR_CORE.parent
# put parent and app home in front of sys.path so `import core.*` works
if str(CORE_PARENT) not in sys.path:
    sys.path.insert(0, str(CORE_PARENT))
if APP_HOME not in sys.path:
    sys.path.insert(0, APP_HOME)

# ---------------------------
# Paths and logs
# ---------------------------
DIR_AGENTS = Path(APP_HOME) / "agents"
DIR_SCAFFOLDS = Path(APP_HOME) / "scaffolds"
DIR_LOGS = Path(APP_HOME) / "logs"
DIR_ARCHIVE = Path(APP_HOME) / "archive"
DIR_CONFIG = Path(APP_HOME) / "config"
DIR_PLUGINS = Path(APP_HOME) / "plugins"
DIR_PIDS = Path(APP_HOME) / "pids"
DIR_QUARANTINE = Path(APP_HOME) / "quarantine"

for d in (DIR_AGENTS, DIR_SCAFFOLDS, DIR_LOGS, DIR_ARCHIVE, DIR_CONFIG, DIR_PLUGINS, DIR_PIDS, DIR_QUARANTINE):
    d.mkdir(parents=True, exist_ok=True)

REGISTRY_FILE = DIR_LOGS / "registry.json"
LINEAGE_FILE = DIR_LOGS / "lineage.jsonl"
FITNESS_FILE = DIR_LOGS / "fitness.jsonl"
MAIN_LOG = DIR_LOGS / "main.log"
LOCK_FILE = DIR_LOGS / ".lock"
CONFIG_FILE = DIR_CONFIG / "config.json"
CRYOVANT_REGISTRY = DIR_LOGS / "cryovant_registry.json"
CRYOVANT_KEY = DIR_CORE / "cryovant_key.bin"   # HMAC key fallback

# ---------------------------
# Defaults
# ---------------------------
DEFAULT_CONFIG = {
    "version": "1.0",
    "agent_timeout_sec": 8,
    "sandbox": {"rlimit_cpu_sec": 6, "rlimit_mem_mb": 200},
    "max_scaffolds": 300,
    "survival_top_k": 5,
    "daemon_sleep_sec": 6,
    "scan_ignore": [".git", "__pycache__"],
    "parallel_score_workers": 2,
    "verbose": True,
    "log_rotate_mb": 12,
    "dashboard_port": 8001,
    "worker_port": 8000,
    "warm_pool_size": 5,
    "beast_top_k": 3
}

# ---------------------------
# Utilities
# ---------------------------
def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _safe_print(*a, **k):
    try:
        if CONFIG.get("verbose", True):
            print(*a, **k)
    except Exception:
        print(*a, **k)

def _write_atomic(path: Path, obj: Any):
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        tmp.replace(path)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            tmp.replace(path)
        except Exception:
            pass

def _append_jsonline(path: Path, obj: Any):
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")
    except Exception:
        pass

def _sha256_file(p: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

# ---------------------------
# Load configuration
# ---------------------------
CONFIG: Dict[str, Any] = {}
try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {}
for k, v in DEFAULT_CONFIG.items():
    CONFIG.setdefault(k, v)

# rotate main log
def _rotate_if_needed(path: Path, max_mb: int):
    try:
        if not path.exists(): return
        size_mb = path.stat().st_size / (1024.0*1024.0)
        if size_mb > max_mb:
            bak = path.with_name(path.name + "." + now_ts().replace(":", "-") + ".bak")
            try: path.replace(bak)
            except Exception: pass
    except Exception:
        pass
_rotate_if_needed(MAIN_LOG, CONFIG.get("log_rotate_mb", 12))

# ---------------------------
# Multiprocess sandboxed call (safe worker)
# ---------------------------
try:
    import resource
except Exception:
    resource = None

def _import_by_path(name: str, path: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise ImportError("bad spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _worker_file(module_path: str, func_name: str, args: tuple, kwargs: dict, tmp_file: str):
    try:
        tmpd = os.path.join(tempfile.gettempdir(), "adaad_run_" + uuid.uuid4().hex[:6])
        os.makedirs(tmpd, exist_ok=True)
        os.chdir(tmpd)
        if resource:
            try:
                r_cpu = int(CONFIG.get("sandbox", {}).get("rlimit_cpu_sec", 6))
                r_mem_mb = int(CONFIG.get("sandbox", {}).get("rlimit_mem_mb", 200))
                resource.setrlimit(resource.RLIMIT_CPU, (r_cpu, r_cpu + 1))
                soft_as = r_mem_mb * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (soft_as, soft_as))
                except Exception:
                    pass
            except Exception:
                pass
        mod = _import_by_path("__cv_agent__", module_path)
        if not hasattr(mod, func_name):
            _write_atomic(Path(tmp_file), {"ok": False, "error": f"missing:{func_name}"})
            return
        res = getattr(mod, func_name)(*args, **kwargs)
        _write_atomic(Path(tmp_file), {"ok": True, "result": res})
    except Exception as e:
        _write_atomic(Path(tmp_file), {"ok": False, "error": str(e), "traceback": traceback.format_exc()})

def call_agent_safe(module_path: str, func_name: str, timeout: Optional[int] = None, *args, **kwargs) -> Dict[str, Any]:
    if timeout is None:
        timeout = int(CONFIG.get("agent_timeout_sec", 8))
    tmp_file = os.path.join(tempfile.gettempdir(), f"adaad_result_{uuid.uuid4().hex}.json")
    p = Process(target=_worker_file, args=(module_path, func_name, args, kwargs, tmp_file))
    p.daemon = True
    t0 = time.time()
    try:
        p.start()
        p.join(timeout)
    except Exception:
        try: p.terminate()
        except Exception: pass
        return {"ok": False, "error": "multiprocess-start-failed", "runtime": 0.0}
    runtime = time.time() - t0
    if p.is_alive():
        try: p.terminate()
        except Exception: pass
        return {"ok": False, "error": "timeout", "runtime": runtime}
    if os.path.exists(tmp_file):
        try:
            with open(tmp_file, "r", encoding="utf-8") as f:
                out = json.load(f)
            out["runtime"] = runtime
            try: os.remove(tmp_file)
            except Exception: pass
            return out
        except Exception:
            return {"ok": False, "error": "file-read-failed", "runtime": runtime}
    return {"ok": False, "error": "no-response", "runtime": runtime}

# ---------------------------
# Registry & discovery (agents)
# ---------------------------
REQUIRED_METHODS = ["info", "run", "mutate", "score"]

def find_agents(base: Path = DIR_AGENTS) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    if not base.exists(): return items
    for name in sorted(os.listdir(base)):
        if name.startswith(".") or name in CONFIG.get("scan_ignore", []): continue
        full = os.path.join(base, name)
        if os.path.isdir(full):
            init = os.path.join(full, "__init__.py")
            if os.path.exists(init):
                items.append((name, init))
        elif os.path.isfile(full) and name.endswith(".py"):
            items.append((name[:-3], full))
    return items

def probe_agent(aid: str, path: str) -> Dict[str, Any]:
    entry = {"id": aid, "path": path, "last_seen": now_ts(), "loaded": False, "missing_methods": []}
    entry["checksum"] = _sha256_file(Path(path))
    try:
        mod = _import_by_path("__probe__", path)
        missing = [m for m in REQUIRED_METHODS if not hasattr(mod, m) or not callable(getattr(mod, m))]
        entry["missing_methods"] = missing
        entry["loaded"] = len(missing) == 0
        if entry["loaded"]:
            info_res = call_agent_safe(path, "info", timeout=int(CONFIG.get("agent_timeout_sec", 6)))
            if info_res.get("ok"): entry["info"] = info_res.get("result")
            else: entry["info_error"] = info_res.get("error")
    except Exception as e:
        entry["import_error"] = str(e)
    return entry

def update_registry(base: Path = DIR_AGENTS, registry_path: Path = REGISTRY_FILE) -> Dict[str,Any]:
    prev = load_registry(registry_path)
    prev_agents = prev.get("agents", {}) if prev else {}
    found = find_agents(base)
    new_registry = {"generated_at": now_ts(), "agents": {}}
    seen = set()
    for aid, path in found:
        seen.add(aid)
        try:
            entry = probe_agent(aid, path)
        except Exception as e:
            entry = {"id": aid, "path": path, "error": str(e)}
        new_registry["agents"][aid] = entry
    removed = [k for k in prev_agents.keys() if k not in seen]
    if removed: new_registry["_removed"] = removed
    _write_atomic(registry_path, new_registry)
    _safe_print("[registry] updated:", registry_path)
    return new_registry

def load_registry(path: Path = REGISTRY_FILE) -> Dict[str,Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"generated_at": None, "agents": {}}

# ---------------------------
# Cryovant — simple CA fallback (HMAC-based)
# ---------------------------
def _ensure_cryovant_key():
    try:
        if not CRYOVANT_KEY.exists():
            k = os.urandom(32)
            with CRYOVANT_KEY.open("wb") as f:
                f.write(k)
            CRYOVANT_KEY.chmod(0o600)
        with CRYOVANT_KEY.open("rb") as f:
            return f.read()
    except Exception:
        # fallback deterministic key — not ideal but keeps system bootable
        return hashlib.sha256(b"adaad-fallback-key").digest()

CRYOVANT_KEY_BYTES = _ensure_cryovant_key()

def cryovant_register(agent_path: Path) -> Dict[str, Any]:
    """Register agent and return record (writes to CRYOVANT_REGISTRY)."""
    try:
        h = _sha256_file(agent_path)
        if not h:
            raise RuntimeError("could-not-hash")
        sig = hmac.new(CRYOVANT_KEY_BYTES, h.encode("utf-8"), hashlib.sha256).hexdigest()
        rec = {"path": str(agent_path), "sha256": h, "sig": sig, "ts": now_ts()}
        # load existing
        try:
            data = json.loads(CRYOVANT_REGISTRY.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {"agents": []}
        # dedupe
        data["agents"] = [a for a in data.get("agents", []) if a.get("path") != str(agent_path)]
        data.setdefault("agents", []).append(rec)
        try:
            CRYOVANT_REGISTRY.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"ok": True, "rec": rec}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def cryovant_verify(agent_path: Path) -> bool:
    try:
        h = _sha256_file(agent_path)
        if not h: return False
        try:
            data = json.loads(CRYOVANT_REGISTRY.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {"agents": []}
        for rec in data.get("agents", []):
            if rec.get("path") == str(agent_path) and rec.get("sha256") == h:
                expected = hmac.new(CRYOVANT_KEY_BYTES, h.encode("utf-8"), hashlib.sha256).hexdigest()
                return hmac.compare_digest(expected, rec.get("sig", ""))
        return False
    except Exception:
        return False

def cryovant_revoke(agent_path: Path):
    try:
        data = json.loads(CRYOVANT_REGISTRY.read_text(encoding="utf-8") or "{}")
    except Exception:
        data = {"agents": []}
    data["agents"] = [a for a in data.get("agents", []) if a.get("path") != str(agent_path)]
    try:
        CRYOVANT_REGISTRY.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

# ---------------------------
# Quarantine & repair behavior
# ---------------------------
def quarantine_agent(agent_path: Path, reason: str = "untrusted"):
    try:
        dst = DIR_QUARANTINE / f"{agent_path.name}.{int(time.time())}"
        shutil.move(str(agent_path), str(dst))
        _safe_print("[quarantine] moved", agent_path, "->", dst, "reason:", reason)
        return {"ok": True, "path": str(dst)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# repair fallback: attempt to re-create from scaffold or remove problematic parts.
def attempt_repair(agent_path: Path) -> Dict[str, Any]:
    # Try to call agent.repair() if exists
    try:
        res = call_agent_safe(str(agent_path), "repair", timeout=6)
        if res.get("ok"):
            # re-register after repair
            cryovant_register(agent_path)
            return {"ok": True, "repaired": True, "detail": res.get("result")}
        else:
            # attempt simple auto-fix: move to quarantine
            quarantine_agent(agent_path, reason="repair_failed")
            return {"ok": False, "error": res.get("error")}
    except Exception as e:
        quarantine_agent(agent_path, reason="repair_exception")
        return {"ok": False, "error": str(e)}

# ---------------------------
# Scoring & fitness (fallback)
# ---------------------------
def score_agent(agent_id: str) -> Dict[str, Any]:
    reg = load_registry()
    info = reg.get("agents", {}).get(agent_id)
    if not info:
        return {"ok": False, "error": "not-found"}
    path = Path(info.get("path"))
    # verify first
    if not cryovant_verify(path):
        _append_jsonline(FITNESS_FILE, {"agent_id": agent_id, "score": 0.0, "runtime": 0.0, "ts": now_ts()})
        return {"ok": False, "error": "unverified"}
    res = call_agent_safe(str(path), "score", timeout=int(CONFIG.get("agent_timeout_sec", 8)))
    if res.get("ok"):
        try:
            s = float(res.get("result"))
        except Exception:
            s = 0.0
        _append_jsonline(FITNESS_FILE, {"agent_id": agent_id, "score": s, "runtime": res.get("runtime"), "ts": now_ts()})
        return {"ok": True, "score": s}
    else:
        # fallback: run() and assign heuristic score
        runres = call_agent_safe(str(path), "run", timeout=int(CONFIG.get("agent_timeout_sec", 8)))
        runtime = float(runres.get("runtime", 0.0))
        _append_jsonline(FITNESS_FILE, {"agent_id": agent_id, "score": 0.0, "runtime": runtime, "ts": now_ts()})
        return {"ok": False, "error": res.get("error", "score_failed")}

# ---------------------------
# Mutate / evolve (Beast Mode helpers)
# ---------------------------
def mutate_agent_by_id(agent_id: str) -> Dict[str, Any]:
    reg = load_registry()
    info = reg.get("agents", {}).get(agent_id)
    if not info: return {"ok": False, "error": "not-found"}
    path = Path(info.get("path"))
    # try to call mutate
    res = call_agent_safe(str(path), "mutate", timeout=int(CONFIG.get("agent_timeout_sec", 8)))
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error")}
    child = res.get("result") or res.get("child")
    if not child:
        return {"ok": False, "error": "no-child"}
    # child expected to be a dict with id & source
    # promote -> write to scaffolds
    try:
        scaf_id = child.get("id", str(uuid.uuid4()))
        dst = DIR_SCAFFOLDS / scaf_id
        dst.mkdir(parents=True, exist_ok=True)
        art = dst / "child.json"
        _write_atomic(art, child)
        _append_jsonline(LINEAGE_FILE, {"parent": agent_id, "child": scaf_id, "ts": now_ts()})
        return {"ok": True, "child": child, "scaffold": str(art)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Beast Mode: select top K and mutate/promote
def beast_mode_cycle(top_k: int = None):
    if top_k is None:
        top_k = int(CONFIG.get("beast_top_k", 3))
    # read fitness file (last score per agent)
    try:
        if not FITNESS_FILE.exists():
            return {"ok": False, "error": "no_fitness"}
        scores = {}
        with FITNESS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    scores[rec["agent_id"]] = rec["score"]
                except Exception:
                    pass
        # pick top k
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for aid, sc in top:
            res = mutate_agent_by_id(aid)
            results.append({"agent": aid, "score": sc, "mutate": res})
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------------------------
# Dream Mode integration (attempt import or fallback)
# ---------------------------
def start_dream_mode() -> Optional[Any]:
    try:
        import importlib
        dm = importlib.import_module("core.dream_mode")
        if hasattr(dm, "start"):
            t = dm.start()
            _safe_print("[dream] started via core.dream_mode")
            return dm
    except Exception as e:
        _safe_print("[dream] import core.dream_mode failed:", e)
    # fallback: use core/dream_mode_fallback_minimal.py if present
    fallback = DIR_CORE / "dream_mode_fallback_minimal.py"
    if fallback.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("core_dream_mode_fallback", str(fallback))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "start"):
                mod.start()
                _safe_print("[dream] started fallback")
                return mod
        except Exception as e:
            _safe_print("[dream] fallback start failed:", e)
    _safe_print("[dream] no dream mode available")
    return None

# ---------------------------
# Warm pool integration
# ---------------------------
def ensure_warm_pool(target: int = None):
    if target is None:
        target = int(CONFIG.get("warm_pool_size", 5))
    try:
        # count agents
        cnt = len([p for p in DIR_AGENTS.glob("*.py")])
        if cnt >= target:
            return {"ok": True, "count": cnt}
        # try to import warm_pool.spawn_warm_pool
        try:
            from core.warm_pool import spawn_warm_pool
            created = spawn_warm_pool(pool_size=(target - cnt))
            return {"ok": True, "created": created}
        except Exception:
            # fallback generator: use agent_creator to create simple agents
            try:
                from core.agent_creator import create_new_agent
                created = []
                for i in range(target - cnt):
                    name = f"warm_{int(time.time())}_{i}"
                    p = create_new_agent(name=name, archetype="generalist")
                    created.append(str(p))
                    time.sleep(0.05)
                return {"ok": True, "created": created}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------------------------
# Repair pass: verify then attempt repair
# ---------------------------
def repair_pass():
    reg = load_registry()
    agents = reg.get("agents", {})
    problems = []
    for aid, info in agents.items():
        path = Path(info.get("path"))
        if not path.exists():
            problems.append({"agent": aid, "error": "missing_file"})
            continue
        if not cryovant_verify(path):
            # attempt repair
            r = attempt_repair(path)
            if not r.get("ok"):
                problems.append({"agent": aid, "error": "unverified_and_repair_failed"})
    return {"ok": True, "problems": problems}

# ---------------------------
# Quick scoring pass for all agents
# ---------------------------
def scoring_pass():
    reg = load_registry()
    agents = list(reg.get("agents", {}).keys())
    results = []
    for aid in agents:
        try:
            res = score_agent(aid)
            results.append({aid: res})
        except Exception as e:
            results.append({aid: {"ok": False, "error": str(e)}})
    return {"ok": True, "results": results}

# ---------------------------
# Orchestrator loop
# ---------------------------
def write_heartbeat():
    try:
        hb = DIR_CORE / "heartbeat.json"
        with hb.open("w", encoding="utf-8") as f:
            json.dump({"last_active": now_ts()}, f)
    except Exception:
        pass

def orchestrator_once():
    _safe_print("[orchestrator] cycle start", now_ts())
    try:
        update_registry()
        # repair broken or unverified agents first
        rep = repair_pass()
        _safe_print("[orchestrator] repair:", rep)
        # scoring
        sc = scoring_pass()
        _safe_print("[orchestrator] score:", {"count": len(sc.get("results", []))})
        # dream mode: try to generate ideas and create agents
        dm = start_dream_mode()
        try:
            if dm and hasattr(dm, "generate"):
                ideas = dm.generate()  # expected list of dict {name, archetype, extra_skills}
                for idea in ideas:
                    try:
                        name = idea.get("name") or f"idea_{int(time.time())}"
                        arch = idea.get("archetype", "generalist")
                        es = idea.get("extra_skills")
                        from core.agent_creator import create_new_agent
                        p = create_new_agent(name=name, archetype=arch, extra_skills=es)
                        cryovant_register(Path(p))
                        _safe_print("[dream] created agent from idea:", p)
                    except Exception as e:
                        _safe_print("[dream] create idea failed:", e)
        except Exception:
            # ignore dream generation errors
            pass
        # Beast Mode: evolve top agents
        bm = beast_mode_cycle()
        _safe_print("[orchestrator] beast:", bm)
        # warm pool ensure
        wp = ensure_warm_pool()
        _safe_print("[orchestrator] warm_pool:", wp)
        write_heartbeat()
        return {"ok": True}
    except Exception as e:
        _safe_print("[orchestrator] fatal:", e, traceback.format_exc())
        return {"ok": False, "error": str(e)}

def orchestrator_loop():
    _safe_print("[orchestrator] starting loop")
    sleep = int(CONFIG.get("daemon_sleep_sec", 6))
    while True:
        try:
            orchestrator_once()
        except KeyboardInterrupt:
            _safe_print("[orchestrator] keyboard interrupt - exiting")
            break
        except Exception:
            _safe_print("[orchestrator] exception:", traceback.format_exc())
        time.sleep(sleep)

# ---------------------------
# CLI helpers (quick)
# ---------------------------
def cli_list_agents():
    reg = load_registry()
    for aid, info in reg.get("agents", {}).items():
        print(aid, info.get("path"), "loaded:", info.get("loaded"))

def cli_create_agent(name: Optional[str] = None):
    try:
        from core.agent_creator import create_new_agent
        if not name:
            name = f"cli_{int(time.time())}"
        p = create_new_agent(name=name, archetype="generalist")
        cryovant_register(Path(p))
        print("created:", p)
    except Exception as e:
        print("create failed:", e)

def cli_repair(agent_name: str):
    reg = load_registry()
    info = reg.get("agents", {}).get(agent_name)
    if not info:
        print("agent not found")
        return
    path = Path(info.get("path"))
    print("repair result:", attempt_repair(path))

# ---------------------------
# Entry point
# ---------------------------
if __name__ == "__main__":
    try:
        _safe_print("[main] ADAAD bootstrap starting", now_ts())
        # ensure registry & logs exist
        update_registry()
        # start dream mode eagerly (non-blocking)
        start_dream_mode()
        # ensure warm pool
        ensure_warm_pool(int(CONFIG.get("warm_pool_size", 5)))
        # CLI modes
        if "--cli" in sys.argv:
            print("ADAAD CLI: list | create | repair | once")
            cmd = sys.argv[2] if len(sys.argv) > 2 else "list"
            if cmd == "list":
                cli_list_agents()
            elif cmd == "create":
                cli_create_agent(sys.argv[3] if len(sys.argv) > 3 else None)
            elif cmd == "repair":
                if len(sys.argv) > 3:
                    cli_repair(sys.argv[3])
                else:
                    print("specify agent name")
            elif cmd == "once":
                orchestrator_once()
            else:
                print("unknown CLI command")
            sys.exit(0)
        # once-run mode
        if "--once" in sys.argv:
            orchestrator_once()
            sys.exit(0)
        # normal loop
        orchestrator_loop()
    except KeyboardInterrupt:
        _safe_print("[main] interrupted by user")
    except Exception:
        _safe_print("[main] fatal bootstrap error:", traceback.format_exc())