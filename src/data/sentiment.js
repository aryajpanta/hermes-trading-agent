import fetch from 'node-fetch';

// Simple in-memory cache for sentiment results (cached for 4 hours)
const SENTIMENT_CACHE = {};
const CACHE_TTL_MS = 4 * 60 * 60 * 1000;

/**
 * Fetch recent news headlines for a symbol using Yahoo Finance.
 * @param {string} symbol - Asset symbol (e.g. BTC, AAPL)
 * @returns {Promise<Array>} List of news items
 */
async function fetchNews(symbol) {
  // Normalize symbol (e.g. BTC/USD -> BTC)
  const query = symbol.split('/')[0].toUpperCase();
  const url = `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(query)}&newsCount=10`;
  
  try {
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    if (!res.ok) {
      console.warn(`[Sentiment] Failed to fetch news for ${query}: status ${res.status}`);
      return [];
    }
    const data = await res.json();
    return data?.news || [];
  } catch (err) {
    console.error(`[Sentiment] Error fetching news for ${query}:`, err.message);
    return [];
  }
}

/**
 * Analyze news sentiment for a symbol using the Gemini API.
 * @param {string} symbol - Asset symbol
 * @returns {Promise<Object>} { sentimentScore: -1 to 1, confidence: 0 to 1, reason: string }
 */
export async function fetchSentiment(symbol) {
  const cleanSymbol = symbol.split('/')[0].toUpperCase();
  const cacheKey = cleanSymbol;
  const now = Date.now();
  
  // Check cache
  if (SENTIMENT_CACHE[cacheKey] && (now - SENTIMENT_CACHE[cacheKey].timestamp < CACHE_TTL_MS)) {
    return SENTIMENT_CACHE[cacheKey].data;
  }

  const defaultResult = { sentimentScore: 0, confidence: 0, reason: 'Sentiment analysis unconfigured or unavailable' };

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    console.warn('[Sentiment] GEMINI_API_KEY environment variable not configured. Returning neutral sentiment.');
    return defaultResult;
  }

  // 1. Fetch news
  const newsItems = await fetchNews(cleanSymbol);
  if (newsItems.length === 0) {
    return { sentimentScore: 0, confidence: 0, reason: 'No recent news articles found for this asset' };
  }

  // Format headlines for prompt
  const headlines = newsItems.map((item, idx) => {
    const time = item.providerPublishTime ? new Date(item.providerPublishTime * 1000).toISOString().split('T')[0] : 'recent';
    return `${idx + 1}. [${time}] "${item.title}" (${item.publisher})`;
  }).join('\n');

  // 2. Call Gemini REST API
  // Using gemini-1.5-flash since it is highly reliable and cost-effective for text categorization
  const model = 'gemini-1.5-flash';
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

  const prompt = `You are a professional financial analyst AI.
Analyze the following recent news headlines for the asset symbol "${cleanSymbol}" to evaluate market sentiment.
Determine:
1. A sentiment score from -1.0 (extremely bearish) to +1.0 (extremely bullish). Neutral news or mixed sentiment should be near 0.0.
2. A confidence score from 0.0 (no confidence/insufficient news) to 1.0 (very high confidence).
3. A brief summary explanation of your reasoning.

Here are the news headlines:
${headlines}

You must return your output strictly in JSON format. Do not wrap in markdown code blocks. The JSON must follow this structure:
{
  "sentimentScore": <float between -1.0 and 1.0>,
  "confidence": <float between 0.0 and 1.0>,
  "reason": "<short sentence summarizing the news sentiment>"
}
`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{
          parts: [{ text: prompt }]
        }],
        generationConfig: {
          responseMimeType: 'application/json'
        }
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`[Sentiment] Gemini API responded with status ${response.status}:`, errorText);
      return defaultResult;
    }

    const data = await response.json();
    const textResponse = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!textResponse) {
      console.error('[Sentiment] Empty response from Gemini API');
      return defaultResult;
    }

    // Parse JSON response
    const result = JSON.parse(textResponse.trim());
    
    // Validate bounds
    const sentimentScore = Math.max(-1, Math.min(1, parseFloat(result.sentimentScore) || 0));
    const confidence = Math.max(0, Math.min(1, parseFloat(result.confidence) || 0));
    const reason = result.reason || 'Sentiment evaluated successfully';

    const finalizedResult = { sentimentScore, confidence, reason };
    
    // Cache the result
    SENTIMENT_CACHE[cacheKey] = {
      timestamp: now,
      data: finalizedResult
    };

    console.log(`[Sentiment] ${cleanSymbol}: Score = ${sentimentScore.toFixed(2)}, Conf = ${confidence.toFixed(2)} - "${reason}"`);
    return finalizedResult;
  } catch (err) {
    console.error(`[Sentiment] Failed to parse sentiment for ${cleanSymbol}:`, err.message);
    return defaultResult;
  }
}

export default { fetchSentiment };
