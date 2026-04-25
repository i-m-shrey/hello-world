# SmartETF - Automated ETF Trading Platform

Intelligent ETF investment platform with automated order execution based on market conditions and user-defined strategies.

## 🏗️ Architecture

SmartETF consists of two microservices designed for Google Cloud Run:

### 1. **Backend Service**
- Flask web application serving the user portal
- Admin dashboard for managing users, brokers, and subscriptions
- Payment integration with Razorpay
- Database management (PostgreSQL via Supabase)
- RESTful API for frontend

### 2. **Runner Service**
- Headless Chrome/Selenium for broker automation
- Strategy execution engine
- ETF data fetching and analysis
- Multi-broker order placement (Zerodha, Dhan, Finvasia, etc.)
- Scheduled execution via Cloud Scheduler

## 📦 Project Structure

```
SmartETF_Merged_Full_Project/
├── app.py                      # Main Flask application
├── models.py                   # Database models
├── api_routes.py              # API endpoints
├── admin_extra_routes.py      # Admin-specific routes
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Backend container config
├── deploy-backend.sh          # Backend deployment script
├── .env.example              # Environment variables template
│
├── strategy_runner/          # Strategy execution logic
│   ├── etf_automated.py     # Main strategy orchestrator
│   ├── fetch_etf_data.py    # ETF data fetching
│   ├── filter_etfs.py       # ETF filtering & selection
│   ├── order_executor_generic.py
│   └── ...
│
├── smartetf-runner/         # Runner microservice
│   ├── runner.py            # Runner Flask app
│   ├── Dockerfile           # Runner container (with Chrome)
│   ├── deploy-runner.sh     # Runner deployment script
│   ├── requirements.txt     # Runner dependencies
│   └── appsrc/             # Shared code from backend
│
├── templates/               # Jinja2 HTML templates
│   ├── admin/              # Admin dashboard
│   ├── client/             # Client dashboard
│   ├── marketing/          # Landing pages
│   └── legal/              # Terms, privacy policy
│
├── static/                  # CSS, JS, images
│   ├── css/
│   ├── js/
│   └── images/
│
└── data/                    # Data files
    ├── accounts.csv
    └── dhan_scrip_master.csv
```

## 🚀 Quick Start

### Prerequisites
- Google Cloud Platform account
- PostgreSQL database (Supabase recommended)
- Razorpay account (for payments)
- SMTP credentials (for emails)

### 1. Clone & Setup
```bash
# Clone or download the project
cd SmartETF_Merged_Full_Project

# Copy environment templates
cp .env.example .env
cp smartetf-runner/.env.example smartetf-runner/.env

# Edit both .env files with your credentials
nano .env
nano smartetf-runner/.env
```

### 2. Deploy Backend
```bash
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="asia-south1"

# Deploy backend service
./deploy-backend.sh

# Set environment variables
gcloud run services update smartetf-backend \
  --env-vars-file=.env \
  --region=$GCP_REGION
```

### 3. Deploy Runner
```bash
# Deploy runner service (takes 5-10 minutes)
cd smartetf-runner
./deploy-runner.sh

# Set environment variables
gcloud run services update smartetf-runner \
  --env-vars-file=.env \
  --region=$GCP_REGION
```

### 4. Connect Services
```bash
# Get runner URL
RUNNER_URL=$(gcloud run services describe smartetf-runner \
  --region=$GCP_REGION \
  --format='value(status.url)')

# Update backend with runner URL
gcloud run services update smartetf-backend \
  --update-env-vars="RUNNER_URL=$RUNNER_URL" \
  --region=$GCP_REGION
```

### 5. Setup Cloud Scheduler (Optional)
```bash
# Create service account for scheduler
gcloud iam service-accounts create smartetf-scheduler

# Grant invoker permissions
gcloud run services add-iam-policy-binding smartetf-runner \
  --member="serviceAccount:smartetf-scheduler@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Create scheduled job (weekdays at 9:30 AM IST)
gcloud scheduler jobs create http smartetf-daily-run \
  --schedule="30 9 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="$RUNNER_URL/run-now" \
  --http-method=POST \
  --oidc-service-account-email="smartetf-scheduler@$GCP_PROJECT_ID.iam.gserviceaccount.com"
```

## 🔧 Configuration

### Backend Environment Variables
See `.env.example` for all available configuration options.

