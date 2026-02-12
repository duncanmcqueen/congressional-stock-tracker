# AGENTS.md - Congressional Stock Tracker

## Purpose
Track stock trades by US Senators and Representatives using publicly available STOCK Act disclosure data.

The STOCK Act (Stop Trading on Congressional Knowledge Act) of 2012 requires members of Congress to disclose stock trades over $1,000 within 45 days.

## What It Does

1. **Fetches Trade Data** - Pulls latest congressional trades from APIs
2. **Analyzes Patterns** - Identifies frequent traders, big movers, trends
3. **Alerts on Activity** - Sends WhatsApp notifications for:
   - New trades by tracked politicians
   - Unusual trading activity
   - Sector concentration changes
4. **Tracks Performance** - Monitors how congressional trades perform

## Data Sources

### Primary: Financial Modeling Prep (FMP) API
- Free tier: 250 calls/day
- House Trading API
- Senate Trading API
- Real-time congressional trade data
- https://site.financialmodelingprep.com/developer/docs

### Secondary: Quiver Quantitative
- Alternative data source
- Historical congressional trading database

### Tertiary: House/Senate Clerk Websites
- Official disclosure PDFs
- Parsed and aggregated by third parties

## Configuration

### Required Environment Variables
```bash
# Finnhub API Key (free at finnhub.io)
FINNHUB_API_KEY="your-api-key"

# WhatsApp Notifications
WHATSAPP_RECIPIENT="+18162672202"

# Alert Thresholds
MIN_TRADE_AMOUNT=1000        # Minimum $ to alert on
TOP_POLITICIAN_COUNT=10      # Track top N active traders
ALERT_ON_SECTOR_CHANGES=true # Alert on sector concentration shifts
```

## Output

### WhatsApp Alerts Include:
- Politician name and chamber
- Stock ticker and company
- Buy/sell action
- Dollar amount
- Date of trade
- Link to official disclosure

### Daily Summary Report:
- Total trades today
- Most active politicians
- Biggest dollar moves
- Sector trends
- Notable patterns

## Automation

### Schedule
- **Frequency:** Every 2 hours (8 AM - 8 PM EST)
- **Daily Summary:** 6 PM EST

### Manual Run
```bash
cd /home/dietpi/.openclaw/ws-stock-tracker
./run-tracker.sh
```

## Ethics & Compliance

⚠️ **Important Notes:**
- Data is public and legally required to be disclosed
- 45-day reporting delay means trades are not real-time
- Use for informational purposes only
- Not investment advice

## Files

- `scripts/stock_tracker.py` - Main tracker logic
- `data/trades.db` - SQLite database of trades
- `data/politicians.json` - Tracked politicians
- `logs/` - Execution logs

---
*Tracking transparency in government*
