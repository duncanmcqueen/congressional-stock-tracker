#!/usr/bin/env python3
"""
Congressional Stock Tracker
Tracks stock trades by US Senators and Representatives using STOCK Act data.

Data Source: Finnhub API (free tier available)
https://finnhub.io/docs/api/congressional-trading
"""

import os
import sys
import json
import sqlite3
import logging
import requests
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
        
        conn.commit()
        conn.close()
        logger.info("Database initialized")
    
    def fetch_congressional_trades(self, from_date: str, to_date: str) -> List[Dict]:
        """
        Fetch congressional trades from FMP API
        FMP has separate endpoints for House and Senate
        
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
        
        # Fetch House trades
        try:
            house_url = f"{self.base_url}/house-trades"
            params = {
                'apikey': self.api_key,
                'from': from_date,
                'to': to_date
            }
            
            logger.info(f"Fetching House trades from {from_date} to {to_date}")
            response = requests.get(house_url, params=params, timeout=30)
            
            if response.status_code == 200:
                house_trades = response.json()
                if isinstance(house_trades, list):
                    # Tag as House
                    for trade in house_trades:
                        trade['chamber'] = 'House'
                    all_trades.extend(house_trades)
                    logger.info(f"Fetched {len(house_trades)} House trades")
            else:
                logger.warning(f"House API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching House trades: {e}")
        
        # Fetch Senate trades
        try:
            senate_url = f"{self.base_url}/senate-trades"
            params = {
                'apikey': self.api_key,
                'from': from_date,
                'to': to_date
            }
            
            logger.info(f"Fetching Senate trades from {from_date} to {to_date}")
            response = requests.get(senate_url, params=params, timeout=30)
            
            if response.status_code == 200:
                senate_trades = response.json()
                if isinstance(senate_trades, list):
                    # Tag as Senate
                    for trade in senate_trades:
                        trade['chamber'] = 'Senate'
                    all_trades.extend(senate_trades)
                    logger.info(f"Fetched {len(senate_trades)} Senate trades")
            else:
                logger.warning(f"Senate API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching Senate trades: {e}")
        
        logger.info(f"Total trades fetched: {len(all_trades)}")
        return all_trades
    
    def parse_trade(self, trade_data: Dict) -> Optional[CongressionalTrade]:
        """Parse raw API trade data into CongressionalTrade object"""
        try:
            # FMP API format
            # House: {'representative': 'Name', 'ticker': 'AAPL', 'transactionDate': '2025-01-15', 
            #         'transactionType': 'Purchase', 'amount': '$1,001 - $15,000', ...}
            # Senate: Similar format
            
            # Parse amount range
            amount_str = trade_data.get('amount', '$1,001 - $15,000')
            if not amount_str or amount_str == '':
                amount_str = '$1,001 - $15,000'
            range_low, range_high = self._parse_amount_range(amount_str)
            
            # Determine transaction type
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
            # Remove $ and commas, split on -
            clean = amount_str.replace('$', '').replace(',', '')
            if '-' in clean:
                parts = clean.split('-')
                low = float(parts[0].strip())
                high = float(parts[1].strip())
                return low, high
            else:
                # Single value
                val = float(clean)
                return val, val
        except:
            return 1000, 15000  # Default range
    
    def save_trade(self, trade: CongressionalTrade) -> bool:
        """Save trade to database, returns True if new trade"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
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
            
            is_new = cursor.rowcount > 0
            
            # Update politician stats
            if is_new:
                cursor.execute('''
                    INSERT INTO politicians (name, chamber, state, party, trade_count, total_volume)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        trade_count = trade_count + 1,
                        total_volume = total_volume + ?,
                        last_trade_date = ?
                ''', (trade.politician_name, trade.chamber, trade.state, trade.party,
                      trade.amount, trade.amount, trade.transaction_date))
            
            conn.commit()
            return is_new
            
        except Exception as e:
            logger.error(f"Error saving trade: {e}")
            return False
        finally:
            conn.close()
    
    def run_tracker(self, days_back: int = 7) -> Dict:
        """
        Main tracker run - fetch and process recent trades
        
        Args:
            days_back: Number of days to look back
            
        Returns:
            Summary dictionary
        """
        logger.info("="*60)
        logger.info("Congressional Stock Tracker - Starting Run")
        logger.info("="*60)
        
        if not self.api_key:
            logger.error("FINNHUB_API_KEY not set - cannot run tracker")
            return {'error': 'API key not configured'}
        
        # Calculate date range
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        # Fetch trades
        raw_trades = self.fetch_congressional_trades(from_date, to_date)
        
        if not raw_trades:
            logger.info("No trades found in date range")
            return {'trades_found': 0, 'new_trades': 0}
        
        # Process trades
        new_trades = []
        total_amount = 0
        
        for trade_data in raw_trades:
            trade = self.parse_trade(trade_data)
            if trade:
                if self.save_trade(trade):
                    new_trades.append(trade)
                    total_amount += trade.amount
                    logger.info(f"New trade: {trade.politician_name} - {trade.transaction_type} {trade.ticker} ${trade.amount:,.0f}")
        
        # Generate summary
        summary = {
            'trades_found': len(raw_trades),
            'new_trades': len(new_trades),
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
