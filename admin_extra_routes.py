from flask import Blueprint, request, jsonify, session, redirect, url_for, flash, current_app, Response
import os
import requests
import threading
import time
import re
import random
import sqlalchemy as sa
import zlib
from models import db, User, Broker
from security_utils import encrypt_portal_password, decrypt_portal_password
from app_utils.shoonya_password_util import change_password_for_client
from email_notifications import send_client_notification_email, send_email
import pyotp

admin_extra_bp = Blueprint('admin_extra', __name__)

RUNNER_URL = os.getenv("RUNNER_URL", "").rstrip("/")
RUNNER_TOKEN = os.getenv("RUNNER_TOKEN", "")
JOBS: dict[int, dict] = {}

def _is_admin():
    uid = session.get('user_id')
    if not uid:
        return None
    user = db.session.get(User, uid)
    if user and user.is_admin:
        return user
    return None

def _runner_post2(path: str, params: dict | None = None):
    if not RUNNER_URL:
        return {"status": "error", "message": "RUNNER_URL is not set; set it to your runner Cloud Run URL."}
    from urllib.parse import urlencode
    qs = urlencode(params or {})
    if RUNNER_TOKEN:
        tok = urlencode({"token": RUNNER_TOKEN})
        qs = f"{qs}&{tok}" if qs else tok
    url = f"{RUNNER_URL}{path}"
    if qs:
        url += f"?{qs}"
    try:
        r = requests.post(url, data=b"", timeout=600)
        if r.ok:
            try:
                return r.json()
            except ValueError:
                return {"status": "error", "message": f"Runner returned non-JSON: {r.text[:400]}"}
        else:
            return {"status": "error", "message": f"Runner HTTP {r.status_code}: {r.text[:400]}"}
    except Exception as e:
        return {"status": "error", "message": f"Runner request failed: {e}"}

def _runner_get(path: str, params: dict | None = None):
    if not RUNNER_URL:
        return {"status": "error", "message": "RUNNER_URL is not set; set it to your runner Cloud Run URL."}
    from urllib.parse import urlencode
    qs = urlencode(params or {})
    if RUNNER_TOKEN:
        tok = urlencode({"token": RUNNER_TOKEN})
        qs = f"{qs}&{tok}" if qs else tok
    url = f"{RUNNER_URL}{path}"
    if qs:
        url += f"?{qs}"
    try:
        r = requests.get(url, timeout=600)
        if r.ok:
            try:
                return r.json()
            except ValueError:
                return {"status": "error", "message": f"Runner returned non-JSON: {r.text[:400]}"}
        else:
            return {"status": "error", "message": f"Runner HTTP {r.status_code}: {r.text[:400]}"}
    except Exception as e:
        return {"status": "error", "message": f"Runner request failed: {e}"}

