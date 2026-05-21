"""
Live Data Engine
================
Fetches real financial metrics for 7 asset class ETF proxies directly from
Yahoo Finance (public API, no key required) and FRED (CPI for inflation beta).

Data fetched:
  - 5 years of monthly adjusted-close prices (Yahoo Finance v8 API)
  - Current risk-free rate (3-month T-Bill via BIL ETF yield)
  - Monthly CPI (FRED CPIAUCSL, no key required)

Computed metrics (all annualised where applicable):
  - Expected return %          (geometric mean of monthly returns × 12)
  - Beta                       (vs SPY benchmark, OLS)
  - Volatility %               (std of monthly returns × √12)
  - Max drawdown %             (peak-to-trough over full window)
  - Sharpe ratio               (annualised excess return / annualised vol)
  - Average pairwise correlation (cross-asset, from full 7×7 matrix)
  - Inflation beta             (OLS regression: asset returns ~ CPI_change)
  - Dividend yield %           (trailing 12-month dividends / current price)
  - Liquidity score            (log-scaled average daily dollar volume, 1–10)

Caching:
  Results are cached to _live_data_cache.json for CACHE_TTL_HOURS (24h).
  If Yahoo Finance is unreachable, the engine falls back to the cached values,
  and if no cache exists, to the hardcoded research estimates in evidence_engine.py.

ETF Proxies (liquid, widely-used benchmarks):
  Small Stocks    → IWM   iShares Russell 2000 ETF
  Large Stocks    → SPY   SPDR S&P 500 ETF Trust
  Corporate Bonds → LQD   iShares iBoxx $ IG Corp Bond ETF
  Government Bonds→ IEF   iShares 7-10 Year Treasury Bond ETF
  Real Estate     → VNQ   Vanguard Real Estate ETF
  Money Market    → BIL   SPDR Bloomberg 1-3 Month T-Bill ETF
  Commodities     → GSG   iShares S&P GSCI Commodity-Indexed Trust
"""

import json
import math
import os
import ssl
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

ASSET_PROXIES: Dict[str, Dict] = {
    "Small Stocks":    {"ticker": "IWM",  "full_name": "iShares Russell 2000 ETF",            "source": "Yahoo Finance"},
    "Large Stocks":    {"ticker": "SPY",  "full_name": "SPDR S&P 500 ETF Trust",               "source": "Yahoo Finance"},
    "Corporate Bonds": {"ticker": "LQD",  "full_name": "iShares iBoxx $ IG Corp Bond ETF",     "source": "Yahoo Finance"},
    "Government Bonds":{"ticker": "IEF",  "full_name": "iShares 7-10 Year Treasury Bond ETF",  "source": "Yahoo Finance"},
    "Real Estate":     {"ticker": "VNQ",  "full_name": "Vanguard Real Estate ETF",              "source": "Yahoo Finance"},
    "Money Market":    {"ticker": "BIL",  "full_name": "SPDR Bloomberg 1-3 Month T-Bill ETF",  "source": "Yahoo Finance"},
    "Commodities":     {"ticker": "GSG",  "full_name": "iShares S&P GSCI Commodity-Indexed",   "source": "Yahoo Finance"},
}

BENCHMARK_TICKER = "SPY"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_live_data_cache.json")
CACHE_TTL_HOURS = 24
FETCH_RANGE   = "5y"    # 5-year window
FETCH_INTERVAL = "1mo"  # monthly bars

# Liquidity scores (1–10) based on AUM and avg daily volume — updated annually
# These don't change meaningfully day-to-day so we keep them research-based
LIQUIDITY_SCORES = {
    "Small Stocks":    6.0,   # IWM ~$60B AUM, decent spread
    "Large Stocks":    9.5,   # SPY ~$550B AUM, tightest spread in the world
    "Corporate Bonds": 7.0,   # LQD ~$30B AUM, bond market liquidity
    "Government Bonds":9.5,   # IEF ~$30B AUM, Treasuries extremely liquid
    "Real Estate":     4.0,   # VNQ ~$35B AUM, but underlying RE illiquid
    "Money Market":    10.0,  # BIL effectively cash equivalent
    "Commodities":     6.5,   # GSG ~$1.5B AUM, futures-based
}

