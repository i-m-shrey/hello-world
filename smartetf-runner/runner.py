import os
import sys
import subprocess
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, abort
import sqlalchemy as sa
import zlib
import uuid
import threading

# Make your SmartETF project importable
HERE = os.path.dirname(os.path.abspath(__file__))
APPSRC = os.path.join(HERE, "appsrc")
if APPSRC not in sys.path:
    sys.path.insert(0, APPSRC)

# ---- Config ----
DB_URL = os.getenv("DB_URL")  # Example: postgresql+pg8000://user:pass@host:5432/dbname
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "3"))    # allowed minute window
LOCK_MINUTES = int(os.getenv("LOCK_MINUTES", "15"))       # recent-run lock window
ONCE_PER_DAY = os.getenv("ONCE_PER_DAY", "1").lower() in ("1","true","yes")

# Force headless mode hints for the child process
os.environ.setdefault("RUN_MODE", "headless")

app = Flask(__name__)


def get_engine():
    url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DB_URL or DATABASE_URL env var not set")
    return sa.create_engine(url, pool_pre_ping=True, future=True)


# ---------- Finvasia helpers (module scope) ----------

def finvasia_change_password_http(uid: str, oldpw: str, newpw: str, totp_secret: str):
    # Use shared Shoonya util with correct hashing and verification
    try:
        import pyotp
        from appsrc.utils.shoonya_password_util import change_password_for_client
        def _totp():
            return pyotp.TOTP(totp_secret).now() if totp_secret else ''
        ok = change_password_for_client(
            userid=uid,
            old_password=oldpw,
            new_password=newpw,
            vendor_code=os.getenv('FINVASIA_VENDOR_CODE','') or '',
            api_secret=os.getenv('FINVASIA_API_SECRET','') or '',
            imei=os.getenv('FINVASIA_IMEI','api-device'),
            totp_fn=_totp,
            verify=True,
        )
        return (True, '') if ok else (False, 'change/verify failed')
    except Exception as e:
        return False, f'HTTP change failed: {e}'


def finvasia_change_password_api(uid: str, oldpw: str, newpw: str, totp_secret: str, vendor_code: str, api_secret: str, imei: str):
    try:
        from appsrc.account import Account
        acct = Account(uid, oldpw, totp_secret, vendor_code, api_secret, imei)
        acct.login()
        api = getattr(acct, 'session', None)
        if not api:
            return False, 'API session unavailable'
        for meth in ('password_update','passwd_update','change_password','update_password'):
            fn = getattr(api, meth, None)
            if not fn:
                continue
            for args in (
                dict(userid=uid, old_password=oldpw, new_password=newpw),
                dict(old_password=oldpw, new_password=newpw),
                dict(oldpw=oldpw, newpw=newpw),
                dict(pwd=oldpw, npwd=newpw),
            ):
                try:
                    resp = fn(**args)
                    if isinstance(resp, dict) and str(resp.get('stat','')).lower() == 'ok':
                        return True, ''
                except TypeError:
                    continue
        return False, 'No API method for password change'
    except Exception as e:
        return False, f'API login/change failed: {e}'


def finvasia_change_password_web(uid: str, oldpw: str, newpw: str, totp_secret: str):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(options=opts)
        try:
            driver.set_page_load_timeout(60)
            driver.get('https://shoonyatrade.finvasia.com')
            return False, 'Web change not implemented'
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception as e:
        return False, f'Web change init failed: {e}'


def verify_login_and_funds(uid: str, newpw: str, totp_secret: str, vendor_code: str, api_secret: str, imei: str):
    try:
        from appsrc.account import Account
        acct = Account(uid, newpw, totp_secret, vendor_code, api_secret, imei)
        acct.login()
        api = getattr(acct, 'session', None)
        if not api:
            return False, None, 'No API session after change'
        funds = None
        for meth in ('limits','get_limits','get_balance','account_details'):
            fn = getattr(api, meth, None)
            if not fn:
                continue
            try:
                res = fn()
                funds = res
                break
            except Exception:
                continue
        return True, funds, ''
    except Exception as e:
        return False, None, str(e)


# ---------- Schedule helpers ----------
BIT_MAP = {"mon":1, "tue":2, "wed":4, "thu":8, "fri":16, "sat":32, "sun":64}


def _default_schedule():
    return {
        "timezone": "Asia/Kolkata",
        "health_time": None,
        "exec_time": None,
        "health_days": 31,  # Mon–Fri
        "exec_days": 31,    # Mon–Fri
        "health_enabled": True,
        "exec_enabled": True,
    }


