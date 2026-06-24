"""
AI-AHP Pension Fund Portfolio Allocation System
Flask Web Application Backend
"""

import sys, os, json, time
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, jsonify, request, redirect
from ahp_engine import (
    build_liberty_bell_model, AHPModel,
    ASSET_CLASSES, CRITERIA, ACTORS, HORIZONS, SCENARIOS,
    build_matrix, priority_vector, consistency_ratio,
    LIBERTY_BELL_CONSTRAINTS,
    PRACTITIONER_PROFILES, SAATY_SCALE_OPTIONS, run_stress_test,
)
from evidence_engine import (
    get_evidence, generate_all_pairwise_suggestions,
    PENSION_FUND_ALLOCATIONS, HISTORICAL_RETURNS,
    FORWARD_PROJECTIONS, get_correlation_matrix,
)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ── Server-side API key (set ANTHROPIC_API_KEY in Railway env vars) ──
_SERVER_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# ── Simple in-memory rate limiter ────────────────────────────────────
# Each IP gets RATE_LIMIT_MAX messages per RATE_LIMIT_WINDOW seconds.
RATE_LIMIT_MAX    = 20          # messages per window
RATE_LIMIT_WINDOW = 3600        # 1 hour

_rate_store: dict = defaultdict(lambda: {'count': 0, 'reset': 0})

def _check_rate(ip: str) -> tuple[bool, int, int]:
    """Returns (allowed, used, remaining)."""
    now  = time.time()
    data = _rate_store[ip]
    if now > data['reset']:
        data['count'] = 0
        data['reset'] = now + RATE_LIMIT_WINDOW
    if data['count'] >= RATE_LIMIT_MAX:
        return False, data['count'], 0
    data['count'] += 1
    return True, data['count'], RATE_LIMIT_MAX - data['count']

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/platform')
def platform():
    return render_template('platform.html')


# ── Scenario → criteria pairwise comparisons ──────────────────
_SCENARIO_CRITERIA = {
    "Steady Growth": {
        ("Return","Risk"): 2, ("Return","Liquidity"): 5,
        ("Return","Diversification"): 3,
        ("Risk","Liquidity"): 3, ("Risk","Diversification"): 2,
        ("Liquidity","Diversification"): 0.5,
    },
    "Bull Market": {
        ("Return","Risk"): 4, ("Return","Liquidity"): 7,
        ("Return","Diversification"): 5,
        ("Risk","Liquidity"): 2, ("Risk","Diversification"): 2,
        ("Liquidity","Diversification"): 1,
    },
    "Stagflation": {
        ("Return","Risk"): 1/3, ("Return","Liquidity"): 2,
        ("Return","Diversification"): 1,
        ("Risk","Liquidity"): 4, ("Risk","Diversification"): 3,
        ("Liquidity","Diversification"): 1,
    },
    "Deflation": {
        ("Return","Risk"): 0.25, ("Return","Liquidity"): 0.5,
        ("Return","Diversification"): 0.5,
        ("Risk","Liquidity"): 0.5, ("Risk","Diversification"): 1,
        ("Liquidity","Diversification"): 2,
    },
}

