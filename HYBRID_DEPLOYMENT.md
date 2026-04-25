# SmartETF Hybrid Deployment Configuration

## Current Setup (Optimized for Your Use Case)

```
┌─────────────────────┐
│   Users/Browser     │
└──────────┬──────────┘
           │ HTTPS
           ▼
┌─────────────────────────┐
│  Backend (Cloud Run)    │ ← FREE Tier (us-region)
│  • Flask Web App        │ ← OPTIMIZED for cold starts
│  • User Portal         │
│  • Admin Dashboard     │
└──────────┬──────────────┘
           │ HTTP/HTTPS
           │ (RUNNER_URL)
           ▼
┌─────────────────────────┐
│  Runner (Local 24/7)    │ ← Your Machine
│  • Strategy Execution   │ ← NO CLOUD COSTS
│  • Browser Automation   │
│  • Order Placement      │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  PostgreSQL (Supabase)  │
└─────────────────────────┘
```

## Environment Configuration

### Backend (.env)
```bash
# Database
DB_URL=postgresql+pg8000://...

# Flask
SECRET_KEY=your-secret-key
APP_BASE_URL=https://your-backend.run.app

# Runner Configuration - POINT TO LOCAL OR CLOUD
# Option 1: Local Runner (Current Setup)
RUNNER_URL=http://your-local-ip:8080
# OR
RUNNER_URL=https://your-ngrok-url.ngrok.io
# OR
RUNNER_URL=http://your-home-ip:8080

# Option 2: Cloud Runner (Future - Just Change URL)
# RUNNER_URL=https://smartetf-runner-xxx.a.run.app

RUNNER_TOKEN=your-shared-secret-token

# Rest of config...
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
SMTP_SERVER=...
```

### Runner (Local or Cloud - Same Config)
```bash
# Database (same as backend)
DB_URL=postgresql+pg8000://...

# Runner Settings
RUN_MODE=headless
RUNNER_TOKEN=your-shared-secret-token  # MUST MATCH BACKEND
WINDOW_MINUTES=3
LOCK_MINUTES=15

# Broker Credentials
FINVASIA_VENDOR_CODE=...
FINVASIA_API_SECRET=...
# etc...
```

## Switch Between Local & Cloud Runner (3 Steps)

### Currently Using: Local Runner ✅

**Advantages:**
- ✅ $0 cloud runner costs
- ✅ Full control
- ✅ Fast execution (no cold starts)
- ✅ Can access local resources

**Setup:**
1. Runner runs on your local machine 24/7
2. Backend points to local runner via RUNNER_URL
3. Use ngrok or port forwarding to expose local runner

### Switch to Cloud Runner (When Needed)

**When to Switch:**
- Need higher reliability
- Local machine downtime
- Want automated scaling
- Don't want to manage local server

**3 Steps to Switch:**

#### Step 1: Deploy Cloud Runner (5 min)
```bash
cd smartetf-runner

# Deploy to Cloud Run
gcloud run deploy smartetf-runner \
  --source . \
  --region=asia-south1 \
  --no-allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 900 \
  --concurrency 1 \
  --set-env-vars="$(cat .env | tr '\n' ',' | sed 's/,$//')"

# Get runner URL
RUNNER_URL=$(gcloud run services describe smartetf-runner \
  --region=asia-south1 \
  --format='value(status.url)')

echo "Runner URL: $RUNNER_URL"
```

#### Step 2: Update Backend (1 min)
```bash
# Update backend to point to cloud runner
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=$RUNNER_URL" \
  --region=us-central1
```

#### Step 3: Stop Local Runner
```bash
# Stop local runner process
# Now cloud runner handles everything
```

### Switch Back to Local Runner

**3 Steps to Switch Back:**

#### Step 1: Start Local Runner
```bash
cd smartetf-runner
python runner.py
# Or use systemd/pm2 to run as service
```

#### Step 2: Update Backend
```bash
# Update backend to point to local runner
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=http://your-local-ip:8080" \
  --region=us-central1
```

#### Step 3: Stop Cloud Runner (Save Money)
```bash
# Option A: Delete cloud runner (stop billing)
gcloud run services delete smartetf-runner --region=asia-south1

# Option B: Scale to zero (keep for quick restart)
gcloud run services update smartetf-runner \
  --max-instances=0 \
  --region=asia-south1
```

## Local Runner Setup (Your Current Setup)

### Option A: Direct IP (Simple)
```bash
# On local machine
cd smartetf-runner
export DB_URL="postgresql+pg8000://..."
export RUNNER_TOKEN="your-token"
python runner.py
```

**Backend .env:**
```bash
RUNNER_URL=http://YOUR_LOCAL_IP:8080
```

**Pros:** Simple, no extra tools
**Cons:** Backend must be able to reach your local IP

### Option B: Ngrok Tunnel (Recommended)
```bash
# Terminal 1: Run runner
cd smartetf-runner
python runner.py

# Terminal 2: Expose via ngrok
ngrok http 8080
```

**Backend .env:**
```bash
RUNNER_URL=https://abc123.ngrok.io
```

**Pros:** Works from anywhere, HTTPS
**Cons:** Free ngrok URLs change on restart

### Option C: Static Tunnel (Best)
```bash
# Use ngrok with static domain (paid) or cloudflared (free)

# Cloudflare Tunnel (FREE)
cloudflared tunnel --url http://localhost:8080
```

**Pros:** Free, persistent URL
**Cons:** One-time setup

