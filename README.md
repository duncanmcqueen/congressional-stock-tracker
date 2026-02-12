# Congressional Stock Tracker

📊 Track stock trades by US Senators and Representatives using publicly available STOCK Act disclosure data.

## What It Does

- **Fetches Trade Data** - Pulls latest congressional trades from Finnhub API
- **Stores & Analyzes** - SQLite database with politician activity tracking
- **Alerts on Activity** - WhatsApp notifications for significant trades
- **Tracks Performance** - Monitors trading patterns and volumes

## Data Source

**Financial Modeling Prep (FMP)** - Free tier: 250 API calls/day
- House trading API
- Senate trading API
- Real-time updates
- Covers Senate and House members

Get your free API key: https://site.financialmodelingprep.com/register

## Setup

### 1. Install Dependencies
```bash
pip3 install requests
```

### 2. Configure API Key
```bash
cd /home/dietpi/.openclaw/ws-stock-tracker
cp .env.example .env
# Edit .env and add your FINNHUB_API_KEY
```

### 3. Test Run
```bash
./run-tracker.sh
```

## Usage

### Manual Run
```bash
./run-tracker.sh
```

### Scheduled (Cron)
Runs automatically every 2 hours via cron job.

## Output

### Database Schema
- **trades** - Individual stock trades
- **politicians** - Aggregated activity by member

### WhatsApp Alerts Include:
- Number of new trades
- Large trades (>$50K)
- Most active traders
- Total trading volume

## Alert Thresholds

**Default Settings:**
- Track all trades > $1,000
- Alert on trades > $50,000
- Top 10 most active traders

## Files

- `scripts/stock_tracker.py` - Main tracker
- `data/trades.db` - SQLite database
- `logs/` - Execution logs
- `data/whatsapp-alert.txt` - Latest alert

## Important Notes

⚠️ **STOCK Act Disclosures:**
- 45-day reporting delay (not real-time)
- Legally required public disclosures
- Use for informational purposes only
- Not investment advice

## Privacy & Ethics

- Uses only publicly available data
- Respects API rate limits
- No personal data stored beyond public disclosures

---

*Tracking transparency in government*
