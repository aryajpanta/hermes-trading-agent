# Spec: M1 — Data Foundation

## Objective
Build a reliable market data collection layer that fetches OHLCV data, volume, and basic market metrics from multiple sources.

## Requirements

### Data Sources
- **Yahoo Finance** (yfinance): Stocks, ETFs, forex, commodities
- **CoinGecko API**: Crypto prices, market cap, volume (free tier)
- **Alpha Vantage**: Additional stock/fx data (free tier: 25 req/day)

### Data Model
```python
@dataclass
class MarketData:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str  # "yahoo" | "coingecko" | "alpha_vantage"
    metadata: dict  # extra fields per source
```

### Storage
- SQLite database: `data/market.db`
- Tables: `ohlcv`, `symbols`, `data_sources`
- Auto-create schema on first run
- Upsert on conflict (symbol + timestamp + source)

### Features
- `collect(symbol, source, period)` — fetch and store data
- `collect_batch(symbols, sources, period)` — bulk fetch
- `get_latest(symbol)` — most recent data point
- `get_history(symbol, days)` — historical data as DataFrame
- `list_symbols()` — all tracked symbols
- Rate limiting per source (respect API limits)
- Retry logic with exponential backoff
- CLI entry point: `python -m src.data.collect --symbols AAPL,GOOGL --period 1y`

### Supported Assets (initial)
- Top 20 S&P 500 stocks
- BTC, ETH, SOL (crypto)
- EUR/USD, GBP/USD (forex)
- Gold, Silver (commodities via Yahoo)

## Done Criteria
- [ ] `pytest tests/test_data_collector.py` passes
- [ ] `mypy src/data/` passes
- [ ] Can fetch and store 1 year of daily data for AAPL
- [ ] Data persists in SQLite and can be queried back
- [ ] Rate limiting prevents API blocks
- [ ] CLI `python -m src.data.collect --symbols AAPL --period 1y` works

## Files Expected to Change
- src/data/__init__.py
- src/data/collector.py (main collector)
- src/data/models.py (data classes)
- src/data/storage.py (SQLite layer)
- src/data/sources/ (yahoo.py, coingecko.py, alphavantage.py)
- src/data/cli.py
- tests/test_data_collector.py
- configs/data_config.yaml