def fetch_schedule(conn):
    """Load schedule with admin-panel times as source of truth.
    - Times (health/exec) come from legacy scheduler_settings (admin UI).
    - Advanced flags (timezone, day masks, enabled toggles) overlay from schedule_settings if present.
    """
    sched = _default_schedule()

    # 1) Base times from SchedulerSettings (admin-controlled)
    try:
        row2 = conn.execute(sa.text(
            "SELECT session_test_time, execution_time FROM scheduler_settings ORDER BY id DESC LIMIT 1"
        )).mappings().first()
        if row2:
            if row2.get("session_test_time"):
                sched["health_time"] = row2["session_test_time"]
            if row2.get("execution_time"):
                sched["exec_time"] = row2["execution_time"]
    except Exception:
        pass

    # 2) Overlay advanced toggles from schedule_settings (do NOT override times)
    try:
        row = conn.execute(sa.text(
            """
            SELECT timezone, health_time, exec_time, health_days, exec_days, health_enabled, exec_enabled
            FROM schedule_settings WHERE id=1
            """
        )).mappings().first()
        if row:
            if row.get("timezone"):
                sched["timezone"] = row["timezone"]
            if row.get("health_days") is not None:
                sched["health_days"] = row["health_days"]
            if row.get("exec_days") is not None:
                sched["exec_days"] = row["exec_days"]
            if row.get("health_enabled") is not None:
                sched["health_enabled"] = row["health_enabled"]
            if row.get("exec_enabled") is not None:
                sched["exec_enabled"] = row["exec_enabled"]
    except Exception:
        pass

    return sched


def _now(tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz)


def within_minute(target_hhmm: str | time, now_local: datetime, window_sec: int = 59) -> bool:
    if not target_hhmm:
        return False
    try:
        if isinstance(target_hhmm, time):
            hh, mm = target_hhmm.hour, target_hhmm.minute
        else:
            hh, mm = map(int, str(target_hhmm).split(":"))
    except Exception:
        return False
    return (now_local.hour == hh and now_local.minute == mm)


def day_allowed(mask: int, now_local: datetime) -> bool:
    bit = 1 << now_local.weekday()  # Monday=0
    return (int(mask or 0) & bit) != 0


def should_trigger(job: str, sched: dict, now_local: datetime):
    if job == "health":
        if not sched.get("health_enabled", True):
            return False, "disabled"
        if not day_allowed(sched.get("health_days", 31), now_local):
            return False, "wrong_day"
        if not within_minute(sched.get("health_time"), now_local):
            return False, "not_time"
        return True, "ok"
    else:
        if not sched.get("exec_enabled", True):
            return False, "disabled"
        if not day_allowed(sched.get("exec_days", 31), now_local):
            return False, "wrong_day"
        if not within_minute(sched.get("exec_time"), now_local):
            return False, "not_time"
        return True, "ok"


# ---------- Recent-run and once-per-day ----------

def recent_execution_exists(conn):
    cutoff = datetime.utcnow() - timedelta(minutes=LOCK_MINUTES)
    count = conn.execute(sa.text(
        "SELECT COUNT(*) FROM execution_run WHERE started_at > :cutoff"
    ), {"cutoff": cutoff}).scalar_one()
    return count and int(count) > 0


def ran_today(conn, table: str, tz_name: str) -> bool:
    """Return True if a row exists today (local day boundaries) in the given table."""
    now_local = _now(tz_name)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    try:
        count = conn.execute(sa.text(
            f"SELECT COUNT(*) FROM {table} WHERE started_at >= :start AND started_at < :end"
        ), {"start": start_utc, "end": end_utc}).scalar_one()
        return int(count or 0) > 0
    except Exception:
        return False


# ---------- Advisory locks ----------

def _advisory_try_lock(conn, key: int) -> bool:
    try:
        v = conn.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar_one()
        return bool(v)
    except Exception:
        return True


def minute_lock(conn, job: str, now_local: datetime) -> bool:
    k = zlib.crc32(f"{job}:{now_local.strftime('%Y-%m-%d %H:%M')}".encode())
    return _advisory_try_lock(conn, k)


def daily_lock(conn, job: str, now_local: datetime) -> bool:
    k = zlib.crc32(f"{job}:{now_local.strftime('%Y-%m-%d')}".encode())
    return _advisory_try_lock(conn, k)

# ---------- Workers & Retention ----------

def prune_runs(conn):
    try:
        keep_exec = int(os.getenv("RETAIN_LAST_RUNS", "10"))
        keep_health = int(os.getenv("RETAIN_LAST_HEALTH", str(keep_exec)))

        if keep_exec > 0:
            conn.execute(sa.text(
                """
                DELETE FROM order_event
                WHERE run_id IN (
                  SELECT id FROM execution_run
                  WHERE id NOT IN (
                    SELECT id FROM execution_run ORDER BY started_at DESC LIMIT :k1
                  )
                )
                """
            ), {"k1": keep_exec})

            conn.execute(sa.text(
                """
                DELETE FROM execution_run
                WHERE id NOT IN (
                  SELECT id FROM execution_run ORDER BY started_at DESC LIMIT :k2
                )
                """
            ), {"k2": keep_exec})

        if keep_health > 0:
            conn.execute(sa.text(
                """
                DELETE FROM health_check_run
                WHERE id NOT IN (
                  SELECT id FROM health_check_run ORDER BY started_at DESC LIMIT :k3
                )
                """
            ), {"k3": keep_health})
    except Exception:
        pass

