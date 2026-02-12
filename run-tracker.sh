#!/bin/bash
#
# Congressional Stock Tracker - Run Script
# Usage: ./run-tracker.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables
if [ -f .env ]; then
    source .env
fi

# Create directories
mkdir -p logs data

LOG_FILE="logs/tracker-$(date +%Y%m%d-%H%M%S).log"

echo "📊 Congressional Stock Tracker"
echo "==============================="
echo "Start: $(date)"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found"
    exit 1
fi

# Check if Finnhub API key is configured
if [ -z "$FINNHUB_API_KEY" ]; then
    echo "⚠️  WARNING: FINNHUB_API_KEY not configured!"
    echo "Get your free API key at: https://finnhub.io/register"
    echo "Then add it to .env file"
    echo ""
    echo "Continuing with demo mode (limited functionality)..."
    echo ""
fi

echo "Running tracker..."
echo ""

# Run the tracker
python3 scripts/stock_tracker.py 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "Finish: $(date)"
echo "Log saved to: $LOG_FILE"

# Check for WhatsApp alert
if [ -f "data/whatsapp-alert.txt" ]; then
    echo ""
    echo "📱 WhatsApp alert generated!"
fi

exit $EXIT_CODE