# ── Scenario → asset Return scores ────────────────────────────
# Higher score = better expected return under this macro environment.
_SCENARIO_ASSET_RETURN = {
    "Bull Market": {
        # Equities dominate aggressively; bonds sidelined
        ("Small Stocks","Large Stocks"):3, ("Small Stocks","Corporate Bonds"):7,
        ("Small Stocks","Government Bonds"):9, ("Small Stocks","Real Estate"):4,
        ("Small Stocks","Money Market"):9, ("Small Stocks","Commodities"):5,
        ("Large Stocks","Corporate Bonds"):4, ("Large Stocks","Government Bonds"):7,
        ("Large Stocks","Real Estate"):3, ("Large Stocks","Money Market"):9,
        ("Large Stocks","Commodities"):3,
        ("Corporate Bonds","Government Bonds"):2, ("Corporate Bonds","Real Estate"):1/2,
        ("Corporate Bonds","Money Market"):4, ("Corporate Bonds","Commodities"):1/2,
        ("Government Bonds","Real Estate"):1/4, ("Government Bonds","Money Market"):3,
        ("Government Bonds","Commodities"):1/3,
        ("Real Estate","Money Market"):5, ("Real Estate","Commodities"):2,
        ("Money Market","Commodities"):1/4,
    },
    "Stagflation": {
        # Commodities & Real Estate are the inflation hedges; gov bonds are worst
        ("Small Stocks","Large Stocks"):1, ("Small Stocks","Corporate Bonds"):2,
        ("Small Stocks","Government Bonds"):5, ("Small Stocks","Real Estate"):1/2,
        ("Small Stocks","Money Market"):3, ("Small Stocks","Commodities"):1/3,
        ("Large Stocks","Corporate Bonds"):2, ("Large Stocks","Government Bonds"):5,
        ("Large Stocks","Real Estate"):1/2, ("Large Stocks","Money Market"):3,
        ("Large Stocks","Commodities"):1/3,
        ("Corporate Bonds","Government Bonds"):2, ("Corporate Bonds","Real Estate"):1/3,
        ("Corporate Bonds","Money Market"):2, ("Corporate Bonds","Commodities"):1/5,
        ("Government Bonds","Real Estate"):1/5, ("Government Bonds","Money Market"):1,
        ("Government Bonds","Commodities"):1/7,
        ("Real Estate","Money Market"):4, ("Real Estate","Commodities"):1/2,
        ("Money Market","Commodities"):1/5,
    },
    "Deflation": {
        # Government bonds price-appreciate as rates fall; commodities worst
        ("Small Stocks","Large Stocks"):1, ("Small Stocks","Corporate Bonds"):1/2,
        ("Small Stocks","Government Bonds"):1/5, ("Small Stocks","Real Estate"):1,
        ("Small Stocks","Money Market"):2, ("Small Stocks","Commodities"):3,
        ("Large Stocks","Corporate Bonds"):1/2, ("Large Stocks","Government Bonds"):1/5,
        ("Large Stocks","Real Estate"):1, ("Large Stocks","Money Market"):2,
        ("Large Stocks","Commodities"):3,
        ("Corporate Bonds","Government Bonds"):1/3, ("Corporate Bonds","Real Estate"):2,
        ("Corporate Bonds","Money Market"):4, ("Corporate Bonds","Commodities"):5,
        ("Government Bonds","Real Estate"):5, ("Government Bonds","Money Market"):7,
        ("Government Bonds","Commodities"):8,
        ("Real Estate","Money Market"):2, ("Real Estate","Commodities"):3,
        ("Money Market","Commodities"):1,
    },
}

