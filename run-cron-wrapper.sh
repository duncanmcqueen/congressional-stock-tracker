#!/bin/bash
#
# Congressional Stock Tracker - Cron Wrapper
# Runs the tracker and sends WhatsApp alerts
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment
source .env 2>/dev/null || true

LOG_FILE="logs/cron-$(date +%Y%m%d-%H%M%S).log"
mkdir -p logs data

echo "📊 Congressional Stock Tracker - Cron Run" > "$LOG_FILE"
echo "==========================================" >> "$LOG_FILE"
echo "Start: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Check if Finnhub API key is configured
if [ -z "$FINNHUB_API_KEY" ]; then
    echo "⚠️  FINNHUB_API_KEY not configured" >> "$LOG_FILE"
    echo "Get free API key at: https://finnhub.io/register" >> "$LOG_FILE"
fi

# Run tracker with timeout (10 minutes max)
timeout 600 ./run-tracker.sh 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=$?
END_TIME=$(date)

echo "" >> "$LOG_FILE"
echo "Finish: $END_TIME" >> "$LOG_FILE"

if [ $EXIT_CODE -eq 124 ]; then
    echo "⚠️  TIMEOUT: Tracker took too long" >> "$LOG_FILE"
    EXIT_CODE=1
fi

# Create WhatsApp summary
SUMMARY_FILE="logs/whatsapp-summary.txt"
echo "📊 Congressional Stock Tracker Report" > "$SUMMARY_FILE"
echo "--------------------------------------" >> "$SUMMARY_FILE"
echo "Time: $(date +'%Y-%m-%d %H:%M')" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    # Extract summary from log
    TRADES=$(grep "New trades:" "$LOG_FILE" | tail -1 | awk '{print $3}')
    VALUE=$(grep "Total value:" "$LOG_FILE" | tail -1 | awk '{print $3}')
    
    echo "✅ Tracker completed successfully" >> "$SUMMARY_FILE"
    echo "" >> "$SUMMARY_FILE"
    if [ -n "$TRADES" ]; then
        echo "🆕 New trades: $TRADES" >> "$SUMMARY_FILE"
        echo "💰 Total value: $VALUE" >> "$SUMMARY_FILE"
    fi
    
    # Include alert content if exists
    if [ -f "data/whatsapp-alert.txt" ]; then
        echo "" >> "$SUMMARY_FILE"
        cat "data/whatsapp-alert.txt" >> "$SUMMARY_FILE"
    fi
else
    echo "❌ Tracker encountered issues" >> "$SUMMARY_FILE"
    echo "Check log: $LOG_FILE" >> "$SUMMARY_FILE"
fi

# Display summary
cat "$SUMMARY_FILE"

exit $EXIT_CODE
