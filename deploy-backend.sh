#!/bin/bash
set -e

echo "🚀 Deploying SmartETF Backend Service to Google Cloud Run..."

PROJECT_ID=${GCP_PROJECT_ID:-"your-project-id"}
REGION=${GCP_REGION:-"asia-south1"}
SERVICE_NAME="smartetf-backend"

if [ "$PROJECT_ID" == "your-project-id" ]; then
    echo "❌ Error: Please set GCP_PROJECT_ID environment variable"
    echo "   export GCP_PROJECT_ID=your-actual-project-id"
    exit 1
fi

gcloud config set project $PROJECT_ID

echo "📦 Building and deploying backend..."
gcloud run deploy $SERVICE_NAME \
  --source . \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 10 \
  --timeout 120 \
  --concurrency 80

echo ""
echo "✅ Backend deployed successfully!"
echo ""
echo "📝 Next steps:"
echo "1. Note the service URL above"
echo "2. Set environment variables:"
echo "   gcloud run services update $SERVICE_NAME --update-env-vars='DB_URL=your-db-url,SECRET_KEY=your-secret'"
echo "3. Deploy runner service: cd smartetf-runner && ./deploy-runner.sh"