# Duration (interest-rate sensitivity) — structural, not price-derived
DURATION_YEARS = {
    "Small Stocks":    0.0,
    "Large Stocks":    0.0,
    "Corporate Bonds": 8.5,   # LQD effective duration ~8.5 yr
    "Government Bonds":7.5,   # IEF 7-10yr average ~7.5 yr
    "Real Estate":     0.0,
    "Money Market":    0.1,   # BIL ~0.1 yr duration
    "Commodities":     0.0,
}

# ─────────────────────────────────────────────────────────────
# SSL / HTTP HELPERS
# ─────────────────────────────────────────────────────────────

import http.cookiejar as cookiejar

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Session-level crumb cache
_SESSION_CRUMB: Optional[str] = None
_SESSION_COOKIE: Optional[str] = None


def _get_yahoo_crumb() -> Tuple[str, str]:
    """Obtain Yahoo Finance session cookie + crumb (needed since 2024)."""
    global _SESSION_CRUMB, _SESSION_COOKIE

    if _SESSION_CRUMB and _SESSION_COOKIE:
        return _SESSION_CRUMB, _SESSION_COOKIE

    # Step 1: hit consent/home page to get a session cookie
    consent_url = "https://finance.yahoo.com/"
    req = urllib.request.Request(consent_url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    cookie = ""
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as resp:
        raw = resp.headers.get("Set-Cookie", "")
        # Extract A1/A3 cookie tokens Yahoo uses
        for part in raw.split(","):
            part = part.strip()
            if part.startswith("A1=") or part.startswith("A3=") or part.startswith("GUC="):
                cookie = part.split(";")[0]
                break
        if not cookie:
            # Fallback: grab first name=value segment
            first = raw.split(";")[0].strip()
            if "=" in first:
                cookie = first

    # Step 2: get crumb
    crumb_url = "https://query1.finance.yahoo.com/v1/test/getcrumb"
    crumb_req = urllib.request.Request(crumb_url, headers={
        "User-Agent": _UA,
        "Accept": "*/*",
        "Cookie": cookie,
    })
    with urllib.request.urlopen(crumb_req, timeout=15, context=_SSL) as resp:
        crumb = resp.read().decode("utf-8").strip()

    _SESSION_CRUMB  = crumb
    _SESSION_COOKIE = cookie
    return crumb, cookie


def _get(url: str, timeout: int = 30) -> dict:
    """HTTP GET with Yahoo crumb auth."""
    try:
        crumb, cookie = _get_yahoo_crumb()
        sep = "&" if "?" in url else "?"
        full_url = url + sep + f"crumb={urllib.parse.quote(crumb)}"
        req = urllib.request.Request(full_url, headers={
            "User-Agent": _UA,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Cookie": cookie,
            "Referer": "https://finance.yahoo.com/",
        })
    except Exception:
        # If crumb fails, try without it (may work for some endpoints)
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "application/json",
        })
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ─────────────────────────────────────────────────────────────
# YAHOO FINANCE FETCH
# ─────────────────────────────────────────────────────────────

def _fetch_yahoo(ticker: str, range_: str = FETCH_RANGE,
                 interval: str = FETCH_INTERVAL) -> Tuple[List[int], List[float], dict]:
    """
    Fetch monthly adjusted-close prices.
    Primary: yfinance library (handles crumb auth automatically).
    Fallback: raw urllib with crumb (for environments without yfinance).
    Returns (timestamps_unix_list, adj_close_list, dividends_raw_dict).
    """
    # ── Primary: yfinance ──────────────────────────────────────
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=range_, interval=interval, auto_adjust=True)
        if hist.empty:
            raise ValueError("Empty DataFrame returned")

        # Build parallel lists
        ts_list  = [int(idx.timestamp()) for idx in hist.index]
        prc_list = [float(v) for v in hist["Close"].tolist()]

        # Dividends: {unix_ts_str: {amount: val}} format to match old code
        divs_raw: dict = {}
        if "Dividends" in hist.columns:
            for idx, row in hist.iterrows():
                d = float(row.get("Dividends", 0))
                if d > 0:
                    divs_raw[str(int(idx.timestamp()))] = {"amount": d}

        return ts_list, prc_list, divs_raw

    except ImportError:
        pass   # yfinance not available — fall through to urllib

    # ── Fallback: urllib with crumb ────────────────────────────
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval={interval}&range={range_}&events=div"
    )
    data = _get(url)
    result = data["chart"]["result"][0]
    timestamps   = result["timestamp"]
    adj          = result["indicators"]["adjclose"][0]["adjclose"]
    dividends_raw = result.get("events", {}).get("dividends", {})
    pairs = [(t, p) for t, p in zip(timestamps, adj) if p is not None]
    return [p[0] for p in pairs], [p[1] for p in pairs], dividends_raw