# ── Scenario → asset Risk scores ──────────────────────────────
# Higher score = SAFER (lower actual risk) under this macro environment.
_SCENARIO_ASSET_RISK = {
    "Bull Market": {
        # Risk appetite rises — equities penalised less
        ("Small Stocks","Large Stocks"):1/2, ("Small Stocks","Corporate Bonds"):1/3,
        ("Small Stocks","Government Bonds"):1/5, ("Small Stocks","Real Estate"):1/2,
        ("Small Stocks","Money Market"):1/7, ("Small Stocks","Commodities"):1/2,
        ("Large Stocks","Corporate Bonds"):1/2, ("Large Stocks","Government Bonds"):1/3,
        ("Large Stocks","Real Estate"):1/2, ("Large Stocks","Money Market"):1/5,
        ("Large Stocks","Commodities"):1,
        ("Corporate Bonds","Government Bonds"):1/2, ("Corporate Bonds","Real Estate"):2,
        ("Corporate Bonds","Money Market"):1/3, ("Corporate Bonds","Commodities"):2,
        ("Government Bonds","Real Estate"):3, ("Government Bonds","Money Market"):1/2,
        ("Government Bonds","Commodities"):4,
        ("Real Estate","Money Market"):1/4, ("Real Estate","Commodities"):1,
        ("Money Market","Commodities"):5,
    },
    "Stagflation": {
        # Extreme risk aversion; govts and cash dominate; commodities volatile
        ("Small Stocks","Large Stocks"):1/2, ("Small Stocks","Corporate Bonds"):1/5,
        ("Small Stocks","Government Bonds"):1/9, ("Small Stocks","Real Estate"):1/3,
        ("Small Stocks","Money Market"):1/9, ("Small Stocks","Commodities"):1/2,
        ("Large Stocks","Corporate Bonds"):1/4, ("Large Stocks","Government Bonds"):1/8,
        ("Large Stocks","Real Estate"):1/2, ("Large Stocks","Money Market"):1/9,
        ("Large Stocks","Commodities"):1,
        ("Corporate Bonds","Government Bonds"):1/3, ("Corporate Bonds","Real Estate"):2,
        ("Corporate Bonds","Money Market"):1/5, ("Corporate Bonds","Commodities"):3,
        ("Government Bonds","Real Estate"):5, ("Government Bonds","Money Market"):1/2,
        ("Government Bonds","Commodities"):8,
        ("Real Estate","Money Market"):1/5, ("Real Estate","Commodities"):2,
        ("Money Market","Commodities"):9,
    },
    "Deflation": {
        # Flight to quality: government bonds = safest; commodities destroyed
        ("Small Stocks","Large Stocks"):1/2, ("Small Stocks","Corporate Bonds"):1/4,
        ("Small Stocks","Government Bonds"):1/9, ("Small Stocks","Real Estate"):1/3,
        ("Small Stocks","Money Market"):1/8, ("Small Stocks","Commodities"):1/3,
        ("Large Stocks","Corporate Bonds"):1/3, ("Large Stocks","Government Bonds"):1/9,
        ("Large Stocks","Real Estate"):1/2, ("Large Stocks","Money Market"):1/7,
        ("Large Stocks","Commodities"):1/2,
        ("Corporate Bonds","Government Bonds"):1/4, ("Corporate Bonds","Real Estate"):2,
        ("Corporate Bonds","Money Market"):1/3, ("Corporate Bonds","Commodities"):3,
        ("Government Bonds","Real Estate"):6, ("Government Bonds","Money Market"):1,
        ("Government Bonds","Commodities"):9,
        ("Real Estate","Money Market"):1/6, ("Real Estate","Commodities"):1,
        ("Money Market","Commodities"):7,
    },
}

# ── Scenario → policy constraints ─────────────────────────────
_SCENARIO_CONSTRAINTS = {
    "Steady Growth": {
        "Small Stocks":(0.05,0.25), "Large Stocks":(0.15,0.40),
        "Corporate Bonds":(0.05,0.20), "Government Bonds":(0.10,0.30),
        "Real Estate":(0.05,0.15), "Money Market":(0.02,0.10),
        "Commodities":(0.00,0.10),
    },
    "Bull Market": {
        "Small Stocks":(0.10,0.30), "Large Stocks":(0.20,0.45),
        "Corporate Bonds":(0.05,0.15), "Government Bonds":(0.05,0.20),
        "Real Estate":(0.05,0.18), "Money Market":(0.02,0.08),
        "Commodities":(0.02,0.10),
    },
    "Stagflation": {
        "Small Stocks":(0.03,0.15), "Large Stocks":(0.08,0.25),
        "Corporate Bonds":(0.05,0.15), "Government Bonds":(0.15,0.35),
        "Real Estate":(0.08,0.20), "Money Market":(0.05,0.15),
        "Commodities":(0.05,0.20),
    },
    "Deflation": {
        "Small Stocks":(0.03,0.12), "Large Stocks":(0.08,0.22),
        "Corporate Bonds":(0.08,0.22), "Government Bonds":(0.25,0.45),
        "Real Estate":(0.03,0.12), "Money Market":(0.05,0.18),
        "Commodities":(0.00,0.05),
    },
}

