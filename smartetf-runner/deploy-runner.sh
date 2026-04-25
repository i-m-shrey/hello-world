#!/bin/bash
set -e

echo "🚀 Deploying SmartETF Runner Service to Google Cloud Run..."

PROJECT_ID=${GCP_PROJECT_ID:-"your-project-id"}
REGION=${GCP_REGION:-"asia-south1"}
SERVICE_NAME="smartetf-runner"

if [ "$PROJECT_ID" == "your-project-id" ]; then
    echo "❌ Error: Please set GCP_PROJECT_ID environment variable"
    echo "   export GCP_PROJECT_ID=your-actual-project-id"
    exit 1
fi

gcloud config set project $PROJECT_ID

echo "📦 Building and deploying runner (includes Chrome/Selenium)..."
echo "⚠️  This may take 5-10 minutes due to Chrome installation..."

gcloud run deploy $SERVICE_NAME \
  --source . \
  --platform managed \
  --region $REGION \
  --no-allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --cpu 2 \
  --min-instances 0 \
  --max-instances 3 \
  --timeout 900 \
  --concurrency 1

echo ""
echo "✅ Runner deployed successfully!"
echo ""
echo "📝 Next steps:"
echo "1. Note the service URL above"
echo "2. Set environment variables:"
echo "   gcloud run services update $SERVICE_NAME --update-env-vars='DB_URL=your-db-url,RUN_MODE=headless'"
echo "3. Update backend with runner URL:"
echo "   gcloud run services update smartetf-backend --update-env-vars='RUNNER_URL=<runner-url>,RUNNER_TOKEN=your-token'"