def _fetch_daily_volume(ticker: str) -> float:
    """Fetch average daily dollar volume (3-month window) for liquidity proxy."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=True)
        if not hist.empty and "Volume" in hist.columns and "Close" in hist.columns:
            dv = [float(v) * float(c)
                  for v, c in zip(hist["Volume"], hist["Close"])
                  if v and c and v > 0]
            return sum(dv) / len(dv) if dv else 0.0
    except Exception:
        pass

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range=3mo"
    )
    try:
        data = _get(url)
        result = data["chart"]["result"][0]
        volumes = result["indicators"]["quote"][0].get("volume", [])
        closes  = result["indicators"]["quote"][0].get("close", [])
        dollar_vols = [v * c for v, c in zip(volumes, closes)
                       if v is not None and c is not None and v > 0]
        return sum(dollar_vols) / len(dollar_vols) if dollar_vols else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────
# FRED CPI FETCH (for inflation beta)
# ─────────────────────────────────────────────────────────────

def _fetch_cpi_monthly() -> Dict[str, float]:
    """
    Fetch monthly CPI (CPIAUCSL) from FRED public CSV.
    Returns {YYYY-MM: pct_change_vs_prior_month}.
    No API key required for the CSV endpoint.
    """
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL) as resp:
            raw = resp.read().decode("utf-8").strip().split("\n")
        # Parse CSV: DATE,VALUE
        vals = {}
        for line in raw[1:]:  # skip header
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    vals[parts[0][:7]] = float(parts[1])  # YYYY-MM
                except ValueError:
                    pass
        # Compute month-over-month % change
        dates = sorted(vals.keys())
        changes = {}
        for i in range(1, len(dates)):
            prev = vals[dates[i-1]]
            curr = vals[dates[i]]
            if prev > 0:
                changes[dates[i]] = (curr - prev) / prev
        return changes
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────
# METRIC COMPUTATION
# ─────────────────────────────────────────────────────────────

def _returns_from_prices(prices: List[float]) -> List[float]:
    """Simple monthly returns from price series."""
    rets = []
    for i in range(1, len(prices)):
        if prices[i] and prices[i-1] and prices[i-1] != 0:
            rets.append((prices[i] - prices[i-1]) / prices[i-1])
    return rets


def _annualised_return(monthly_returns: List[float]) -> float:
    """Geometric mean annualised return."""
    if not monthly_returns:
        return 0.0
    compound = 1.0
    for r in monthly_returns:
        compound *= (1.0 + r)
    n = len(monthly_returns)
    geo_mean_monthly = compound ** (1.0 / n) - 1.0
    return ((1.0 + geo_mean_monthly) ** 12 - 1.0) * 100.0


def _annualised_vol(monthly_returns: List[float]) -> float:
    if len(monthly_returns) < 2:
        return 0.0
    n = len(monthly_returns)
    mean = sum(monthly_returns) / n
    var = sum((r - mean) ** 2 for r in monthly_returns) / (n - 1)
    return math.sqrt(var) * math.sqrt(12) * 100.0


def _beta(asset_rets: List[float], bench_rets: List[float]) -> float:
    n = min(len(asset_rets), len(bench_rets))
    if n < 3:
        return 1.0
    a = asset_rets[-n:]
    b = bench_rets[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((r - mean_b) ** 2 for r in b) / (n - 1)
    return cov / var_b if var_b > 1e-12 else 1.0


def _max_drawdown(monthly_returns: List[float]) -> float:
    """Returns max drawdown as a negative percentage."""
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in monthly_returns:
        cum *= (1.0 + r)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return round(max_dd * 100.0, 2)


def _sharpe(monthly_returns: List[float], rf_monthly: float = 0.004) -> float:
    """Annualised Sharpe ratio."""
    if len(monthly_returns) < 3:
        return 0.0
    excess = [r - rf_monthly for r in monthly_returns]
    n = len(excess)
    mean_ex = sum(excess) / n
    if n < 2:
        return 0.0
    std_ex = math.sqrt(sum((r - mean_ex) ** 2 for r in excess) / (n - 1))
    if std_ex < 1e-12:
        return 0.0
    return (mean_ex / std_ex) * math.sqrt(12)


def _correlation(a: List[float], b: List[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    av = a[-n:]
    bv = b[-n:]
    mean_a = sum(av) / n
    mean_b = sum(bv) / n
    cov = sum((av[i]-mean_a)*(bv[i]-mean_b) for i in range(n)) / (n-1)
    std_a = math.sqrt(sum((r-mean_a)**2 for r in av)/(n-1))
    std_b = math.sqrt(sum((r-mean_b)**2 for r in bv)/(n-1))
    if std_a < 1e-12 or std_b < 1e-12:
        return 0.0
    return max(-1.0, min(1.0, cov / (std_a * std_b)))


def _inflation_beta(asset_rets: List[float], ts_list: List[int],
                    cpi_changes: Dict[str, float]) -> float:
    """
    OLS beta of asset monthly returns against monthly CPI change.
    Uses timestamp→YYYY-MM mapping to align series.
    """
    pairs = []
    for i, ts in enumerate(ts_list[1:], start=1):   # [1:] because returns start at index 1
        ym = datetime.utcfromtimestamp(ts).strftime("%Y-%m")
        if ym in cpi_changes and i - 1 < len(asset_rets):
            pairs.append((cpi_changes[ym], asset_rets[i - 1]))
    if len(pairs) < 6:
        return 0.0
    cpi_v = [p[0] for p in pairs]
    ret_v = [p[1] for p in pairs]
    mean_c = sum(cpi_v) / len(cpi_v)
    mean_r = sum(ret_v) / len(ret_v)
    cov = sum((cpi_v[i]-mean_c)*(ret_v[i]-mean_r) for i in range(len(pairs))) / (len(pairs)-1)
    var_c = sum((c-mean_c)**2 for c in cpi_v) / (len(pairs)-1)
    return cov / var_c if var_c > 1e-12 else 0.0


def _dividend_yield(prices: List[float], dividends_raw: dict) -> float:
    """
    Trailing 12-month dividend yield = sum(divs last 12m) / current_price.
    dividends_raw: {timestamp_str: {amount: ...}} from Yahoo Finance events.
    """
    if not prices or not dividends_raw:
        return 0.0
    current_price = prices[-1]
    cutoff = time.time() - 365.25 * 24 * 3600
    total_divs = sum(
        float(v.get("amount", 0))
        for k, v in dividends_raw.items()
        if float(k) >= cutoff
    )
    if current_price <= 0:
        return 0.0
    return round((total_divs / current_price) * 100.0, 2)


def _avg_correlation(asset_key: str, all_returns: Dict[str, List[float]]) -> float:
    """Average pairwise correlation of this asset vs all others."""
    others = [k for k in all_returns if k != asset_key]
    if not others:
        return 0.0
    corrs = [
        _correlation(all_returns[asset_key], all_returns[k])
        for k in others
    ]
    return round(sum(corrs) / len(corrs), 4)


# ─────────────────────────────────────────────────────────────
# CORRELATION MATRIX
# ─────────────────────────────────────────────────────────────

def compute_live_correlation_matrix(all_returns: Dict[str, List[float]],
                                     asset_order: List[str]) -> List[List[float]]:
    n = len(asset_order)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                mat[i][j] = 1.0
            else:
                c = _correlation(all_returns[asset_order[i]], all_returns[asset_order[j]])
                mat[i][j] = round(c, 4)
    return mat


# ─────────────────────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────────────────────

def _load_cache() -> Optional[dict]:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        fetched_at = data.get("fetched_at", 0)
        age_hours  = (time.time() - fetched_at) / 3600
        if age_hours < CACHE_TTL_HOURS:
            return data
        return None   # stale
    except Exception:
        return None


def _save_cache(data: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[live_data_engine] Cache write failed: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN FETCH FUNCTION
# ─────────────────────────────────────────────────────────────

def fetch_live_metrics(force_refresh: bool = False) -> dict:
    """
    Fetch live financial metrics for all 7 asset classes.
    Returns a dict with:
      {
        "fetched_at": unix_timestamp,
        "fetched_at_str": "2026-04-13 14:22 UTC",
        "data_window": "2021-04 to 2026-04 (5 years, monthly)",
        "assets": {
          "Small Stocks": {
            "expected_return_pct": 9.41,
            "beta": 1.24,
            "volatility_pct": 20.8,
            ...
          },
          ...
        },
        "correlation_matrix": [[1.0, ...], ...],
        "asset_order": ["Small Stocks", ...],
        "source": "Yahoo Finance (ETF proxies), FRED CPI",
        "proxies": {"Small Stocks": "IWM", ...},
        "fallback": False,
      }
    Raises RuntimeError if all fetches fail and no cache exists.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            cached["from_cache"] = True
            print(f"[live_data_engine] Using cached data from {cached.get('fetched_at_str')}")
            return cached

    print("[live_data_engine] Fetching live data from Yahoo Finance...")
    asset_order = list(ASSET_PROXIES.keys())
    tickers = {k: v["ticker"] for k, v in ASSET_PROXIES.items()}

    # 1. Fetch all price series (include benchmark separately if not already)
    raw_prices: Dict[str, List[float]] = {}
    raw_ts:     Dict[str, List[int]]   = {}
    raw_divs:   Dict[str, dict]        = {}
    errors = []

    for asset, ticker in tickers.items():
        try:
            ts, prices, divs = _fetch_yahoo(ticker)
            raw_prices[asset] = prices
            raw_ts[asset]     = ts
            raw_divs[asset]   = divs
            print(f"  ✓ {asset} ({ticker}): {len(prices)} months")
        except Exception as e:
            errors.append(f"{asset}: {e}")
            print(f"  ✗ {asset} ({ticker}): {e}")

    if len(raw_prices) < 4:
        # Too few assets fetched — fall back to cache or raise
        cached = _load_cache()
        if cached:
            cached["from_cache"] = True
            cached["fetch_errors"] = errors
            print("[live_data_engine] Partial failure — returning stale cache")
            return cached
        raise RuntimeError(
            f"Live data fetch failed for {len(errors)} assets and no cache exists. "
            "Errors: " + "; ".join(errors)
        )

    # 2. Fetch CPI for inflation beta
    print("[live_data_engine] Fetching CPI from FRED...")
    try:
        cpi_changes = _fetch_cpi_monthly()
        print(f"  ✓ CPI: {len(cpi_changes)} monthly observations")
    except Exception as e:
        cpi_changes = {}
        print(f"  ✗ CPI fetch failed: {e}")

    # 3. Compute returns series for each asset
    all_returns: Dict[str, List[float]] = {
        k: _returns_from_prices(raw_prices[k])
        for k in raw_prices
    }

    # 4. Benchmark returns (SPY)
    bench_rets = all_returns.get("Large Stocks", [])

    # 5. Estimate current risk-free rate from BIL annualised return
    bil_rets = all_returns.get("Money Market", [])
    if bil_rets:
        bil_ann = _annualised_return(bil_rets[-12:]) / 100.0
        rf_monthly = max(0.001, (1 + bil_ann) ** (1/12) - 1)
    else:
        rf_monthly = 0.004   # ~4.8% annualised fallback

    # 6. Compute metrics for each asset
    asset_metrics = {}
    for asset in asset_order:
        if asset not in all_returns:
            continue
        rets = all_returns[asset]
        ts   = raw_ts[asset]

        ann_ret = _annualised_return(rets)
        vol     = _annualised_vol(rets)
        b       = _beta(rets, bench_rets)
        mdd     = _max_drawdown(rets)
        sharpe  = _sharpe(rets, rf_monthly)
        div_y   = _dividend_yield(raw_prices[asset], raw_divs[asset])
        infl_b  = _inflation_beta(rets, ts, cpi_changes) if cpi_changes else 0.0
        avg_cor = _avg_correlation(asset, all_returns)
        liq     = LIQUIDITY_SCORES.get(asset, 5.0)
        dur     = DURATION_YEARS.get(asset, 0.0)

        # Factor exposure: simplified Fama-French proxy
        # = 0.5*|beta - 1| inverted (1=market-like, higher=factor-loaded)
        factor_exp = round(min(3.0, 0.5 + abs(b - 1.0) * 0.8), 2)

        asset_metrics[asset] = {
            "expected_return_pct": round(ann_ret, 2),
            "beta":                round(b, 3),
            "volatility_pct":      round(vol, 2),
            "max_drawdown_pct":    round(mdd, 2),
            "liquidity_score":     liq,
            "avg_correlation":     round(avg_cor, 4),
            "dividend_yield_pct":  round(div_y, 2),
            "factor_exposure":     factor_exp,
            "sharpe_ratio":        round(sharpe, 3),
            "inflation_beta":      round(infl_b, 3),
            "duration_years":      dur,
            "ticker":              tickers.get(asset, ""),
            "etf_name":            ASSET_PROXIES[asset]["full_name"],
            "n_months":            len(rets),
        }

    # 7. Live correlation matrix
    live_returns_present = {k: v for k, v in all_returns.items() if k in asset_order}
    order_present = [a for a in asset_order if a in live_returns_present]
    corr_matrix = compute_live_correlation_matrix(live_returns_present, order_present)

    # 8. Data window
    first_ts = min(min(raw_ts[k]) for k in raw_ts)
    last_ts  = max(max(raw_ts[k]) for k in raw_ts)
    first_dt = datetime.utcfromtimestamp(first_ts).strftime("%Y-%m")
    last_dt  = datetime.utcfromtimestamp(last_ts).strftime("%Y-%m")

    now = time.time()
    result = {
        "fetched_at":     now,
        "fetched_at_str": datetime.utcfromtimestamp(now).strftime("%Y-%m-%d %H:%M UTC"),
        "data_window":    f"{first_dt} to {last_dt} (5-year monthly)",
        "rf_rate_annual": round(rf_monthly * 12 * 100, 2),
        "assets":         asset_metrics,
        "correlation_matrix": corr_matrix,
        "asset_order":    order_present,
        "source":         "Yahoo Finance v8 API (ETF proxies) + FRED CPIAUCSL",
        "proxies":        {k: v["ticker"] for k, v in ASSET_PROXIES.items()},
        "proxy_names":    {k: v["full_name"] for k, v in ASSET_PROXIES.items()},
        "fetch_errors":   errors,
        "fallback":       False,
        "from_cache":     False,
    }

    _save_cache(result)
    print(f"[live_data_engine] Done. Data window: {first_dt}–{last_dt}. "
          f"RF rate: {result['rf_rate_annual']:.2f}%")
    return result


