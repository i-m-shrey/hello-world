#!/bin/bash
# Keep Cloud Run instance warm during business hours
# Run this locally or on a cron job

BACKEND_URL="https://your-backend-url.run.app"
HEALTH_ENDPOINT="/health"

echo "🔥 Warming up SmartETF Backend..."
echo "Target: $BACKEND_URL$HEALTH_ENDPOINT"
echo ""

while true; do
    current_hour=$(date +%H)
    current_day=$(date +%u)  # 1=Monday, 7=Sunday
    
    # Only ping during business hours (9 AM - 6 PM IST, Mon-Fri)
    if [ $current_day -le 5 ] && [ $current_hour -ge 9 ] && [ $current_hour -le 18 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pinging..."
        response=$(curl -s -o /dev/null -w "%{http_code} - %{time_total}s" $BACKEND_URL$HEALTH_ENDPOINT)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Response: $response"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Outside business hours, skipping..."
    fi
    
    # Wait 5 minutes
    sleep 300
done
