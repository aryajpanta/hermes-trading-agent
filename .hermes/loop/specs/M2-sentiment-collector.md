# Spec: M2 — News/Sentiment Collector

## Objective
Collect financial news and social media signals, then score sentiment for market-relevant assets.

## Requirements

### Data Sources
- **RSS Feeds**: Reuters, Bloomberg, MarketWatch, CoinDesk
- **Reddit**: r/wallstreetbets, r/cryptocurrency, r/stocks (via PRAW or RSS)
- **Twitter/X**: Financial influencers, $cashtag mentions (via API or snscrape)
- **SEC filings**: EDGAR RSS for insider activity

### Sentiment Model
- **Primary**: FinBERT (ProsusAI/finbert) — financial sentiment
- **Fallback**: VADER sentiment (lightweight, no GPU needed)
- **Scoring**: -1.0 (bearish) to +1.0 (bullish), with confidence score

### Data Model
```python
@dataclass
class SentimentSignal:
    source: str  # "news" | "reddit" | "twitter" | "sec"
    symbol: str  # ticker or "MARKET" for general
    timestamp: datetime
    headline: str
    body: str
    sentiment_score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    url: str
    author: str
    engagement: int  # upvotes, retweets, etc.
```

### Features
- `collect_news(symbols)` — fetch recent news for symbols
- `collect_social(symbols)` — fetch Reddit/Twitter signals
- `score_sentiment(text)` — analyze text sentiment
- `get_sentiment_history(symbol, hours)` — recent sentiment as DataFrame
- `get_aggregate_sentiment(symbol)` — weighted average across sources
- Deduplication (same story from multiple sources)
- Engagement-weighted scoring (viral = more weight)
- CLI: `python -m src.data.sentiment --symbols AAPL,BTC --hours 24`

## Done Criteria
- [ ] `pytest tests/test_sentiment.py` passes
- [ ] `mypy src/data/sentiment*` passes
- [ ] Can fetch and score sentiment for AAPL from 3+ sources
- [ ] FinBERT produces reasonable scores on test headlines
- [ ] Deduplication works (same news from Reuters + MarketWatch = 1 entry)
- [ ] CLI `python -m src.data.sentiment --symbols AAPL --hours 24` works

## Files Expected to Change
- src/data/sentiment/__init__.py
- src/data/sentiment/collector.py
- src/data/sentiment/scorer.py
- src/data/sentiment/sources/ (rss.py, reddit.py, twitter.py)
- src/data/sentiment/models.py
- tests/test_sentiment.py
- configs/sentiment_config.yaml