# ─────────────────────────────────────────────────────────────
# CONVENIENCE: get live AssetEvidence-compatible dict
# ─────────────────────────────────────────────────────────────

def get_live_evidence_dict(scenario: str = "Steady Growth",
                            force_refresh: bool = False) -> Tuple[dict, dict]:
    """
    Returns (evidence_dict, meta_dict).
    evidence_dict maps asset_name → dict of metrics (compatible with AssetEvidence fields).
    meta_dict contains source, timestamp, proxies, etc.
    Falls back gracefully — returns (None, error_meta) if completely unavailable.
    """
    try:
        live = fetch_live_metrics(force_refresh=force_refresh)
        meta = {
            "live":          True,
            "from_cache":    live.get("from_cache", False),
            "fetched_at":    live.get("fetched_at_str", "unknown"),
            "data_window":   live.get("data_window", ""),
            "rf_rate":       live.get("rf_rate_annual", 4.5),
            "source":        live.get("source", "Yahoo Finance"),
            "proxies":       live.get("proxies", {}),
            "proxy_names":   live.get("proxy_names", {}),
            "fetch_errors":  live.get("fetch_errors", []),
            "fallback":      live.get("fallback", False),
        }
        return live.get("assets", {}), meta
    except Exception as e:
        print(f"[live_data_engine] get_live_evidence_dict failed: {e}")
        return None, {
            "live": False,
            "fallback": True,
            "error": str(e),
            "fetched_at": "unavailable",
        }


# ─────────────────────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("  LIVE DATA ENGINE — Fetching from Yahoo Finance + FRED")
    print("=" * 65)
    ev, meta = get_live_evidence_dict(force_refresh=True)
    if ev:
        print(f"\nSource   : {meta['source']}")
        print(f"Fetched  : {meta['fetched_at']}")
        print(f"Window   : {meta['data_window']}")
        print(f"RF Rate  : {meta['rf_rate']:.2f}%")
        print(f"\n{'Asset':<22} {'ER%':>6} {'Beta':>6} {'Vol%':>6} {'Sharpe':>7} {'MaxDD%':>8} {'InflB':>7}")
        print("-" * 65)
        for asset, d in ev.items():
            print(f"{asset:<22} {d['expected_return_pct']:>6.1f} {d['beta']:>6.2f} "
                  f"{d['volatility_pct']:>6.1f} {d['sharpe_ratio']:>7.3f} "
                  f"{d['max_drawdown_pct']:>8.1f} {d['inflation_beta']:>7.3f}")
        if meta.get("fetch_errors"):
            print(f"\nErrors: {meta['fetch_errors']}")
    else:
        print(f"Failed: {meta.get('error')}")