@admin_extra_bp.route('/admin/user/<int:user_id>/set-password', methods=['POST'])
def admin_set_user_password(user_id: int):
    if not _is_admin():
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    if not new_password or new_password != confirm_password or len(new_password) < 6:
        flash('Invalid password or mismatch', 'error')
        return redirect(url_for('admin_view_user', user_id=user_id))
    user.set_password(new_password)
    try:
        enc, iv, tag = encrypt_portal_password(new_password)
        user.portal_pw_enc = enc
        user.portal_pw_iv = iv
        user.portal_pw_tag = tag
    except Exception as e:
        flash(f'Encryption skipped ({e}). Set PORTAL_PASSWORD_KEY to enable reveal.', 'warning')
    try:
        db.session.commit()
        flash('User password updated', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating password: {e}', 'error')
    return redirect(url_for('admin_view_user', user_id=user_id))

@admin_extra_bp.route('/admin/rotate-passwords/dry-run', methods=['POST'])
def admin_rotate_passwords_dry_run():
    if not _is_admin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    broker_name = (data.get('broker_name') or request.form.get('broker_name') or 'FINVASIA').upper()
    if RUNNER_URL:
        resp = _runner_post2('/rotate-passwords/dry-run', {"broker_name": broker_name})
        code = 200 if isinstance(resp, dict) and resp.get('status') == 'ok' else 500
        return jsonify(resp), code
    return jsonify(_local_rotate_passwords_dry_run(broker_name)), 200

@admin_extra_bp.route('/admin/rotate-passwords/run', methods=['POST'])
def admin_rotate_passwords_run():
    if not _is_admin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    broker_name = (data.get('broker_name') or request.form.get('broker_name') or 'FINVASIA').upper()
    if RUNNER_URL:
        resp = _runner_post2('/rotate-passwords/run', {"broker_name": broker_name})
        code = 200 if isinstance(resp, dict) and resp.get('status') == 'ok' else 500
        return jsonify(resp), code
    res = _local_do_rotation(broker_name)
    return jsonify(res), 200

@admin_extra_bp.route('/admin/rotate-passwords/start', methods=['POST'])
def admin_rotate_passwords_start():
    if not _is_admin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    broker_name = (data.get('broker_name') or request.form.get('broker_name') or 'FINVASIA').upper()
    if RUNNER_URL:
        resp = _runner_post2('/rotate-passwords/start', {"broker_name": broker_name})
        code = 200 if isinstance(resp, dict) and resp.get('status') == 'ok' else 500
        return jsonify(resp), code
    jid = _local_rotation_start(broker_name)
    return jsonify({"status":"ok","job_id": jid}), 200

@admin_extra_bp.route('/admin/rotate-passwords/status', methods=['GET'])
def admin_rotate_passwords_status():
    if not _is_admin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    job_id = request.args.get('job_id', '').strip()
    if not job_id:
        return jsonify({"status":"error","message":"job_id required"}), 400
    if RUNNER_URL:
        resp = _runner_get(f'/jobs/{job_id}')
        code = 200 if isinstance(resp, dict) and resp.get('status') in ('running','ok','error') else 500
        return jsonify(resp), code
    return jsonify(_local_job_status(int(job_id))), 200

@admin_extra_bp.route('/admin/rotate-passwords/report', methods=['GET'])
def admin_rotate_passwords_report():
    if not _is_admin():
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    job_id = request.args.get('job_id', '').strip()
    if not job_id or not job_id.isdigit():
        return jsonify({"status":"error","message":"job_id required"}), 400
    j = JOBS.get(int(job_id))
    if not j:
        return jsonify({"status":"error","message":"job_not_found"}), 404
    rows = j.get('results') or []
    # Build CSV
    out = ["full_name,email,broker_username,old_password,new_password,changed,verified,comments"]
    for r in rows:
        def esc(v):
            s = '' if v is None else str(v)
            if ',' in s or '"' in s:
                s = '"' + s.replace('"','""') + '"'
            return s
        out.append(
            ",".join([
                esc(r.get('full_name')),
                esc(r.get('email')),
                esc(r.get('broker_username')),
                esc(r.get('old_password')),
                esc(r.get('new_password')),
                esc(r.get('changed')),
                esc(r.get('verified')),
                esc(r.get('comments')),
            ])
        )
    csv = "\n".join(out)
    return Response(csv, mimetype='text/csv', headers={'Content-Disposition':'attachment; filename=rotation-report.csv'})

@admin_extra_bp.route('/admin/notify-passwords', methods=['POST'])
def admin_notify_passwords():
    if not _is_admin():
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    broker_name = (data.get('broker_name') or request.form.get('broker_name') or 'FINVASIA').upper()
    # Send each client their current stored broker password (assumes rotation already updated DB)
    rows = _fetch_finvasia_rows()
    sent = 0
    failed = 0
    for r in rows:
        try:
            if r.get('email') and r.get('user_id_broker') and r.get('broker_password'):
                subject = f"Your {broker_name} password has been updated"
                body = (
                    f"Dear {r.get('full_name') or 'Client'},\n\n"
                    f"Your {broker_name} trading account credentials have been updated as requested by the administrator.\n\n"
                    f"User ID: {r['user_id_broker']}\n"
                    f"Password: {r['broker_password']}\n\n"
                    f"Please keep this information confidential.\n\n"
                    f"Regards,\nSmartETF"
                )
                send_client_notification_email(r['email'], subject, body)
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return jsonify({"status":"ok","sent": sent, "failed": failed}), 200

SFXS = ["321","647","743","654","913","525","687","945","125"]

def _sfx_for(uid: str) -> str:
    try:
        idx = zlib.crc32((uid or '').encode('utf-8')) % len(SFXS)
        return SFXS[idx]
    except Exception:
        return SFXS[0]

def _policy_password(full_name: str, uid: str) -> str | None:
    first = (full_name or '').split()[0] if full_name else ''
    cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    return f"{base}@{_sfx_for(uid)}"

def _fetch_finvasia_rows():
    sql = sa.text(
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
    )
    conn = db.engine.connect()
    try:
        rows = conn.execute(sql, {"broker": "FINVASIA"}).mappings().all()
        return rows
    finally:
        conn.close()

def _policy_new_password(full_name: str) -> str | None:
    nums = ["321","647","743"]
    first = (full_name or '').split()[0] if full_name else ''
    cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    return f"{base}@{random.choice(nums)}"

def _local_rotate_passwords_dry_run(broker_name: str) -> dict:
    rows = _fetch_finvasia_rows()
    items = []
    for r in rows:
        missing = []
        if not r["user_id_broker"]: missing.append("user_id_broker")
        if not r["broker_password"]: missing.append("password")
        if not r["totp_secret"]: missing.append("totp_secret")
        if not r["vendor_code"]: missing.append("vendor_code")
        if not r["api_secret"]: missing.append("api_secret")
        if not r["imei"]: missing.append("imei")
        items.append({
            "user_id": r["user_id"],
            "full_name": r["full_name"],
            "email": r["email"],
            "mobile": r["mobile"],
            "broker_username": r["user_id_broker"],
            "readiness": len(missing) == 0,
            "missing_fields": missing,
            "would_set_password_to": _policy_password(r["full_name"], r["user_id_broker"]) or ''
        })
    return {"status":"ok","broker": broker_name, "count": len(items), "items": items}

def _local_do_rotation(broker_name: str) -> dict:
    rows = _fetch_finvasia_rows()
    results = []
    ok = 0
    for r in rows:
        new_pw = _policy_password(r['full_name'], r['user_id_broker'])
        old_pw = r['broker_password']
        changed = False
        verified = False
        funds = None
        comments = ''
        if not new_pw:
            comments = 'Invalid first name for policy'
        else:
            def _totp():
                return pyotp.TOTP(r['totp_secret']).now() if r['totp_secret'] else ''
            try:
                success = change_password_for_client(
                    userid=r['user_id_broker'],
                    old_password=old_pw,
                    new_password=new_pw,
                    vendor_code=r['vendor_code'] or '',
                    api_secret=r['api_secret'] or '',
                    imei=r['imei'] or 'api-device',
                    totp_fn=_totp,
                    verify=True,
                )
                if success:
                    changed = True
                    verified = True
                    try:
                        b = db.session.get(Broker, r['broker_id'])
                        if b:
                            b.password = new_pw
                            b.last_updated = sa.func.now()
                            db.session.commit()
                    except Exception as ue:
                        db.session.rollback()
                        comments += f'; DB update error: {ue}'
                else:
                    comments = 'change/verify failed'
            except Exception as e:
                comments = str(e)
        results.append({
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
        })
        if changed and verified:
            ok += 1
    # Send admin summary email (HTML table)
    try:
        admin_email = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com')
        subject = f"Password Rotation Summary - {broker_name}"
        rows_html = "".join([
            f"<tr><td>{it['full_name'] or ''}</td><td>{it['broker_username'] or ''}</td><td>{it['new_password'] or ''}</td><td>{'OK' if (it['changed'] and it['verified']) else 'FAIL'}</td><td>{(it['comments'] or '')}</td></tr>"
            for it in results
        ])
        html = f"""
        <html><body>
        <h3>Password Rotation Summary - {broker_name}</h3>
        <p>Processed: {len(results)} | OK: {ok} | Failed: {len(results)-ok}</p>
        <table border="1" cellpadding="6" cellspacing="0">
        <thead><tr><th>Full Name</th><th>User ID</th><th>New Password</th><th>Status</th><th>Comments</th></tr></thead>
        <tbody>{rows_html}</tbody>
        </table>
        </body></html>
        """
        send_email(admin_email, subject, html, is_html=True)
    except Exception:
        pass
    return {"status":"ok","broker": broker_name, "processed": len(results), "ok": ok, "failed": len(results)-ok, "results": results}

def _local_rotation_start(broker_name: str) -> int:
    jid = max(JOBS.keys()) + 1 if JOBS else 1
    JOBS[jid] = {"status":"running","progress":{"processed":0,"total":None},"results":[],"started":time.time()}
    # Capture the real app object while we are in a valid context
    app = current_app._get_current_object()
    def _worker(app_obj):
        try:
            # Ensure Flask application context inside background thread
            with app_obj.app_context():
                rows = _fetch_finvasia_rows()
                JOBS[jid]["progress"]["total"] = len(rows)
                processed = 0
                ok = 0
                for r in rows:
                    new_pw = _policy_password(r['full_name'], r['user_id_broker'])
                    old_pw = r['broker_password']
                    changed = False
                    verified = False
                    comments = ''
                    if new_pw:
                        def _totp():
                            return pyotp.TOTP(r['totp_secret']).now() if r['totp_secret'] else ''
                        try:
                            success = change_password_for_client(
                                userid=r['user_id_broker'],
                                old_password=old_pw,
                                new_password=new_pw,
                                vendor_code=r['vendor_code'] or '',
                                api_secret=r['api_secret'] or '',
                                imei=r['imei'] or 'api-device',
                                totp_fn=_totp,
                                verify=True,
                            )
                            if success:
                                changed = True
                                verified = True
                                ok += 1
                                try:
                                    b = db.session.get(Broker, r['broker_id'])
                                    if b:
                                        b.password = new_pw
                                        b.last_updated = sa.func.now()
                                        db.session.commit()
                                except Exception:
                                    db.session.rollback()
                                    comments += '; DB update error'
                            else:
                                comments = 'change/verify failed'
                        except Exception as e:
                            comments = str(e)
                    else:
                        comments = 'Invalid first name for policy'
                    JOBS[jid]['results'].append({'broker_username': r['user_id_broker'], 'changed': changed, 'verified': verified, 'comments': comments})
                    processed += 1
                    JOBS[jid]['progress']['processed'] = processed
                JOBS[jid]['status'] = 'ok'
                JOBS[jid]['summary'] = {"processed": processed, "ok": ok, "failed": processed-ok}
                JOBS[jid]['ended'] = time.time()
                # Send admin summary email (HTML table)
                try:
                    admin_email = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com')
                    subject = f"Password Rotation Summary - {broker_name} (job {jid})"
                    rows_res = JOBS[jid].get('results') or []
                    rows_html = "".join([
                        f"<tr><td>{it.get('full_name','')}</td><td>{it.get('broker_username','')}</td><td>{it.get('new_password','')}</td><td>{'OK' if (it.get('changed') and it.get('verified')) else 'FAIL'}</td><td>{it.get('comments','')}</td></tr>"
                        for it in rows_res
                    ])
                    html = f"""
                    <html><body>
                    <h3>Password Rotation Summary - {broker_name}</h3>
                    <p>Processed: {processed} | OK: {ok} | Failed: {processed-ok}</p>
                    <table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">
                    <thead><tr><th>Full Name</th><th>User ID</th><th>New Password</th><th>Status</th><th>Comments</th></tr></thead>
                    <tbody>{rows_html}</tbody>
                    </table>
                    </body></html>
                    """
                    send_email(admin_email, subject, html, is_html=True)
                except Exception:
                    pass
        except Exception as e:
            JOBS[jid]['status'] = 'error'
            JOBS[jid]['error'] = str(e)
            JOBS[jid]['ended'] = time.time()
    threading.Thread(target=_worker, args=(app,), daemon=True).start()
    return jid

def _local_job_status(job_id: int) -> dict:
    j = JOBS.get(job_id)
    if not j:
        return {"status":"error","message":"job_not_found"}
    if j['status'] == 'running':
        return {"status":"running","job_id": job_id, "progress": j.get('progress',{})}
    return {"status": j['status'], "job_id": job_id, "progress": j.get('progress'), "summary": j.get('summary'), "error": j.get('error')}


# ---------------------------------------------------------------------------
# Dynamic Fall Calculator — status endpoint
# GET /admin/fall-data-status  →  JSON + optional HTML widget
# ---------------------------------------------------------------------------

@admin_extra_bp.route('/admin/fall-data-status', methods=['GET'])
def fall_data_status():
    """
    Returns the current phase of the dynamic average-fall calculator so admins
    can see at a glance whether the system is running on the hardcoded CSV or
    on live rolling data.

    Response JSON:
        phase          : 1 | 2 | 3
        phase_label    : "Hardcoded CSV" | "Blending" | "Fully Dynamic"
        days_collected : int   — trading-day CSV files saved so far
        days_needed    : int   — MIN_DATA_DAYS (90)
        blend_period   : int   — BLEND_PERIOD  (90)
        rolling_window : int   — ROLLING_DAYS  (365)
        blend_ratio    : float — 0.0-1.0 (only meaningful in Phase 2)
        days_to_next   : int   — days until next phase transition
        message        : str   — human-readable status line
        historical_folder : str
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        import sys, os
        # Resolve strategy_runner path so we can import the module
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)

        from dynamic_fall_calculator import (
            get_available_historical_days,
            MIN_DATA_DAYS, BLEND_PERIOD, ROLLING_DAYS,
            ENABLE_DYNAMIC_FALL, HISTORICAL_FOLDER,
        )

        days = get_available_historical_days()
        enabled = bool(ENABLE_DYNAMIC_FALL)

        if not enabled:
            phase = 0
            phase_label = "Disabled"
            blend_ratio = 0.0
            days_to_next = None
            message = "Dynamic fall calculation is DISABLED — always using hardcoded CSV."
        elif days < MIN_DATA_DAYS:
            phase = 1
            phase_label = "Hardcoded CSV only"
            blend_ratio = 0.0
            days_to_next = MIN_DATA_DAYS - days
            message = (
                f"Phase 1 — collecting data. {days} of {MIN_DATA_DAYS} days saved. "
                f"Need {days_to_next} more trading days before blending starts."
            )
        elif days < (MIN_DATA_DAYS + BLEND_PERIOD):
            phase = 2
            phase_label = "Blending (hardcoded + dynamic)"
            days_into_blend = days - MIN_DATA_DAYS
            blend_ratio = round(days_into_blend / BLEND_PERIOD, 3)
            days_to_next = (MIN_DATA_DAYS + BLEND_PERIOD) - days
            message = (
                f"Phase 2 — blending. {int(blend_ratio * 100)}% dynamic, "
                f"{int((1 - blend_ratio) * 100)}% hardcoded. "
                f"{days_to_next} more days until fully dynamic."
            )
        else:
            phase = 3
            phase_label = "Fully Dynamic"
            blend_ratio = 1.0
            days_to_next = 0
            message = (
                f"Phase 3 — fully dynamic. Using rolling average of last "
                f"{ROLLING_DAYS} days ({days} days of data collected)."
            )

        return jsonify({
            'phase':             phase,
            'phase_label':       phase_label,
            'enabled':           enabled,
            'days_collected':    days,
            'days_needed':       MIN_DATA_DAYS,
            'blend_period':      BLEND_PERIOD,
            'rolling_window':    ROLLING_DAYS,
            'blend_ratio':       blend_ratio,
            'days_to_next':      days_to_next,
            'message':           message,
            'historical_folder': os.path.abspath(HISTORICAL_FOLDER),
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