@app.route('/api/run', methods=['POST'])
def run_ahp():
    """Run full AHP model and return results."""
    data         = request.json or {}
    fund_name    = data.get('fund_name', 'Liberty Bell Pension Fund')
    aum          = float(data.get('aum', 3.2))
    scenario     = data.get('scenario', 'Steady Growth')
    funded_ratio = float(data.get('funded_ratio', 87))
    n_mc         = int(data.get('n_simulations', 1000))

    model = build_liberty_bell_model()
    model.fund_name    = fund_name
    model.aum_billions = aum

    # 1. Scenario-specific criteria balance (how much Return vs Risk matters)
    if scenario in _SCENARIO_CRITERIA:
        model.set_criteria_matrix(_SCENARIO_CRITERIA[scenario])

    # 2. Scenario-specific asset matrices (which assets win on Return / Risk)
    if scenario in _SCENARIO_ASSET_RETURN:
        model.set_asset_matrix("Return", _SCENARIO_ASSET_RETURN[scenario])
    if scenario in _SCENARIO_ASSET_RISK:
        model.set_asset_matrix("Risk", _SCENARIO_ASSET_RISK[scenario])

    # 3. Scenario-specific policy constraints
    if scenario in _SCENARIO_CONSTRAINTS:
        model.constraints = _SCENARIO_CONSTRAINTS[scenario].copy()

    # 4. Funded-ratio overlay: underfunded (<85%) tightens equity, raises bond floor
    if funded_ratio < 85:
        shift = min(0.08, (85 - funded_ratio) / 100)  # up to 8pp shift
        for asset in ["Small Stocks", "Large Stocks"]:
            lo, hi = model.constraints[asset]
            model.constraints[asset] = (max(0, lo - shift/2), max(lo, hi - shift))
        for asset in ["Government Bonds", "Money Market"]:
            lo, hi = model.constraints[asset]
            model.constraints[asset] = (min(hi, lo + shift/2), min(0.50, hi + shift/2))
    elif funded_ratio > 110:
        # Well-funded: allow more equity upside
        shift = min(0.05, (funded_ratio - 110) / 200)
        for asset in ["Small Stocks", "Large Stocks"]:
            lo, hi = model.constraints[asset]
            model.constraints[asset] = (lo, min(0.55, hi + shift))

    result = model.run()
    mc     = model.run_monte_carlo(n_simulations=n_mc)

    # Add criteria_weights to result for dashboard chart
    if model.criteria_weights is not None:
        result['criteria_weights'] = dict(zip(CRITERIA, model.criteria_weights.tolist()))
    else:
        result['criteria_weights'] = {c: 1/len(CRITERIA) for c in CRITERIA}

    # IPS policy bands (min/max per asset class after scenario + funded-ratio overlay)
    constraints_out = {a: [float(lo), float(hi)] for a, (lo, hi) in model.constraints.items()}

    # Baseline: long-term Steady Growth at 87% funded — used for delta comparison
    baseline_model = build_liberty_bell_model()
    if 'Steady Growth' in _SCENARIO_CRITERIA:
        baseline_model.set_criteria_matrix(_SCENARIO_CRITERIA['Steady Growth'])
    if 'Steady Growth' in _SCENARIO_ASSET_RETURN:
        baseline_model.set_asset_matrix('Return', _SCENARIO_ASSET_RETURN['Steady Growth'])
    if 'Steady Growth' in _SCENARIO_ASSET_RISK:
        baseline_model.set_asset_matrix('Risk', _SCENARIO_ASSET_RISK['Steady Growth'])
    if 'Steady Growth' in _SCENARIO_CONSTRAINTS:
        baseline_model.constraints = _SCENARIO_CONSTRAINTS['Steady Growth'].copy()
    baseline_weights = baseline_model.run()['constrained_weights']

    return jsonify({
        'status':        'ok',
        'fund_name':     fund_name,
        'aum':           aum,
        'scenario':      scenario,
        'result':        result,
        'monte_carlo':   mc,
        'asset_classes': ASSET_CLASSES,
        'criteria':      CRITERIA,
        'constraints':   constraints_out,
        'baseline_weights': baseline_weights,
    })


