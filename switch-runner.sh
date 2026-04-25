#!/bin/bash
# Quick switch between local and cloud runner

set -e

echo "🔄 SmartETF Runner Switcher"
echo ""
echo "Current setup:"
echo "  Backend: Cloud Run (us-region)"
echo "  Runner: Choose local or cloud"
echo ""
echo "Select option:"
echo "  1) Switch to LOCAL runner (your machine)"
echo "  2) Switch to CLOUD runner (Google Cloud Run)"
echo "  3) Show current configuration"
echo ""
read -p "Enter choice (1-3): " choice

BACKEND_SERVICE="smartetf-backend"
BACKEND_REGION="us-central1"
RUNNER_SERVICE="smartetf-runner"
RUNNER_REGION="asia-south1"

case $choice in
  1)
    echo ""
    read -p "Enter your local runner URL (e.g., http://192.168.1.10:8080): " LOCAL_URL
    
    echo "🔄 Switching to local runner..."
    gcloud run services update $BACKEND_SERVICE \
      --update-env-vars="RUNNER_URL=$LOCAL_URL" \
      --region=$BACKEND_REGION
    
    echo ""
    echo "✅ Backend now points to local runner: $LOCAL_URL"
    echo ""
    echo "Make sure:"
    echo "  1. Local runner is running: python runner.py"
    echo "  2. Port 8080 is accessible"
    echo "  3. RUNNER_TOKEN matches in both .env files"
    echo ""
    echo "Optional: Stop cloud runner to save costs"
    read -p "Stop cloud runner? (y/n): " stop_cloud
    if [ "$stop_cloud" = "y" ]; then
      gcloud run services delete $RUNNER_SERVICE --region=$RUNNER_REGION --quiet
      echo "✅ Cloud runner stopped"
    fi
    ;;
    
  2)
    echo ""
    echo "🚀 Deploying runner to Cloud Run..."
    echo "   This will take 5-10 minutes..."
    
    cd smartetf-runner
    gcloud run deploy $RUNNER_SERVICE \
      --source . \
      --region=$RUNNER_REGION \
      --no-allow-unauthenticated \
      --port 8080 \
      --memory 2Gi \
      --cpu 2 \
      --timeout 900 \
      --concurrency 1
    
    RUNNER_URL=$(gcloud run services describe $RUNNER_SERVICE \
      --region=$RUNNER_REGION \
      --format='value(status.url)')
    
    echo ""
    echo "🔄 Updating backend to use cloud runner..."
    cd ..
    gcloud run services update $BACKEND_SERVICE \
      --update-env-vars="RUNNER_URL=$RUNNER_URL" \
      --region=$BACKEND_REGION
    
    echo ""
    echo "✅ Backend now points to cloud runner: $RUNNER_URL"
    echo ""
    echo "Optional: Stop local runner"
    echo "  pm2 stop smartetf-runner"
    echo "  # or just Ctrl+C if running in terminal"
    ;;
    
  3)
    echo ""
    echo "📊 Current Configuration:"
    echo ""
    echo "Backend:"
    gcloud run services describe $BACKEND_SERVICE \
      --region=$BACKEND_REGION \
      --format="table(status.url, metadata.name, metadata.annotations.RUNNER_URL)"
    
    echo ""
    echo "Runner (if deployed to cloud):"
    gcloud run services describe $RUNNER_SERVICE \
      --region=$RUNNER_REGION \
      --format="table(status.url, metadata.name, spec.template.spec.containers[0].resources.limits)" \
      2>/dev/null || echo "  Cloud runner not deployed"
    ;;
    
  *)
    echo "Invalid choice"
    exit 1
    ;;
esac

echo ""
echo "Done!"
