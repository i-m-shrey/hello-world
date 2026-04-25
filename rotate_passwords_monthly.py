import os
import sys
import time
import json
import requests

RUNNER_URL = os.environ.get('RUNNER_URL', '').rstrip('/')
RUNNER_TOKEN = os.environ.get('RUNNER_TOKEN', '')
BROKER = os.environ.get('BROKER_NAME', 'FINVASIA').upper()
POLL_SEC = int(os.environ.get('POLL_SECONDS', '5'))
TIMEOUT_MIN = int(os.environ.get('TIMEOUT_MINUTES', '30'))

if not RUNNER_URL:
    print('ERROR: Set RUNNER_URL to your runner service base URL (e.g., https://smartetf-runner-xxx.run.app)')
    sys.exit(2)

headers = {'Content-Type': 'application/json'}

params = {}
if RUNNER_TOKEN:
    params['token'] = RUNNER_TOKEN

# 1) Start rotation job
start_url = f"{RUNNER_URL}/rotate-passwords/start"
try:
    r = requests.post(start_url, params=params, json={'broker_name': BROKER}, timeout=60)
    data = r.json() if r.headers.get('content-type','').startswith('application/json') else {'status':'error','message':r.text}
except Exception as e:
    print(f'ERROR: Failed to start job: {e}')
    sys.exit(1)

if data.get('status') != 'ok' or not data.get('job_id'):
    print(f'ERROR: Start failed: {data}')
    sys.exit(1)

job_id = int(data['job_id'])
print(f"Rotation job started (broker={BROKER}) job_id={job_id}")

# 2) Poll status until completion or timeout
start_ts = time.time()
status_url = f"{RUNNER_URL}/jobs/{job_id}"
while True:
    if time.time() - start_ts > TIMEOUT_MIN * 60:
        print('ERROR: Timeout waiting for rotation to complete')
        sys.exit(1)
    try:
        rs = requests.get(status_url, params=params, timeout=30)
        st = rs.json() if rs.headers.get('content-type','').startswith('application/json') else {'status':'error','message':rs.text}
    except Exception as e:
        print(f'WARN: status fetch error: {e}')
        time.sleep(POLL_SEC)
        continue
    if st.get('status') == 'running':
        pr = st.get('progress', {})
        print(f"Running: {pr.get('processed',0)}/{pr.get('total','?')} processed...")
        time.sleep(POLL_SEC)
        continue
    if st.get('status') == 'ok':
        summ = (st.get('summary') or {})
        print(f"DONE: processed={summ.get('processed')}, ok={summ.get('ok')}, failed={summ.get('failed')}")
        sys.exit(0)
    print(f"ERROR: job status={st.get('status')} error={st.get('error') or st.get('message')}")
    sys.exit(1)