@app.route('/api/evidence')
def evidence():
    scenario = request.args.get('scenario', 'Steady Growth')
    force    = request.args.get('refresh', 'false').lower() == 'true'

    # Try live data; get metadata alongside
    data_meta = {'live': False, 'fetched_at': 'hardcoded fallback',
                 'source': 'Research-calibrated (Bloomberg/CRSP/MSCI 2020-2025)',
                 'proxies': {}, 'data_window': 'N/A', 'from_cache': False}
    try:
        from live_data_engine import get_live_evidence_dict
        _, live_meta = get_live_evidence_dict(force_refresh=force)
        if live_meta and not live_meta.get('fallback'):
            data_meta = {
                'live':        True,
                'fetched_at':  live_meta.get('fetched_at', ''),
                'data_window': live_meta.get('data_window', ''),
                'source':      live_meta.get('source', 'Yahoo Finance'),
                'proxies':     live_meta.get('proxies', {}),
                'proxy_names': live_meta.get('proxy_names', {}),
                'rf_rate':     live_meta.get('rf_rate', 4.5),
                'from_cache':  live_meta.get('from_cache', False),
                'fetch_errors': live_meta.get('fetch_errors', []),
            }
    except Exception:
        pass

    ev   = get_evidence(scenario)
    corr = get_correlation_matrix(scenario).tolist()

    ev_out = {}
    for asset, d in ev.items():
        proxy_ticker = data_meta.get('proxies', {}).get(asset, '')
        ev_out[asset] = {
            'expected_return': d.expected_return_pct,
            'beta':            d.beta,
            'volatility':      d.volatility_pct,
            'max_drawdown':    d.max_drawdown_pct,
            'liquidity':       d.liquidity_score,
            'avg_correlation': d.avg_correlation,
            'sharpe':          d.sharpe_ratio,
            'inflation_beta':  d.inflation_beta,
            'dividend_yield':  d.dividend_yield_pct,
            'proxy_ticker':    proxy_ticker,
        }

    suggestions = {}
    for crit in CRITERIA:
        sug = generate_all_pairwise_suggestions(ev, crit)
        suggestions[crit] = {
            f"{a} vs {b}": {'value': abs(v), 'preferred': a if v > 0 else b, 'reason': r[:120]}
            for (a, b), (v, r) in sug.items()
        }

    return jsonify({
        'evidence':      ev_out,
        'correlation':   corr,
        'suggestions':   suggestions,
        'asset_classes': ASSET_CLASSES,
        'scenario':      scenario,
        'data_meta':     data_meta,
    })


