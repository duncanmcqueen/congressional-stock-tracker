#!/usr/bin/env python3
"""
Congressional Stock Tracker
Tracks stock trades by US Senators and Representatives using STOCK Act data.

Data Source: Financial Modeling Prep (FMP) API
https://site.financialmodelingprep.com/developer/docs
"""

import os
import sys
import json
import sqlite3
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

# Setup paths
SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"
LOGS_DIR = SCRIPT_DIR / "logs"

# Load environment variables from .env file
env_path = SCRIPT_DIR / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                # Remove inline comments
                if '#' in value:
                    value = value.split('#')[0].strip()
                # Remove quotes if present
                value = value.strip('"').strip("'")
                os.environ.setdefault(key, value)

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Configuration
# FMP API Key (free tier: 250 calls/day) - https://site.financialmodelingprep.com/register
FMP_API_KEY = os.environ.get('FMP_API_KEY', os.environ.get('FINNHUB_API_KEY', ''))
WHATSAPP_RECIPIENT = os.environ.get('WHATSAPP_RECIPIENT', '+18162672202')
MIN_TRADE_AMOUNT = int(os.environ.get('MIN_TRADE_AMOUNT', '1000'))
ALERT_THRESHOLD = int(os.environ.get('ALERT_THRESHOLD', '50000'))  # $50K+ for alerts

# Setup logging
LOG_FILE = LOGS_DIR / f"tracker-{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class CongressionalTrade:
    """Represents a single congressional stock trade"""
    politician_name: str
    chamber: str  # 'Senate' or 'House'
    state: str
    party: str
    transaction_date: str
    disclosure_date: str
    ticker: str
    asset_name: str
    transaction_type: str  # 'Purchase' or 'Sale'
    amount: float
    range_low: float
    range_high: float
    raw_data: Dict