# ---------- Existing runners ----------

def run_etf_automated(run_id: int | None = None):
    script_path = os.path.join("/app", "appsrc", "strategy_runner", "etf_automated.py")
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("ENABLE_RUN_LOGS", "1")
    env.setdefault("AVG_FALL_CSV", "/app/appsrc/strategy_runner/average_percentage_fall_indices.csv")
    if run_id:
        env["RUN_ID"] = str(run_id)
    if not run_id:
        try:
            with get_engine().begin() as _conn:
                run_id = create_prelock_run(_conn, mode=os.environ.get("RUN_MODE", "headless"))
                env["RUN_ID"] = str(run_id)
        except Exception:
            pass
    return subprocess.run([sys.executable, "-u", script_path], env=env, cwd="/app/appsrc", check=False)


def create_prelock_run(conn, mode="headless"):
    rid = conn.execute(sa.text(
        "INSERT INTO execution_run (started_at, status, mode, message, trace_id) "
        "VALUES (:started_at, 'running', :mode, :message, :trace_id) RETURNING id"
    ), {
        "started_at": datetime.utcnow(),
        "mode": mode,
        "message": "runner_prelock",
        "trace_id": uuid.uuid4().hex[:16]
    }).scalar_one()
    return int(rid)


def run_health_check():
    script = os.path.join("/app", "appsrc", "strategy_runner", "morning_health_check.py")
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.run([sys.executable, "-u", script], env=env, cwd="/app/appsrc", check=False)

# ---------- Async wrappers ----------

# Simple in-memory job store for long-running tasks (rotation)
JOBS: dict[str, dict] = {}
# Per-account delay between operations (seconds)
ROTATION_DELAY_SECONDS = int(os.getenv("ROTATION_DELAY_SECONDS", "1"))

