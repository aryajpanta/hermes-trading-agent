/**
 * Trading Intelligence Dashboard — Shared JavaScript utilities
 */

// Auto-refresh configuration
const AUTO_REFRESH_MS = 60000; // 60 seconds

/**
 * Format a number as USD currency.
 */
function formatUSD(value) {
    if (value == null) return '—';
    return '$' + Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

/**
 * Format a large number with K/M/B suffixes.
 */
function formatCompact(value) {
    if (value == null) return '—';
    const n = Number(value);
    if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toLocaleString();
}

/**
 * Format an ISO timestamp to a locale string.
 */
function formatTimestamp(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
}

/**
 * Generic fetch wrapper with error handling.
 */
async function apiFetch(url, options) {
    try {
        const res = await fetch(url, options);
        if (!res.ok) {
            console.error(`API error: ${res.status} ${res.statusText}`);
            return null;
        }
        return await res.json();
    } catch (e) {
        console.error(`Fetch error for ${url}:`, e);
        return null;
    }
}

// Log that shared JS loaded
console.log('Trading Intelligence Dashboard — shared JS loaded');