Key variables:
- `DB_URL` - PostgreSQL connection string
- `SECRET_KEY` - Flask session secret
- `RUNNER_URL` - URL of runner service
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` - Payment credentials
- `SMTP_*` - Email server configuration

### Runner Environment Variables
See `smartetf-runner/.env.example` for runner-specific options.

Key variables:
- `RUN_MODE=headless` - Required for Cloud Run
- `WINDOW_MINUTES=3` - Execution time window
- `LOCK_MINUTES=15` - Prevents duplicate runs
- Broker API credentials (Finvasia, Zerodha, Dhan, etc.)

## 📊 Features

### For Users
- ✅ Automated ETF investment based on market dips
- ✅ Multiple broker support
- ✅ SIP-style monthly investment tracking
- ✅ Real-time order status
- ✅ Portfolio analytics
- ✅ Email notifications

### For Admins
- ✅ User management dashboard
- ✅ Subscription & payment tracking
- ✅ Manual strategy execution
- ✅ System health monitoring
- ✅ Broker password management
- ✅ Execution logs & reports

### Trading Strategy
- Monitors market indices (Nifty 50, Bank Nifty, etc.)
- Calculates percentage falls from recent peaks
- Identifies buying opportunities during dips
- Automatically places orders across configured brokers
- Tracks monthly investment limits
- Generates detailed execution reports

## 🛠️ Development

### Local Testing

**Backend:**
```bash
pip install -r requirements.txt
export FLASK_APP=app.py
export FLASK_ENV=development
flask run --port=8080
```

**Runner:**
```bash
cd smartetf-runner
pip install -r requirements.txt
python runner.py
```

### Database Migrations
```bash
# The application auto-creates tables on first run
# Or manually initialize:
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

## 📝 API Endpoints

### Backend
- `GET /` - Landing page
- `POST /register` - User registration
- `POST /login` - User authentication
- `GET /client/dashboard` - Client dashboard
- `GET /admin/dashboard` - Admin dashboard
- `POST /admin/execute-now` - Trigger manual execution

### Runner
- `POST /run-now` - Execute strategy (authenticated)
- `POST /health-now` - Run health check
- `GET /health` - Service health status

## 🔒 Security

- ✅ Password hashing with Werkzeug
- ✅ Session management with Flask
- ✅ Encrypted broker credentials
- ✅ HTTPS-only communication
- ✅ Runner service requires authentication
- ✅ Database connection pooling with SSL
- ✅ Environment-based secrets

## 📈 Monitoring

### View Logs
```bash
# Backend logs
gcloud run services logs read smartetf-backend --limit=100

# Runner logs
gcloud run services logs read smartetf-runner --limit=100

# Follow logs in real-time
gcloud run services logs tail smartetf-backend
```

### Health Checks
- Backend: `https://your-backend.run.app/health`
- Runner: Available via backend admin dashboard

## 🐛 Troubleshooting

### Common Issues

**Issue: Runner fails to start**
- Check memory allocation (needs 2GB+)
- Verify Chrome dependencies in Dockerfile
- Check RUN_MODE=headless is set

**Issue: Database connection timeout**
- Verify DB_URL is correct in both services
- Check database allows connections from Cloud Run
- Ensure connection pooling settings are appropriate

**Issue: Orders not executing**
- Verify broker credentials in environment
- Check broker API access is enabled
- Review runner logs for detailed errors
- Ensure market hours and trading days

**Issue: Email notifications not working**
- Verify SMTP credentials
- Check SMTP port (587 for TLS)
- Enable "Less secure app access" or use app passwords

## 💰 Cost Estimates

Typical monthly costs on Google Cloud:
- Backend: $5-15 (scales to zero when idle)
- Runner: $10-20 (minimal usage, executes ~20 days/month)
- Database: $0-25 (Supabase free tier available)
- **Total: $15-60/month**

## 📚 Documentation

- [DEPLOYMENT.md](DEPLOYMENT.md) - Detailed deployment guide
- [.env.example](.env.example) - Configuration reference
- [smartetf-runner/.env.example](smartetf-runner/.env.example) - Runner config

## 📄 License

Proprietary - SmartETF Platform

## 🤝 Support

For issues or questions:
- Email: smartetfalgo@gmail.com
- Check logs for detailed error messages
- Review Cloud Run quotas and limits

---

**Built with:** Python 3.11, Flask, SQLAlchemy, Selenium, PostgreSQL, Google Cloud Run