class CongressionalStockTracker:
    """Main tracker class for congressional stock trades"""

    def __init__(self):
        self.api_key = FMP_API_KEY
        self.base_url = "https://financialmodelingprep.com/api/v3"
        self.db_path = DATA_DIR / "trades.db"
        # Persistent HTTP session for connection reuse across requests
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'CongressionalStockTracker/1.0'})
        self.init_database()

        if not self.api_key:
            logger.error("FMP_API_KEY not configured!")
            logger.error("Get your free API key at https://site.financialmodelingprep.com/register")

    def init_database(self):
        """Initialize SQLite database for storing trades"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                politician_name TEXT NOT NULL,
                chamber TEXT,
                state TEXT,
                party TEXT,
                transaction_date DATE,
                disclosure_date DATE,
                ticker TEXT,
                asset_name TEXT,
                transaction_type TEXT,
                amount REAL,
                range_low REAL,
                range_high REAL,
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(politician_name, transaction_date, ticker, transaction_type, amount)
            )
        ''')

        # Politicians table for tracking activity
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS politicians (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                chamber TEXT,
                state TEXT,
                party TEXT,
                trade_count INTEGER DEFAULT 0,
                last_trade_date DATE,
                total_volume REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Indexes for faster queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(transaction_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_amount ON trades(amount)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_politician ON trades(politician_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_disclosure ON trades(disclosure_date)')

        conn.commit()
        conn.close()
        logger.info("Database initialized")

    def _fetch_chamber_trades(self, chamber: str, from_date: str, to_date: str) -> List[Dict]:
        """
        Fetch trades for a single chamber (House or Senate).
        Called concurrently from fetch_congressional_trades.
        """
        endpoint = 'house-trades' if chamber == 'House' else 'senate-trades'
        url = f"{self.base_url}/{endpoint}"
        params = {'apikey': self.api_key, 'from': from_date, 'to': to_date}

        logger.info(f"Fetching {chamber} trades from {from_date} to {to_date}")
        response = self.session.get(url, params=params, timeout=30)

        if response.status_code != 200:
            logger.warning(f"{chamber} API error: {response.status_code}")
            return []

        trades = response.json()
        if not isinstance(trades, list):
            return []

        for trade in trades:
            trade['chamber'] = chamber

        logger.info(f"Fetched {len(trades)} {chamber} trades")
        return trades

    def fetch_congressional_trades(self, from_date: str, to_date: str) -> List[Dict]:
        """
        Fetch congressional trades from FMP API.
        House and Senate endpoints are fetched in parallel to cut wait time in half.

        Args:
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            List of trade dictionaries
        """
        if not self.api_key:
            logger.error("Cannot fetch trades - API key not configured")
            return []

        all_trades = []

        # Fetch House and Senate concurrently
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._fetch_chamber_trades, 'House', from_date, to_date): 'House',
                executor.submit(self._fetch_chamber_trades, 'Senate', from_date, to_date): 'Senate',
            }
            for future in as_completed(futures):
                chamber = futures[future]
                try:
                    trades = future.result()
                    all_trades.extend(trades)
                except Exception as e:
                    logger.error(f"Error fetching {chamber} trades: {e}")

        logger.info(f"Total trades fetched: {len(all_trades)}")
        return all_trades

    def get_last_seen_date(self) -> Optional[str]:
        """
        Return the most recent disclosure_date already in the database.
        Used for delta fetching to avoid re-processing known trades.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(disclosure_date) FROM trades')
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else None

    def parse_trade(self, trade_data: Dict) -> Optional[CongressionalTrade]:
        """Parse raw API trade data into CongressionalTrade object"""
        try:
            amount_str = trade_data.get('amount', '$1,001 - $15,000')
            if not amount_str or amount_str == '':
                amount_str = '$1,001 - $15,000'
            range_low, range_high = self._parse_amount_range(amount_str)

            trans_type = trade_data.get('transactionType', trade_data.get('type', 'Unknown'))

            return CongressionalTrade(
                politician_name=trade_data.get('representative', trade_data.get('senator', 'Unknown')),
                chamber=trade_data.get('chamber', 'Unknown'),
                state=trade_data.get('state', 'Unknown'),
                party=trade_data.get('party', 'Unknown'),
                transaction_date=trade_data.get('transactionDate', ''),
                disclosure_date=trade_data.get('disclosureDate', trade_data.get('filingDate', '')),
                ticker=trade_data.get('ticker', ''),
                asset_name=trade_data.get('assetName', trade_data.get('asset', '')),
                transaction_type=trans_type,
                amount=(range_low + range_high) / 2,  # Use midpoint
                range_low=range_low,
                range_high=range_high,
                raw_data=trade_data
            )
        except Exception as e:
            logger.error(f"Error parsing trade: {e}")
            logger.debug(f"Trade data: {trade_data}")
            return None

    def _parse_amount_range(self, amount_str: str) -> Tuple[float, float]:
        """Parse amount string like '$1,001 - $15,000' into (low, high)"""
        try:
            clean = amount_str.replace('$', '').replace(',', '')
            if '-' in clean:
                parts = clean.split('-')
                low = float(parts[0].strip())
                high = float(parts[1].strip())
                return low, high
            else:
                val = float(clean)
                return val, val
        except Exception:
            return 1000, 15000  # Default range

    def save_trades_batch(self, trades: List[CongressionalTrade]) -> int:
        """
        Save a batch of trades in a single transaction.
        Returns the number of newly inserted trades.
        """
        if not trades:
            return 0

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        new_count = 0

        try:
            for trade in trades:
                cursor.execute('''
                    INSERT OR IGNORE INTO trades
                    (politician_name, chamber, state, party, transaction_date, disclosure_date,
                     ticker, asset_name, transaction_type, amount, range_low, range_high, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    trade.politician_name, trade.chamber, trade.state, trade.party,
                    trade.transaction_date, trade.disclosure_date, trade.ticker,
                    trade.asset_name, trade.transaction_type, trade.amount,
                    trade.range_low, trade.range_high, json.dumps(trade.raw_data)
                ))
                if cursor.rowcount > 0:
                    new_count += 1

            # Batch-update politician aggregates in a single query per politician
            if new_count > 0:
                new_trades = [t for t in trades]
                # Build per-politician aggregates from this batch
                politician_stats: Dict[str, Dict] = {}
                for trade in new_trades:
                    key = trade.politician_name
                    if key not in politician_stats:
                        politician_stats[key] = {
                            'chamber': trade.chamber,
                            'state': trade.state,
                            'party': trade.party,
                            'count': 0,
                            'volume': 0.0,
                            'last_date': trade.transaction_date,
                        }
                    s = politician_stats[key]
                    s['count'] += 1
                    s['volume'] += trade.amount
                    if trade.transaction_date > s['last_date']:
                        s['last_date'] = trade.transaction_date

                for name, s in politician_stats.items():
                    cursor.execute('''
                        INSERT INTO politicians (name, chamber, state, party, trade_count, total_volume, last_trade_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(name) DO UPDATE SET
                            trade_count = trade_count + ?,
                            total_volume = total_volume + ?,
                            last_trade_date = MAX(last_trade_date, ?)
                    ''', (name, s['chamber'], s['state'], s['party'],
                          s['count'], s['volume'], s['last_date'],
                          s['count'], s['volume'], s['last_date']))

            conn.commit()
        except Exception as e:
            logger.error(f"Error saving trades batch: {e}")
            conn.rollback()
        finally:
            conn.close()

        return new_count

    # Keep single-trade save for backwards compatibility
    def save_trade(self, trade: CongressionalTrade) -> bool:
        """Save a single trade. Returns True if it was new."""
        return self.save_trades_batch([trade]) > 0

    def run_tracker(self, days_back: int = 7) -> Dict:
        """
        Main tracker run - fetch and process recent trades.

        Uses delta fetching: if the database already has trades, only fetches
        from the day after the most recently seen disclosure date, limiting
        unnecessary API calls and processing.

        Args:
            days_back: Number of days to look back (used when DB is empty)

        Returns:
            Summary dictionary
        """
        logger.info("="*60)
        logger.info("Congressional Stock Tracker - Starting Run")
        logger.info("="*60)

        if not self.api_key:
            logger.error("FMP_API_KEY not set - cannot run tracker")
            return {'error': 'API key not configured'}

        # Smart delta fetching: start from day after last seen disclosure
        to_date = datetime.now().strftime('%Y-%m-%d')
        last_seen = self.get_last_seen_date()
        if last_seen:
            # Start the day after the last known disclosure to avoid redundant work
            last_dt = datetime.strptime(last_seen, '%Y-%m-%d')
            from_date = (last_dt + timedelta(days=1)).strftime('%Y-%m-%d')
            logger.info(f"Delta fetch: last seen disclosure={last_seen}, fetching from {from_date}")
        else:
            from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
            logger.info(f"Full fetch: no prior data, looking back {days_back} days")

        # Skip fetch if we're already up to date
        if from_date > to_date:
            logger.info("Already up to date - no new dates to fetch")
            return {'trades_found': 0, 'new_trades': 0, 'total_value': 0,
                    'date_range': f"{from_date} to {to_date}",
                    'timestamp': datetime.now().isoformat()}

        # Fetch trades (parallel House + Senate)
        raw_trades = self.fetch_congressional_trades(from_date, to_date)

        if not raw_trades:
            logger.info("No trades found in date range")
            return {'trades_found': 0, 'new_trades': 0}

        # Parse all trades first, then batch-save in one transaction
        parsed_trades = []
        for trade_data in raw_trades:
            trade = self.parse_trade(trade_data)
            if trade:
                parsed_trades.append(trade)

        new_count = self.save_trades_batch(parsed_trades)
        new_trades = parsed_trades[:new_count]  # approximate for logging
        total_amount = sum(t.amount for t in parsed_trades)

        for trade in parsed_trades:
            logger.info(
                f"Trade: {trade.politician_name} - {trade.transaction_type} "
                f"{trade.ticker} ${trade.amount:,.0f}"
            )

        summary = {
            'trades_found': len(raw_trades),
            'new_trades': new_count,
            'total_value': total_amount,
            'date_range': f"{from_date} to {to_date}",
            'timestamp': datetime.now().isoformat()
        }

        logger.info(f"\nRun complete:")
        logger.info(f"  Total trades found: {summary['trades_found']}")
        logger.info(f"  New trades saved: {summary['new_trades']}")
        logger.info(f"  Total value: ${summary['total_value']:,.2f}")

        return summary

    def get_top_traders(self, limit: int = 10) -> List[Dict]:
        """Get most active congressional traders"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT name, chamber, party, trade_count, total_volume, last_trade_date
            FROM politicians
            ORDER BY trade_count DESC
            LIMIT ?
        ''', (limit,))

        results = []
        for row in cursor.fetchall():
            results.append({
                'name': row[0],
                'chamber': row[1],
                'party': row[2],
                'trade_count': row[3],
                'total_volume': row[4],
                'last_trade': row[5]
            })

        conn.close()
        return results

    def get_recent_large_trades(self, min_amount: float = 50000, limit: int = 20) -> List[Dict]:
        """Get recent large trades above threshold"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT politician_name, chamber, ticker, asset_name, transaction_type,
                   amount, transaction_date
            FROM trades
            WHERE amount >= ?
            ORDER BY transaction_date DESC
            LIMIT ?
        ''', (min_amount, limit))

        results = []
        for row in cursor.fetchall():
            results.append({
                'politician': row[0],
                'chamber': row[1],
                'ticker': row[2],
                'asset': row[3],
                'type': row[4],
                'amount': row[5],
                'date': row[6]
            })

        conn.close()
        return results

    def generate_whatsapp_alert(self, summary: Dict) -> str:
        """Generate WhatsApp alert message"""
        message = f"📊 Congressional Stock Tracker\n"
        message += f"Daily Report - {datetime.now().strftime('%Y-%m-%d')}\n"
        message += "=" * 40 + "\n\n"

        if summary.get('error'):
            message += f"❌ Error: {summary['error']}\n"
            return message

        message += f"✅ Trades found: {summary.get('trades_found', 0)}\n"
        message += f"🆕 New trades: {summary.get('new_trades', 0)}\n"
        if 'total_value' in summary:
            message += f"💰 Total value: ${summary['total_value']:,.0f}\n\n"
        else:
            message += "\n"

        # Get recent large trades
        large_trades = self.get_recent_large_trades(min_amount=ALERT_THRESHOLD, limit=5)
        if large_trades:
            message += "💵 Recent Large Trades:\n"
            for trade in large_trades[:3]:
                message += f"  • {trade['politician']}\n"
                message += f"    {trade['type']} {trade['ticker']} (${trade['amount']:,.0f})\n\n"

        # Get top traders
        top_traders = self.get_top_traders(limit=5)
        if top_traders:
            message += "🏆 Most Active Traders:\n"
            for trader in top_traders[:3]:
                message += f"  {trader['name']} ({trader['chamber']}): {trader['trade_count']} trades\n"

        return message


def main():
    """CLI entry point"""
    print("\n" + "="*60)
    print("📊 Congressional Stock Tracker")
    print("Tracking STOCK Act disclosures")
    print("="*60 + "\n")

    # Check for API key
    if not FMP_API_KEY:
        print("❌ FMP_API_KEY not configured!")
        print("Get your free API key at: https://site.financialmodelingprep.com/register")
        print("Then add it to your .env file\n")
        sys.exit(1)

    # Run tracker
    tracker = CongressionalStockTracker()
    summary = tracker.run_tracker(days_back=7)

    # Generate WhatsApp alert
    alert_message = tracker.generate_whatsapp_alert(summary)

    # Save alert to file for WhatsApp
    alert_file = DATA_DIR / "whatsapp-alert.txt"
    with open(alert_file, 'w') as f:
        f.write(alert_message)

    print("\n" + "="*60)
    print("Alert saved to:", alert_file)
    print("="*60 + "\n")

    # Print alert
    print(alert_message)

    return summary


if __name__ == "__main__":
    main()