# Rotation job persistence helpers
CREATE_ROTATION_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS rotation_job (
  id SERIAL PRIMARY KEY,
  broker VARCHAR(50) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'running',
  processed INTEGER NOT NULL DEFAULT 0,
  total INTEGER,
  started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMP WITHOUT TIME ZONE,
  error TEXT
);
CREATE TABLE IF NOT EXISTS rotation_item (
  id SERIAL PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES rotation_job(id) ON DELETE CASCADE,
  full_name TEXT,
  email TEXT,
  mobile TEXT,
  broker_username TEXT,
  old_password TEXT,
  new_password TEXT,
  funds TEXT,
  comments TEXT,
  changed BOOLEAN,
  verified BOOLEAN,
  processed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
"""

def ensure_rotation_tables(conn):
    for stmt in CREATE_ROTATION_TABLES_SQL.strip().split(';'):
        s = stmt.strip()
        if s:
            conn.execute(sa.text(s))


def run_etf_automated_async(prelock: bool = True) -> int | None:
    run_id = None
    try:
        if prelock:
            with get_engine().begin() as conn:
                run_id = create_prelock_run(conn, mode=os.environ.get("RUN_MODE", "headless"))
    except Exception:
        run_id = None

    def _worker(_run_id):
        try:
            run_etf_automated(_run_id)
        except Exception:
            pass

    threading.Thread(target=_worker, args=(run_id,), daemon=True).start()
    return run_id


def run_health_check_async():
    def _worker():
        try:
            run_health_check()
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


@app.get("/tick")
def tick():
    try:
        with get_engine().begin() as conn:
            sched = fetch_schedule(conn)
            tz = sched.get("timezone") or "Asia/Kolkata"
            now_local = _now(tz)

            actions = []

            ok, reason = should_trigger("health", sched, now_local)
            if ok:
                try:
                    if not minute_lock(conn, "health", now_local):
                        actions.append({"job":"health","status":"noop","reason":"minute_lock"})
                    elif ONCE_PER_DAY and ran_today(conn, "health_check_run", tz):
                        actions.append({"job":"health","status":"noop","reason":"already_ran_today"})
                    else:
                        run_health_check_async()
                        actions.append({"job":"health","status":"triggered"})
                except Exception:
                    run_health_check_async()
                    actions.append({"job":"health","status":"triggered"})
            else:
                actions.append({"job":"health","status":"noop","reason":reason})

            ok, reason = should_trigger("exec", sched, now_local)
            if ok:
                try:
                    if not minute_lock(conn, "exec", now_local):
                        actions.append({"job":"exec","status":"noop","reason":"minute_lock"})
                    elif ONCE_PER_DAY and ran_today(conn, "execution_run", tz):
                        actions.append({"job":"exec","status":"noop","reason":"already_ran_today"})
                    else:
                        rid = run_etf_automated_async(prelock=True)
                        actions.append({"job":"exec","status":"triggered","run_id": rid})
                except Exception:
                    rid = run_etf_automated_async(prelock=True)
                    actions.append({"job":"exec","status":"triggered","run_id": rid})
            else:
                actions.append({"job":"exec","status":"noop","reason":reason})

            prune_runs(conn)

        any_triggered = any(a["status"] == "triggered" for a in actions)
        return jsonify({"status": "triggered" if any_triggered else "noop", "actions": actions}), 200

    except Exception as e:
        return jsonify({"status":"error", "message": str(e)}), 500


@app.get("/")
def root_health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()})


@app.get("/status")
def status():
    try:
        with get_engine().begin() as conn:
            sched = fetch_schedule(conn)
            exec_row = conn.execute(sa.text(
                "SELECT * FROM execution_run ORDER BY id DESC LIMIT 1"
            )).mappings().first()
            try:
                health_row = conn.execute(sa.text(
                    "SELECT * FROM health_check_run ORDER BY id DESC LIMIT 1"
                )).mappings().first()
            except Exception:
                health_row = None

        def pick(row, keys):
            out = {}
            for k in keys:
                out[k] = (str(row[k]) if row and (k in row) and row[k] is not None else None)
            return out

        return jsonify({
            "status": "ok",
            "schedule": {
                "timezone": sched.get("timezone"),
                "health_time": str(sched.get("health_time")),
                "exec_time": str(sched.get("exec_time")),
                "health_days": int(sched.get("health_days")),
                "exec_days": int(sched.get("exec_days")),
                "health_enabled": bool(sched.get("health_enabled")),
                "exec_enabled": bool(sched.get("exec_enabled")),
            },
            "last_execution": pick(exec_row,  ["id","started_at","ended_at","status","total_orders","ok_orders","fail_orders"]),
            "last_health":    pick(health_row,["id","started_at","ended_at","driver_issues","passed","failed"]),
        }), 200
    except Exception as e:
        return jsonify({"status":"error","message": str(e)}), 500


# Auth for manual endpoints
RUNNER_TOKEN = os.getenv("RUNNER_TOKEN", "")

def _check_token(req):
    if not RUNNER_TOKEN:
        return True
    tok = req.headers.get("X-Runner-Token") or req.args.get("token")
    return str(tok or "") == str(RUNNER_TOKEN)


@app.post("/run-now")
def run_now():
    if not _check_token(request):
        abort(401)
    force = str(request.args.get("force", "")).lower() in ("1","true","yes")
    try:
        with get_engine().begin() as conn:
            sched = fetch_schedule(conn)
            tz = sched.get("timezone") or "Asia/Kolkata"
            now_local = _now(tz)
            if (not force) and (not minute_lock(conn, "exec", now_local)):
                return jsonify({"status":"noop","ran": False, "reason":"minute_lock"}), 200
            # prelock run id for traceability and spawn async
            run_id = create_prelock_run(conn, mode=os.environ.get("RUN_MODE", "headless"))
    except Exception:
        run_id = None
    result = run_etf_automated(run_id)
    status = "ok" if (result and getattr(result, "returncode", 1) == 0) else "error"
    return jsonify({"status": status, "ran": True, "run_id": run_id, "returncode": (result.returncode if result else None)}), (200 if status == "ok" else 500)


@app.post("/health-now")
def health_now():
    if not _check_token(request):
        abort(401)
    force = str(request.args.get("force", "")).lower() in ("1","true","yes")
    try:
        with get_engine().begin() as conn:
            sched = fetch_schedule(conn)
            tz = sched.get("timezone") or "Asia/Kolkata"
            now_local = _now(tz)
            if (not force) and (not minute_lock(conn, "health", now_local)):
                return jsonify({"status":"noop","ran": False, "reason":"minute_lock"}), 200
    except Exception:
        pass
    result = run_health_check()
    status = "ok" if (result and getattr(result, "returncode", 1) == 0) else "error"
    return jsonify({"status": status, "ran": True, "returncode": (result.returncode if result else None)}), (200 if status == "ok" else 500)


@app.post("/rotate-passwords/dry-run")
def rotate_passwords_dry_run():
    if not _check_token(request):
        abort(401)
    broker_name = (request.args.get("broker_name") or (request.get_json(silent=True) or {}).get("broker_name") or "FINVASIA").upper()
    try:
        with get_engine().begin() as conn:
            rows = conn.execute(sa.text(
                """
                SELECT b.id AS broker_id,
                       b.broker_name,
                       b.user_id_broker,
                       b.password AS broker_password,
                       b.totp_secret,
                       b.vendor_code,
                       b.api_secret,
                       b.imei,
                       u.id AS user_id,
                       u.full_name,
                       u.email,
                       u.mobile,
                       u.customer_id
                FROM broker b
                JOIN "user" u ON u.id = b.user_id
                WHERE b.broker_name = :broker
                  AND COALESCE(b.subscription_status,'') = 'Active'
                  AND EXISTS (
                    SELECT 1 FROM subscription s
                    WHERE s.customer_id = u.customer_id
                      AND s.payment_status IN ('Paid','Active','Successful')
                      AND s.expiry_date > NOW()
                  )
                """
            ), {"broker": broker_name}).mappings().all()
            import re, random
            nums = ["321","647","743"]
            def sanitize_first(name):
                if not name:
                    return ""
                first = name.split()[0]
                cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
                if not cleaned:
                    return ""
                return cleaned[:1].upper() + cleaned[1:].lower()
            items = []
            for r in rows:
                missing = []
                if not r["user_id_broker"]:
                    missing.append("user_id_broker")
                if not r["broker_password"]:
                    missing.append("password")
                if not r["totp_secret"]:
                    missing.append("totp_secret")
                if not r["vendor_code"]:
                    missing.append("vendor_code")
                if not r["api_secret"]:
                    missing.append("api_secret")
                if not r["imei"]:
                    missing.append("imei")
                fname = sanitize_first(r["full_name"])
                suffix = random.choice(nums)
                new_pw = f"{fname}@{suffix}" if fname else None
                items.append({
                    "user_id": r["user_id"],
                    "full_name": r["full_name"],
                    "email": r["email"],
                    "mobile": r["mobile"],
                    "broker_username": r["user_id_broker"],
                    "readiness": len(missing) == 0,
                    "missing_fields": missing,
                    "would_set_password_to": new_pw
                })
            return jsonify({"status":"ok","broker":broker_name,"count":len(items),"items":items}), 200
    except Exception as e:
        return jsonify({"status":"error","message": str(e)}), 500


@app.post("/rotate-passwords/run")
def rotate_passwords_run():
    if not _check_token(request):
        abort(401)
    payload = request.get_json(silent=True) or {}
    broker_name = (request.args.get("broker_name") or payload.get("broker_name") or "FINVASIA").upper()
    return jsonify(_do_password_rotation(broker_name)), 200


def _do_password_rotation(broker_name: str, job_id: str | None = None) -> dict:
    # Legacy in-memory implementation retained for compatibility
    import re, random, time
    # Read all candidate rows first to know total for progress
    try:
        with get_engine().connect() as conn_ro:
            rows = conn_ro.execute(sa.text(
                """
                SELECT b.id AS broker_id,
                       b.broker_name,
                       b.user_id_broker,
                       b.password AS broker_password,
                       b.totp_secret,
                       b.vendor_code,
                       b.api_secret,
                       b.imei,
                       u.id AS user_id,
                       u.full_name,
                       u.email,
                       u.mobile,
                       u.customer_id
                FROM broker b
                JOIN "user" u ON u.id = b.user_id
                WHERE b.broker_name = :broker
                  AND COALESCE(b.subscription_status,'') = 'Active'
                  AND EXISTS (
                    SELECT 1 FROM subscription s
                    WHERE s.customer_id = u.customer_id
                      AND s.payment_status IN ('Paid','Active','Successful')
                      AND s.expiry_date > NOW()
                  )
                ORDER BY u.id
                """
            ), {"broker": broker_name}).mappings().all()
    except Exception as e:
        if job_id and job_id in JOBS:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)
        return {"status":"error","message": str(e)}

    total = len(rows)
    if job_id:
        JOBS[job_id]["progress"] = {"processed": 0, "total": total}
        JOBS[job_id]["results"] = []

    nums = ["321","647","743"]
    def sanitize_first(name):
        if not name:
            return ""
        first = name.split()[0]
        cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
        if not cleaned:
            return ""
        return cleaned[:1].upper() + cleaned[1:].lower()

    def finvasia_change_password_http(uid, oldpw, newpw, totp_secret, vendor_code, api_secret, imei):
        try:
            import pyotp
            from appsrc.utils.shoonya_password_util import change_password_for_client
            def _totp():
                return pyotp.TOTP(totp_secret).now() if totp_secret else ''
            ok = change_password_for_client(
                userid=uid,
                old_password=oldpw,
                new_password=newpw,
                vendor_code=vendor_code,
                api_secret=api_secret,
                imei=imei,
                totp_fn=_totp,
                verify=True,
            )
            return (True, '') if ok else (False, 'change/verify failed')
        except Exception as e:
            return False, f'HTTP change failed: {e}'

    def finvasia_change_password_api(uid, oldpw, newpw, totp_secret, vendor_code, api_secret, imei):
        try:
            from appsrc.account import Account
            acct = Account(uid, oldpw, totp_secret, vendor_code, api_secret, imei)
            acct.login()
            api = getattr(acct, 'session', None)
            if not api:
                return False, 'API session unavailable'
            for meth in ('password_update','passwd_update','change_password','update_password'):
                fn = getattr(api, meth, None)
                if not fn:
                    continue
                for args in (
                    dict(userid=uid, old_password=oldpw, new_password=newpw),
                    dict(old_password=oldpw, new_password=newpw),
                    dict(oldpw=oldpw, newpw=newpw),
                    dict(pwd=oldpw, npwd=newpw),
                ):
                    try:
                        resp = fn(**args)
                        if isinstance(resp, dict) and str(resp.get('stat','')).lower() == 'ok':
                            return True, ''
                    except TypeError:
                        continue
            return False, 'No API method for password change'
        except Exception as e:
            return False, f'API login/change failed: {e}'

    def finvasia_change_password_web(uid, oldpw, newpw, totp_secret):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            opts = Options()
            opts.add_argument('--headless=new')
            opts.add_argument('--no-sandbox')
            opts.add_argument('--disable-dev-shm-usage')
            driver = webdriver.Chrome(options=opts)
            try:
                driver.set_page_load_timeout(60)
                driver.get('https://shoonyatrade.finvasia.com')
                return False, 'Web change not implemented'
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception as e:
            return False, f'Web change init failed: {e}'

    def verify_login_and_funds(uid, newpw, totp_secret, vendor_code, api_secret, imei):
        try:
            from appsrc.account import Account
            acct = Account(uid, newpw, totp_secret, vendor_code, api_secret, imei)
            acct.login()
            api = getattr(acct, 'session', None)
            if not api:
                return False, None, 'No API session after change'
            funds = None
            for meth in ('limits','get_limits','get_balance','account_details'):
                fn = getattr(api, meth, None)
                if not fn:
                    continue
                try:
                    res = fn()
                    funds = res
                    break
                except Exception:
                    continue
            return True, funds, ''
        except Exception as e:
            return False, None, str(e)

    results = []
    for idx, r in enumerate(rows):
        fname = sanitize_first(r['full_name'])
        suffix = random.choice(nums)
        new_pw = f"{fname}@{suffix}" if fname else None
        old_pw = r['broker_password']
        comments = ''
        changed = False
        if not new_pw:
            comments = 'Invalid first name for policy'
        else:
            ok_http, msg_http = finvasia_change_password_http(r['user_id_broker'], old_pw, new_pw, r['totp_secret'], r['vendor_code'], r['api_secret'], r['imei'])
            if ok_http:
                changed = True
            else:
                comments = f'HTTP change failed: {msg_http}'
                ok_api, msg_api = finvasia_change_password_api(r['user_id_broker'], old_pw, new_pw, r['totp_secret'], r['vendor_code'], r['api_secret'], r['imei'])
                if ok_api:
                    changed = True
                else:
                    comments += f'; API change failed: {msg_api}'
                    ok2, msg2 = finvasia_change_password_web(r['user_id_broker'], old_pw, new_pw, r['totp_secret'])
                    if ok2:
                        changed = True
                    else:
                        comments += f'; Web change failed: {msg2}'
        verified = False
        funds = None
        if changed:
            v_ok, v_funds, v_err = verify_login_and_funds(r['user_id_broker'], new_pw, r['totp_secret'], r['vendor_code'], r['api_secret'], r['imei'])
            if v_ok:
                verified = True
                funds = v_funds
                try:
                    with get_engine().begin() as conn_upd:
                        conn_upd.execute(sa.text(
                            'UPDATE broker SET password = :p, last_updated = NOW() WHERE id = :bid'
                        ), {"p": new_pw, "bid": r['broker_id']})
                except Exception as ue:
                    comments += f'; DB update error: {ue}'
                try:
                    from appsrc.email_notifications import send_client_broker_password_email
                    send_client_broker_password_email(r['email'], r['full_name'], broker_name, new_pw, r['user_id_broker'])
                except Exception as ee:
                    comments += f'; Client email error: {ee}'
            else:
                comments += f'; Verification failed: {v_err}'
        row_result = {
            'full_name': r['full_name'],
            'email': r['email'],
            'mobile': r['mobile'],
            'broker_username': r['user_id_broker'],
            'old_password': old_pw,
            'new_password': new_pw,
            'funds': funds,
            'comments': comments,
            'changed': changed,
            'verified': verified,
        }
        results.append(row_result)
        if job_id and job_id in JOBS:
            JOBS[job_id]['results'].append(row_result)
            JOBS[job_id]['progress']['processed'] = idx + 1
        if idx < len(rows) - 1 and ROTATION_DELAY_SECONDS > 0:
            time.sleep(ROTATION_DELAY_SECONDS)

    try:
        from appsrc.email_notifications import send_admin_rotation_summary_email
        send_admin_rotation_summary_email(results, broker_name)
    except Exception:
        pass

    ok_count = sum(1 for r in results if r['changed'] and r['verified'])
    fail_count = len(results) - ok_count
    summary = {"status":"ok","broker": broker_name, "processed": len(results), "ok": ok_count, "failed": fail_count, "results": results}
    if job_id and job_id in JOBS:
        JOBS[job_id]['status'] = 'ok'
        JOBS[job_id]['ended_at'] = datetime.utcnow().isoformat()
        JOBS[job_id]['summary'] = summary
    return summary


@app.post("/rotate-passwords/start")
def rotate_passwords_start():
    if not _check_token(request):
        abort(401)
    payload = request.get_json(silent=True) or {}
    broker_name = (request.args.get("broker_name") or payload.get("broker_name") or "FINVASIA").upper()
    try:
        with get_engine().begin() as conn:
            ensure_rotation_tables(conn)
            total = conn.execute(sa.text(
                """
                SELECT COUNT(*) FROM broker b
                JOIN "user" u ON u.id = b.user_id
                WHERE b.broker_name = :broker
                  AND COALESCE(b.subscription_status,'') = 'Active'
                  AND EXISTS (
                    SELECT 1 FROM subscription s
                    WHERE s.customer_id = u.customer_id
                      AND s.payment_status IN ('Paid','Active','Successful')
                      AND s.expiry_date > NOW()
                  )
                """
            ), {"broker": broker_name}).scalar_one()
            job_id = conn.execute(sa.text(
                "INSERT INTO rotation_job (broker, status, total) VALUES (:b, 'running', :t) RETURNING id"
            ), {"b": broker_name, "t": int(total or 0)}).scalar_one()
    except Exception as e:
        return jsonify({"status":"error","message": str(e)}), 500

    def _worker_db(jid: int, bname: str):
        try:
            _run_rotation_job(jid, bname)
        except Exception as e:
            try:
                with get_engine().begin() as c2:
                    c2.execute(sa.text(
                        "UPDATE rotation_job SET status='error', error=:e, ended_at=NOW() WHERE id=:id"
                    ), {"e": str(e), "id": jid})
            except Exception:
                pass
    threading.Thread(target=_worker_db, args=(int(job_id), broker_name), daemon=True).start()
    return jsonify({"status":"ok","job_id": int(job_id)}), 200


def _run_rotation_job(job_id: int, broker_name: str):
    # Fetch eligible rows and update total if needed
    with get_engine().begin() as conn:
        ensure_rotation_tables(conn)
        rows = conn.execute(sa.text(
            """
            SELECT b.id AS broker_id,
                   b.broker_name,
                   b.user_id_broker,
                   b.password AS broker_password,
                   b.totp_secret,
                   b.vendor_code,
                   b.api_secret,
                   b.imei,
                   u.id AS user_id,
                   u.full_name,
                   u.email,
                   u.mobile,
                   u.customer_id
            FROM broker b
            JOIN "user" u ON u.id = b.user_id
            WHERE b.broker_name = :broker
              AND COALESCE(b.subscription_status,'') = 'Active'
              AND EXISTS (
                SELECT 1 FROM subscription s
                WHERE s.customer_id = u.customer_id
                  AND s.payment_status IN ('Paid','Active','Successful')
                  AND s.expiry_date > NOW()
              )
            ORDER BY u.id
            """
        ), {"broker": broker_name}).mappings().all()
        conn.execute(sa.text("UPDATE rotation_job SET total=:t WHERE id=:id"), {"t": len(rows), "id": job_id})

    # Process rows sequentially and write progress/items
    processed = 0
    ok_count = 0
    results_summary = []

    # Re-use core change/verify logic from _do_password_rotation
    import re, random, time
    nums = ["321","647","743"]
    def sanitize_first(name):
        if not name:
            return ""
        first = name.split()[0]
        cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
        if not cleaned:
            return ""
        return cleaned[:1].upper() + cleaned[1:].lower()

    for idx, r in enumerate(rows):
        fname = sanitize_first(r['full_name'])
        suffix = random.choice(nums)
        new_pw = f"{fname}@{suffix}" if fname else None
        old_pw = r['broker_password']
        comments = ''
        changed = False
        verified = False
        funds = None
        try:
            if not new_pw:
                comments = 'Invalid first name for policy'
            else:
                ok_http, msg_http = finvasia_change_password_http(r['user_id_broker'], old_pw, new_pw, r['totp_secret'], r['vendor_code'], r['api_secret'], r['imei'])
                if ok_http:
                    changed = True
                else:
                    comments = f'HTTP change failed: {msg_http}'
                    ok_api, msg_api = finvasia_change_password_api(r['user_id_broker'], old_pw, new_pw, r['totp_secret'], r['vendor_code'], r['api_secret'], r['imei'])
                    if ok_api:
                        changed = True
                    else:
                        comments += f'; API change failed: {msg_api}'
        except Exception as e:
            comments += f'; Exception: {e}'

        if changed:
            v_ok, v_funds, v_err = verify_login_and_funds(r['user_id_broker'], new_pw, r['totp_secret'], r['vendor_code'], r['api_secret'], r['imei'])
            if v_ok:
                verified = True
                funds = v_funds
                ok_count += 1
                # Update broker password only after verification
                try:
                    with get_engine().begin() as cu:
                        cu.execute(sa.text('UPDATE broker SET password = :p, last_updated = NOW() WHERE id = :bid'), {"p": new_pw, "bid": r['broker_id']})
                except Exception as ue:
                    comments += f'; DB update error: {ue}'
            else:
                comments += f'; Verification failed: {v_err}'

        # Persist item and progress
        try:
            with get_engine().begin() as ci:
                ci.execute(sa.text(
                    'INSERT INTO rotation_item (job_id, full_name, email, mobile, broker_username, old_password, new_password, funds, comments, changed, verified) '
                    'VALUES (:job_id, :full_name, :email, :mobile, :broker_username, :old_password, :new_password, :funds, :comments, :changed, :verified)'
                ), {
                    "job_id": job_id,
                    "full_name": r['full_name'],
                    "email": r['email'],
                    "mobile": r['mobile'],
                    "broker_username": r['user_id_broker'],
                    "old_password": old_pw,
                    "new_password": new_pw,
                    "funds": str(funds) if funds is not None else None,
                    "comments": comments,
                    "changed": bool(changed),
                    "verified": bool(verified)
                })
                processed += 1
                ci.execute(sa.text('UPDATE rotation_job SET processed = :p WHERE id = :id'), {"p": processed, "id": job_id})
        except Exception as e:
            # Best-effort logging in DB error field
            try:
                with get_engine().begin() as ce:
                    ce.execute(sa.text('UPDATE rotation_job SET error = :e WHERE id = :id'), {"e": f'Item persist error: {e}', "id": job_id})
            except Exception:
                pass

        # delay between accounts
        if idx < len(rows) - 1 and ROTATION_DELAY_SECONDS > 0:
            time.sleep(ROTATION_DELAY_SECONDS)

    # Send admin summary email (best effort)
    try:
        from appsrc.email_notifications import send_admin_rotation_summary_email
        # Build rows from rotation_item? For now, we skip fetching items and rely on email content minimal.
        # send_admin_rotation_summary_email could accept results; Not fetching here to keep perf.
    except Exception:
        pass

    # Mark job as finished
    with get_engine().begin() as cf:
        cf.execute(sa.text("UPDATE rotation_job SET status='ok', ended_at=NOW() WHERE id=:id"), {"id": job_id})


@app.get("/jobs/<job_id>")
def job_status(job_id: str):
    if not _check_token(request):
        abort(401)
    try:
        with get_engine().begin() as conn:
            ensure_rotation_tables(conn)
            row = conn.execute(sa.text('SELECT id, broker, status, processed, total, started_at, ended_at, error FROM rotation_job WHERE id=:id'), {"id": int(job_id)}).mappings().first()
            if not row:
                return jsonify({"status":"error","message":"job_not_found"}), 404
            status = row['status']
            progress = {"processed": int(row['processed'] or 0), "total": (int(row['total']) if row['total'] is not None else None)}
            if status == 'running':
                return jsonify({
                    "status": "running",
                    "job_id": int(row['id']),
                    "broker": row['broker'],
                    "progress": progress,
                    "started_at": str(row['started_at'])
                }), 200
            # Finished or error: compute summary counts
            counts = conn.execute(sa.text(
                "SELECT SUM(CASE WHEN changed AND verified THEN 1 ELSE 0 END) AS ok_cnt, COUNT(*) AS total_cnt FROM rotation_item WHERE job_id=:id"
            ), {"id": int(job_id)}).mappings().first()
            ok_cnt = int(counts['ok_cnt'] or 0)
            total_cnt = int(counts['total_cnt'] or 0)
            fail_cnt = total_cnt - ok_cnt
            return jsonify({
                "status": status if status in ('ok','error') else str(status),
                "job_id": int(row['id']),
                "broker": row['broker'],
                "progress": progress,
                "started_at": str(row['started_at']),
                "ended_at": str(row['ended_at']) if row['ended_at'] else None,
                "summary": {"processed": total_cnt, "ok": ok_cnt, "failed": fail_cnt},
                "error": row['error']
            }), 200
    except Exception as e:
        return jsonify({"status":"error","message": str(e)}), 500
