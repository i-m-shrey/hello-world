# SmartETF Google Cloud Deployment Guide

This project requires **two separate Cloud Run services**:

## 1. Backend Service (Main Application)
The main Flask web application serving the portal.

### Deploy Backend
```bash
cd /path/to/SmartETF_Merged_Full_Project

gcloud run deploy smartetf-backend \
  --source . \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars="DB_URL=YOUR_DB_URL,SECRET_KEY=YOUR_SECRET_KEY,RUNNER_URL=https://smartetf-runner-xxx.run.app,RUNNER_TOKEN=YOUR_RUNNER_TOKEN"
```

### Backend Environment Variables
Required:
- `DB_URL` - PostgreSQL connection string
- `SECRET_KEY` - Flask secret key
- `RUNNER_URL` - URL of the runner service (set after deploying runner)
- `RUNNER_TOKEN` - Shared secret to authenticate runner requests
- `RAZORPAY_KEY_ID` - Payment gateway key
- `RAZORPAY_KEY_SECRET` - Payment gateway secret
- `SMTP_*` - Email configuration
- `ADMIN_EMAIL` - Admin notification email

## 2. Runner Service (Strategy Execution)
The background service that executes trading strategies with browser automation.

### Deploy Runner
```bash
cd /path/to/SmartETF_Merged_Full_Project/smartetf-runner

gcloud run deploy smartetf-runner \
  --source . \
  --platform managed \
  --region asia-south1 \
  --no-allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 900 \
  --concurrency 1 \
  --set-env-vars="DB_URL=YOUR_DB_URL,RUN_MODE=headless,WINDOW_MINUTES=3,LOCK_MINUTES=15"
```

### Runner Environment Variables
Required:
- `DB_URL` - Same PostgreSQL connection string as backend
- `RUN_MODE` - Set to `headless` for Cloud Run
- `RUNNER_TOKEN` - Same token as backend (for authentication)
- `WINDOW_MINUTES` - Execution window (default: 3)
- `LOCK_MINUTES` - Lock duration to prevent duplicate runs (default: 15)
- `FINVASIA_*` - Broker API credentials (if using Finvasia)
- `ADMIN_EMAIL` - For notifications

### Runner Features
- Includes Chrome/Selenium for browser automation
- Handles ETF order execution
- Supports multiple brokers (Zerodha, Dhan, Finvasia, etc.)
- Scheduled execution via Cloud Scheduler

## 3. Connect Services

After deploying both services:

1. Copy the runner service URL from Cloud Run console
2. Update backend with runner URL:
```bash
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=https://smartetf-runner-xxx.run.app"
```

## 4. Setup Cloud Scheduler (Optional)

Create a scheduled job to trigger strategy execution:

```bash
gcloud scheduler jobs create http smartetf-daily-run \
  --schedule="30 9 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="https://smartetf-runner-xxx.run.app/run-now" \
  --http-method=POST \
  --oidc-service-account-email=YOUR_SERVICE_ACCOUNT@project.iam.gserviceaccount.com \
  --headers="Authorization=Bearer YOUR_RUNNER_TOKEN"
```

## Architecture

```
┌─────────────┐
│   Users     │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  Backend Service    │◄─── Cloud Scheduler
│  (Flask Web App)    │
└──────┬──────────────┘
       │ HTTP API
       ▼
┌─────────────────────┐
│  Runner Service     │
│  (Strategy Engine)  │
│  + Chrome/Selenium  │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│   PostgreSQL DB     │
│   (Supabase)        │
└─────────────────────┘
```

## File Structure

```
SmartETF_Merged_Full_Project/
├── Dockerfile               # Backend Docker config
├── app.py                   # Main Flask application
├── requirements.txt         # Backend dependencies
├── models.py               # Database models
├── templates/              # HTML templates
├── static/                 # CSS, JS, images
├── strategy_runner/        # Strategy logic (shared)
└── smartetf-runner/        # Runner service
    ├── Dockerfile          # Runner Docker config
    ├── runner.py           # Runner Flask app
    ├── requirements.txt    # Runner dependencies
    └── appsrc/            # Shared code from backend
```

## Deployment Checklist

- [ ] Deploy backend service
- [ ] Deploy runner service  
- [ ] Update backend with runner URL
- [ ] Configure environment variables for both services
- [ ] Setup Cloud Scheduler (optional)
- [ ] Test manual execution from admin dashboard
- [ ] Verify database connectivity
- [ ] Check logs for both services

## Monitoring

View logs:
```bash
# Backend logs
gcloud run services logs read smartetf-backend --limit=50

# Runner logs
gcloud run services logs read smartetf-runner --limit=50
```

## Cost Optimization

- Backend: 1 vCPU, 1GB RAM (scales to zero)
- Runner: 2 vCPU, 2GB RAM (concurrency: 1 for sequential execution)
- Set minimum instances to 0 to reduce costs when idle
- Use Cloud Scheduler to trigger runs only during market hours

## Security Notes

- Runner service is NOT publicly accessible (`--no-allow-unauthenticated`)
- Backend calls runner with authentication token
- Database credentials stored in environment variables
- Broker passwords encrypted in database
