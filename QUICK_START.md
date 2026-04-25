# Quick Start Guide

Get SmartETF running on Google Cloud in 15 minutes.

## ⚡ Prerequisites

1. Google Cloud account with billing enabled
2. `gcloud` CLI installed ([Install guide](https://cloud.google.com/sdk/docs/install))
3. PostgreSQL database (get free tier at [supabase.com](https://supabase.com))
4. Razorpay account ([razorpay.com](https://razorpay.com))

## 🚀 5-Step Deployment

### Step 1: Configure gcloud
```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
export GCP_PROJECT_ID="YOUR_PROJECT_ID"
```

### Step 2: Setup Environment Files
```bash
# In project root
cp .env.example .env
cp smartetf-runner/.env.example smartetf-runner/.env

# Edit with your credentials
nano .env
nano smartetf-runner/.env
```

**Minimum required in `.env`:**
```bash
DB_URL=postgresql+pg8000://user:pass@host:6543/db
SECRET_KEY=$(openssl rand -hex 32)
RUNNER_TOKEN=$(openssl rand -hex 32)
RAZORPAY_KEY_ID=rzp_test_xxxxx
RAZORPAY_KEY_SECRET=xxxxx
ADMIN_EMAIL=your-email@example.com
```

**Minimum required in `smartetf-runner/.env`:**
```bash
DB_URL=postgresql+pg8000://user:pass@host:6543/db
RUN_MODE=headless
RUNNER_TOKEN=<same-as-backend>
```

### Step 3: Deploy Backend
```bash
gcloud run deploy smartetf-backend \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120

# Set environment variables
gcloud run services update smartetf-backend \
  --update-env-vars="$(cat .env | tr '\n' ',' | sed 's/,$//')" \
  --region asia-south1
```

### Step 4: Deploy Runner
```bash
cd smartetf-runner

gcloud run deploy smartetf-runner \
  --source . \
  --region asia-south1 \
  --no-allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 900 \
  --concurrency 1

# Set environment variables
gcloud run services update smartetf-runner \
  --update-env-vars="$(cat .env | tr '\n' ',' | sed 's/,$//')" \
  --region asia-south1
```

### Step 5: Connect Services
```bash
# Get runner URL
RUNNER_URL=$(gcloud run services describe smartetf-runner \
  --region asia-south1 \
  --format='value(status.url)')

# Update backend
cd ..
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=$RUNNER_URL" \
  --region asia-south1
```

## ✅ Verify Deployment

### Test Backend
```bash
BACKEND_URL=$(gcloud run services describe smartetf-backend \
  --region asia-south1 \
  --format='value(status.url)')

curl $BACKEND_URL
# Should return HTML landing page
```

### Test Admin Login
1. Visit: `https://your-backend-url.run.app/admin/dashboard`
2. Create admin user via database or registration
3. Login and test "Execute Now" button

### View Logs
```bash
# Backend
gcloud run services logs tail smartetf-backend --region asia-south1

# Runner
gcloud run services logs tail smartetf-runner --region asia-south1
```

## 🔄 Update Deployment

### Update Backend
```bash
# Make code changes, then:
gcloud run deploy smartetf-backend \
  --source . \
  --region asia-south1
```

### Update Runner
```bash
cd smartetf-runner
gcloud run deploy smartetf-runner \
  --source . \
  --region asia-south1
```

### Update Environment Variables
```bash
# Update single variable
gcloud run services update smartetf-backend \
  --update-env-vars="KEY=VALUE" \
  --region asia-south1

# Update from file
gcloud run services update smartetf-backend \
  --update-env-vars="$(cat .env | tr '\n' ',' | sed 's/,$//')" \
  --region asia-south1
```

## 🕒 Setup Scheduling (Optional)

```bash
# Create service account
gcloud iam service-accounts create smartetf-scheduler

# Grant permissions
gcloud run services add-iam-policy-binding smartetf-runner \
  --member="serviceAccount:smartetf-scheduler@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --region asia-south1

# Create job (Mon-Fri at 9:30 AM IST)
gcloud scheduler jobs create http smartetf-daily \
  --schedule="30 9 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="$RUNNER_URL/run-now" \
  --http-method=POST \
  --oidc-service-account-email="smartetf-scheduler@$GCP_PROJECT_ID.iam.gserviceaccount.com"

# Test the job
gcloud scheduler jobs run smartetf-daily
```

## 🐛 Common Issues

### "Permission Denied" Error
```bash
# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

### Database Connection Fails
- Check DB_URL format: `postgresql+pg8000://user:pass@host:port/db`
- URL-encode special characters in password
- Verify database allows external connections

### Runner Timeout
- Increase timeout: `--timeout 900`
- Check broker credentials are correct
- Verify market hours (won't execute outside trading hours)

### Out of Memory
- Increase memory:
  - Backend: `--memory 1Gi` → `--memory 2Gi`
  - Runner: `--memory 2Gi` → `--memory 4Gi`

## 📊 Monitoring

### Cloud Run Dashboard
```bash
# Open in browser
gcloud run services describe smartetf-backend --region asia-south1
gcloud run services describe smartetf-runner --region asia-south1
```

### Resource Usage
```bash
# Check metrics in Cloud Console
echo "https://console.cloud.google.com/run?project=$GCP_PROJECT_ID"
```

## 💡 Tips

1. **Use Secrets Manager** for sensitive data:
   ```bash
   # Create secret
   echo -n "my-secret-value" | gcloud secrets create db-password --data-file=-
   
   # Use in Cloud Run
   gcloud run services update smartetf-backend \
     --update-secrets=DB_PASSWORD=db-password:latest
   ```

2. **Set minimum instances** to reduce cold starts:
   ```bash
   gcloud run services update smartetf-backend \
     --min-instances=1  # Keeps 1 instance warm
   ```

3. **Enable HTTP/2** for better performance:
   ```bash
   gcloud run services update smartetf-backend \
     --use-http2
   ```

4. **Set up alerts** for errors:
   - Go to Cloud Console → Monitoring → Alerting
   - Create alert for Cloud Run error rate > 5%

## 📚 Next Steps

- ✅ Configure broker API credentials
- ✅ Test order execution manually
- ✅ Setup Cloud Scheduler for automation
- ✅ Configure email notifications
- ✅ Review execution logs
- ✅ Add custom domain (optional)

## 🆘 Need Help?

1. Check logs: `gcloud run services logs read SERVICE_NAME --limit=50`
2. Review [DEPLOYMENT.md](DEPLOYMENT.md) for detailed docs
3. Email: smartetfalgo@gmail.com

---

**Total deployment time: ~15 minutes**
**Monthly cost: ~$15-60 (scales to zero when idle)**