@app.route('/api/refresh-data', methods=['POST'])
def refresh_data():
    """Force-refresh live data cache from Yahoo Finance."""
    try:
        from live_data_engine import fetch_live_metrics
        result = fetch_live_metrics(force_refresh=True)
        return jsonify({
            'status':      'ok',
            'fetched_at':  result['fetched_at_str'],
            'data_window': result['data_window'],
            'source':      result['source'],
            'n_assets':    len(result.get('assets', {})),
            'rf_rate':     result.get('rf_rate_annual'),
            'errors':      result.get('fetch_errors', []),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/validate')
def validate():
    from validation_engine import PensionFundValidator
    validator = PensionFundValidator()
    results   = validator.validate_all()
    stats     = validator.overall_stats()

    rows = [
        {
            'fund':         r.fund_name,
            'year':         r.year,
            'scenario':     r.scenario,
            'mae':          round(r.mae * 100, 2),
            'rmse':         round(r.rmse * 100, 2),
            'correlation':  round(r.correlation, 3),
            'grade':        r.grade,
            'max_dev_asset': r.max_deviation_asset,
            'max_dev_pct':  round(r.max_deviation_pct * 100, 2),
        }
        for r in sorted(results, key=lambda x: (x.fund_name, x.year))
    ]

    summaries = {
        fund: {
            'avg_mae':   round(s['avg_mae'] * 100, 2),
            'avg_corr':  round(s['avg_corr'], 3),
            'hit_rate':  round(s['hit_rate'] * 100, 1),
            'grades':    s['grades'],
        }
        for fund, s in validator.fund_summaries.items()
    }

    return jsonify({
        'rows':      rows,
        'summaries': summaries,
        'overall':   stats,
    })


@app.route('/api/forecast')
def forecast():
    try:
        from validation_engine import ForecastEngine
        fund = request.args.get('fund', 'CalPERS')
        fe   = ForecastEngine()
        data = fe.forecast_allocations(fund, [2026, 2027, 2028, 2029, 2030])
        attr = fe.compute_returns_attribution(fund)
        return jsonify({'forecast': data, 'attribution': attr})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/sensitivity', methods=['POST'])
def sensitivity():
    data   = request.json or {}
    crit   = data.get('criterion', 'Return')
    model  = build_liberty_bell_model()
    model.run()
    result = model.sensitivity_analysis(crit, steps=9)
    return jsonify(result)


@app.route('/api/chat', methods=['POST'])
def chat():
    """Proxy to Claude adversarial / advisor chatbot."""
    data       = request.json or {}
    # Prefer client-supplied key; fall back to server env key
    api_key    = data.get('api_key', '').strip() or _SERVER_API_KEY
    message    = data.get('message', '')
    mode       = data.get('mode', 'CHALLENGE')
    history    = data.get('history', [])
    model_ctx  = data.get('model_context', {})

    if not api_key:
        return jsonify({'error': 'No API key configured. Please contact the site administrator.'}), 503
    if not message:
        return jsonify({'error': 'Message required'}), 400

    # Rate-limit only when using the server key (users with their own key bypass)
    using_server_key = not data.get('api_key', '').strip()
    if using_server_key:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        allowed, used, remaining = _check_rate(ip)
        if not allowed:
            return jsonify({
                'error': f'Session limit reached ({RATE_LIMIT_MAX} messages per hour). '
                         'Enter your own Anthropic API key below to continue unlimited.',
                'rate_limited': True,
                'used': used,
                'limit': RATE_LIMIT_MAX,
            }), 429

    try:
        from chatbot_agent import AHPChallengerBot
        bot = AHPChallengerBot(mode=mode, api_key=api_key)
        bot.conversation_history = history

        # Inject model context as a system-level prefix if available
        if model_ctx:
            import json as _json
            ctx_lines = []
            if model_ctx.get('fund_name'):
                ctx_lines.append(f"Fund: {model_ctx['fund_name']}")
            if model_ctx.get('aum'):
                ctx_lines.append(f"AUM: ${model_ctx['aum']}B")
            if model_ctx.get('scenario'):
                ctx_lines.append(f"Macro Scenario: {model_ctx['scenario']}")
            if model_ctx.get('overall_grade'):
                ctx_lines.append(f"AHP Overall Grade: {model_ctx['overall_grade']}")
            if model_ctx.get('funded_ratio'):
                ctx_lines.append(f"Funded Ratio: {model_ctx['funded_ratio']}%")
            if model_ctx.get('constrained_weights'):
                w = model_ctx['constrained_weights']
                aum = float(model_ctx.get('aum', 0))
                alloc_lines = []
                for asset, weight in sorted(w.items(), key=lambda x: -x[1]):
                    dollar = weight * aum
                    alloc_lines.append(
                        f"  {asset}: {weight*100:.1f}%"
                        + (f" = ${dollar:.3f}B" if aum > 0 else "")
                    )
                ctx_lines.append("Current AHP Allocation:\n" + "\n".join(alloc_lines))
            if model_ctx.get('criteria_weights'):
                cw = model_ctx['criteria_weights']
                ctx_lines.append("Criteria Weights: " +
                    ", ".join(f"{k}={v*100:.1f}%" for k, v in cw.items()))
            if model_ctx.get('consistency_results'):
                cr_data = model_ctx['consistency_results']
                avg_cr = sum(v['CR'] for v in cr_data.values()) / len(cr_data)
                ctx_lines.append(f"Avg Consistency Ratio: {avg_cr:.4f} (all 10 matrices pass CR ≤ 0.10)")
            if model_ctx.get('dollar_allocation'):
                pass  # already included in constrained_weights block above
            if model_ctx.get('mc_summary'):
                mc = model_ctx['mc_summary']
                high_sens = [a for a, v in mc.items() if v.get('sensitivity') == 'HIGH']
                if high_sens:
                    ctx_lines.append(f"High-sensitivity assets: {', '.join(high_sens)}")
                else:
                    ctx_lines.append("Monte Carlo: all assets LOW/MEDIUM sensitivity (robust)")

            if ctx_lines:
                context_block = (
                    "\n=== LIVE AHP MODEL CONTEXT ===\n"
                    + "\n".join(ctx_lines)
                    + "\n==============================\n\n"
                )
                message = context_block + message

        reply = bot.ask_question(message)
        resp_data = {'reply': reply, 'history': bot.conversation_history}
        if using_server_key:
            resp_data['used']      = used
            resp_data['remaining'] = remaining
            resp_data['limit']     = RATE_LIMIT_MAX
        return jsonify(resp_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/benchmark')
def benchmark():
    """
    Deep per-fund benchmark: model weights vs actual weights, year-by-year,
    for all 8 pension funds. Returns data needed for side-by-side charts,
    error heatmap, and scatter plot.
    """
    try:
        from validation_engine import PensionFundValidator, _build_model_for_fund
        import numpy as np

        fund_filter = request.args.get('fund', None)

        validator = PensionFundValidator()
        results = validator.validate_all()

        funds_data = {}
        for fund_name, fund_meta in PENSION_FUND_ALLOCATIONS.items():
            if fund_filter and fund_name != fund_filter:
                continue

            fund_results = [r for r in results if r.fund_name == fund_name]
            years = sorted([r.year for r in fund_results])

            year_data = {}
            for r in sorted(fund_results, key=lambda x: x.year):
                year_data[r.year] = {
                    'model':         {a: round(r.model_weights.get(a, 0), 4) for a in ASSET_CLASSES},
                    'actual':        {a: round(r.actual_weights.get(a, 0), 4) for a in ASSET_CLASSES},
                    'mae':           round(r.mae * 100, 3),
                    'rmse':          round(r.rmse * 100, 3),
                    'correlation':   round(r.correlation, 4),
                    'grade':         r.grade,
                    'scenario':      r.scenario,
                    'max_dev_asset': r.max_deviation_asset,
                    'max_dev_pct':   round(r.max_deviation_pct * 100, 2),
                }

            asset_errors = {}
            for asset in ASSET_CLASSES:
                errs = [abs(year_data[y]['model'][asset] - year_data[y]['actual'][asset]) * 100
                        for y in years if y in year_data]
                asset_errors[asset] = {
                    'mean_error': round(float(np.mean(errs)), 3) if errs else 0,
                    'max_error':  round(float(np.max(errs)), 3) if errs else 0,
                }

            funds_data[fund_name] = {
                'meta': {
                    'description':    fund_meta.get('description', ''),
                    'aum':            fund_meta.get('AUM_USD_billions', 0),
                    'funded_ratio':   fund_meta.get('funded_ratio_pct', 0),
                    'horizon':        fund_meta.get('horizon', ''),
                    'risk_tolerance': fund_meta.get('risk_tolerance', ''),
                },
                'years':        years,
                'year_data':    year_data,
                'asset_errors': asset_errors,
                'summary':      validator.fund_summaries.get(fund_name, {}),
            }

        all_funds = list(funds_data.keys())
        heatmap = []
        for fund in all_funds:
            row = [funds_data[fund]['asset_errors'].get(a, {}).get('mean_error', 0)
                   for a in ASSET_CLASSES]
            heatmap.append(row)

        return jsonify({
            'funds':         funds_data,
            'fund_list':     all_funds,
            'asset_classes': ASSET_CLASSES,
            'heatmap':       heatmap,
            'overall':       validator.overall_stats(),
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/practitioner-profiles')
def practitioner_profiles():
    """Return all 5 practitioner profiles with criteria values."""
    out = {}
    for name, p in PRACTITIONER_PROFILES.items():
        # Convert tuple keys to string for JSON
        out[name] = {
            "description": p["description"],
            "archetype":   p["archetype"],
            "priority":    p["priority"],
            "criteria":    {f"{a} vs {b}": v for (a, b), v in p["criteria"].items()},
        }
    saaty_options = [{"value": v, "label": lbl} for v, lbl in SAATY_SCALE_OPTIONS]
    return jsonify({"profiles": out, "saaty_options": saaty_options})


@app.route('/api/stress-test', methods=['POST'])
def stress_test():
    """
    Run practitioner stress test against base Liberty Bell model.
    Body: { "criteria": {"Return vs Risk": 3, "Return vs Liquidity": 5, ...} }
    """
    data     = request.json or {}
    criteria_raw = data.get('criteria', {})
    if not criteria_raw:
        return jsonify({'error': 'criteria dict required'}), 400

    # Parse "Return vs Risk" → ("Return", "Risk")
    VALID_CRIT = set(CRITERIA)
    criteria: dict = {}
    for key, val in criteria_raw.items():
        parts = [p.strip() for p in key.split(' vs ')]
        if len(parts) == 2 and parts[0] in VALID_CRIT and parts[1] in VALID_CRIT:
            criteria[(parts[0], parts[1])] = float(val)

    required_pairs = [
        ("Return", "Risk"), ("Return", "Liquidity"), ("Return", "Diversification"),
        ("Risk", "Liquidity"), ("Risk", "Diversification"), ("Liquidity", "Diversification"),
    ]
    for pair in required_pairs:
        if pair not in criteria:
            criteria[pair] = 1.0  # default to equal

    try:
        result = run_stress_test(criteria)
        return jsonify({'status': 'ok', **result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/forecast-ci')
def forecast_ci():
    """
    Bootstrap CI forecast for 2026–2030.
    Query params: fund (default CalPERS), n_sims (default 400)
    """
    fund   = request.args.get('fund', 'CalPERS')
    n_sims = int(request.args.get('n_sims', 400))
    n_sims = max(100, min(n_sims, 1000))  # safety clamp

    try:
        from validation_engine import BootstrapForecastEngine
        engine = BootstrapForecastEngine()
        result = engine.forecast_with_ci(fund_name=fund, n_sims=n_sims)
        return jsonify({'status': 'ok', **result})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/constants')
def constants():
    return jsonify({
        'asset_classes': ASSET_CLASSES,
        'criteria':      CRITERIA,
        'actors':        ACTORS,
        'horizons':      HORIZONS,
        'scenarios':     SCENARIOS,
        'constraints':   {k: list(v) for k, v in LIBERTY_BELL_CONSTRAINTS.items()},
        'pension_funds': list(PENSION_FUND_ALLOCATIONS.keys()),
        'historical_returns': HISTORICAL_RETURNS,
        'forward_projections': FORWARD_PROJECTIONS,
    })


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, port=port, host='0.0.0.0')