### Option D: Systemd Service (Production)
```bash
# Create service file
sudo nano /etc/systemd/system/smartetf-runner.service
```

```ini
[Unit]
Description=SmartETF Runner Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/smartetf-runner
Environment="DB_URL=postgresql+pg8000://..."
Environment="RUNNER_TOKEN=your-token"
ExecStart=/usr/bin/python3 runner.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable smartetf-runner
sudo systemctl start smartetf-runner
sudo systemctl status smartetf-runner
```

## Cost Comparison

| Setup | Backend Cost | Runner Cost | Total/Month |
|-------|-------------|-------------|-------------|
| **Current (Backend Cloud + Runner Local)** | $0-5 | $0 | **$0-5** |
| Backend Cloud + Runner Cloud (asia) | $0-5 | $15-30 | $15-35 |
| Backend Cloud (warm) + Runner Local | $5-15 | $0 | $5-15 |
| Both Cloud (both regions) | $0-5 | $15-30 | $15-35 |

**Your current setup is MOST cost-effective!**

## Deployment Flexibility

### Deploy Backend Only (Current)
```bash
cd /path/to/SmartETF_Merged_Full_Project

# Deploy backend
./deploy-backend.sh

# Set runner URL to local
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=http://your-local-ip:8080,RUNNER_TOKEN=your-token" \
  --region=us-central1
```

### Deploy Runner to Cloud (Future)
```bash
cd smartetf-runner

# Deploy runner
./deploy-runner.sh

# Update backend
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=https://your-runner.run.app" \
  --region=us-central1
```

### Deploy Both (If Needed)
```bash
# Backend
./deploy-backend.sh

# Runner
cd smartetf-runner
./deploy-runner.sh

# Connect them
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=$(gcloud run services describe smartetf-runner --region=asia-south1 --format='value(status.url)')" \
  --region=us-central1
```

## Testing Runner Connection

### From Backend, Test Runner
```bash
# SSH to Cloud Run or use Cloud Shell
curl -X POST "http://your-runner-url:8080/health" \
  -H "Authorization: Bearer your-token"

# Should return: {"status": "ok"}
```

### From Admin Dashboard
1. Login to admin panel
2. Click "Execute Now" or "Health Check"
3. Should see success message

### Check Logs
```bash
# Backend logs
gcloud run services logs read smartetf-backend --limit=50

# Local runner logs
tail -f /path/to/smartetf-runner/logs/order_execution_*.log
```

## Security Considerations

### Local Runner Exposure
- ✅ Use RUNNER_TOKEN for authentication
- ✅ Use HTTPS (ngrok/cloudflared)
- ✅ Firewall: Only allow backend IP
- ✅ Don't expose runner publicly without auth

### Cloud Runner
- ✅ `--no-allow-unauthenticated` flag
- ✅ RUNNER_TOKEN in environment
- ✅ Backend authenticates with token

## Monitoring

### Local Runner
```bash
# Check if running
ps aux | grep runner.py

# View logs
tail -f logs/order_execution_*.log

# Check resource usage
htop
# or
top
```

### Cloud Runner (When Deployed)
```bash
gcloud run services logs tail smartetf-runner --region=asia-south1
```

### Backend
```bash
gcloud run services logs tail smartetf-backend --region=us-central1
```

## Troubleshooting

### Backend Can't Reach Local Runner
**Problem:** "Runner request failed: Connection refused"

**Solutions:**
1. Check runner is running: `ps aux | grep runner.py`
2. Check firewall allows port 8080
3. Verify RUNNER_URL is correct
4. Use ngrok for reliable connection

### Runner Authentication Fails
**Problem:** "Unauthorized" or "403 Forbidden"

**Solution:** Verify RUNNER_TOKEN matches in both:
- Backend `.env`: `RUNNER_TOKEN=abc123`
- Local runner `.env`: `RUNNER_TOKEN=abc123`

### Orders Not Executing
**Problem:** Manual execution from admin panel fails

**Solutions:**
1. Check runner logs: `tail -f logs/order_execution_*.log`
2. Verify broker credentials in runner `.env`
3. Check database connection from runner
4. Test runner directly: `curl -X POST http://localhost:8080/run-now?token=your-token`

## Best Practices

### For Your Current Setup (Local Runner)

1. **Use Process Manager:**
   ```bash
   # Install PM2
   npm install -g pm2
   
   # Run runner with PM2
   pm2 start runner.py --name smartetf-runner --interpreter python3
   pm2 save
   pm2 startup
   ```

2. **Use Persistent Tunnel:**
   - Ngrok with static domain ($8/month)
   - Cloudflare Tunnel (FREE)
   - Port forwarding with static IP

3. **Monitor Health:**
   ```bash
   # Add to crontab
   */5 * * * * curl http://localhost:8080/health || echo "Runner down!" | mail -s "Alert" you@email.com
   ```

4. **Backup Strategy:**
   - Keep cloud runner config ready
   - Document switch process
   - Test switching quarterly

## Quick Reference

### Current Setup Commands
```bash
# Start local runner
cd smartetf-runner && python runner.py

# Check runner status
curl http://localhost:8080/health

# View runner logs
tail -f logs/order_execution_*.log

# Update backend runner URL
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=http://your-ip:8080"
```

### Switch to Cloud Commands
```bash
# Deploy cloud runner
cd smartetf-runner && ./deploy-runner.sh

# Update backend
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=https://runner-url.run.app"

# Stop local runner
pm2 stop smartetf-runner
```

---

**Your setup is OPTIMAL for cost savings while maintaining flexibility!**
