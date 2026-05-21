"""
AHP Engine — Full 6-Level Hierarchy
Based on Khaksari, Kamath & Grieves (1989), Journal of Portfolio Management
Extended with AI-driven enhancements, dual synthesis, Monte Carlo, and ANP feedback loops.

Hierarchy:
  Level 1 : Goal (Optimal Portfolio Allocation)
  Level 2 : Actors (Sponsor, Beneficiaries, Portfolio Manager)
  Level 3 : Investment Horizon (Short, Medium, Long)
  Level 4 : Economic Scenarios (Bull, Stagflation, Deflation, Growth)
  Level 5 : Criteria + Sub-Criteria (Return, Risk, Liquidity, Diversification)
  Level 6 : Asset Classes (Small Stocks, Large Stocks, Corp Bonds, Govt Bonds,
                           Real Estate, Money Market, Commodities)
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# SAATY CONSTANTS
# ─────────────────────────────────────────────────────────────
SAATY_SCALE = [1/9, 1/8, 1/7, 1/6, 1/5, 1/4, 1/3, 1/2,
               1, 2, 3, 4, 5, 6, 7, 8, 9]

# Random Index values for matrix sizes 1–10 (Saaty 1980)
RI = {1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
      6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

ASSET_CLASSES = [
    "Small Stocks",
    "Large Stocks",
    "Corporate Bonds",
    "Government Bonds",
    "Real Estate",
    "Money Market",
    "Commodities",
]

CRITERIA = ["Return", "Risk", "Liquidity", "Diversification"]
ACTORS   = ["Sponsor", "Beneficiaries", "Portfolio Manager"]
HORIZONS = ["Short-term", "Medium-term", "Long-term"]
SCENARIOS = ["Bull Market", "Stagflation", "Deflation", "Steady Growth"]

RISK_SUB_CRITERIA    = ["Beta", "Volatility", "Max Drawdown", "Liquidity Risk"]
RETURN_SUB_CRITERIA  = ["Expected Return", "Dividend Yield", "Growth Potential"]

# Liberty Bell Policy Constraints (from original 1989 paper)
LIBERTY_BELL_CONSTRAINTS = {
    "Small Stocks":       (0.05, 0.25),
    "Large Stocks":       (0.15, 0.40),
    "Corporate Bonds":    (0.05, 0.20),
    "Government Bonds":   (0.10, 0.30),
    "Real Estate":        (0.05, 0.15),
    "Money Market":       (0.02, 0.10),
    "Commodities":        (0.00, 0.10),
}


# ─────────────────────────────────────────────────────────────
# CORE AHP FUNCTIONS
# ─────────────────────────────────────────────────────────────

def priority_vector(matrix: np.ndarray) -> np.ndarray:
    """Geometric-mean method for priority vector (Saaty 1980)."""
    n = matrix.shape[0]
    geo_means = np.array([np.prod(matrix[i, :]) ** (1.0 / n) for i in range(n)])
    return geo_means / geo_means.sum()


def consistency_ratio(matrix: np.ndarray, weights: np.ndarray) -> Tuple[float, float, str]:
    """
    Returns (lambda_max, CI, CR, grade).
    Grade: A (<0.05), B (0.05–0.08), C (0.08–0.10), F (>0.10).
    """
    n = matrix.shape[0]
    if n <= 2:
        return float(n), 0.0, 0.0, "A"
    lam_max = float(np.dot(matrix @ weights, 1.0 / weights) / n)
    ci = (lam_max - n) / (n - 1)
    ri = RI.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0
    if cr < 0.05:
        grade = "A"
    elif cr < 0.08:
        grade = "B"
    elif cr <= 0.10:
        grade = "C"
    else:
        grade = "F"
    return lam_max, ci, cr, grade


def repair_matrix(matrix: np.ndarray, max_iter: int = 10) -> Tuple[np.ndarray, int]:
    """
    Saaty's auto-repair: replace most deviant element with w_i / w_j ratio.
    Returns (repaired_matrix, iterations_used).
    """
    m = matrix.copy()
    n = m.shape[0]
    for iteration in range(max_iter):
        w = priority_vector(m)
        _, _, cr, _ = consistency_ratio(m, w)
        if cr <= 0.10:
            return m, iteration
        # Find most deviant off-diagonal element
        max_dev, best_i, best_j = -1, 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                ideal = w[i] / w[j]
                dev = abs(m[i, j] - ideal)
                if dev > max_dev:
                    max_dev, best_i, best_j = dev, i, j
        new_val = w[best_i] / w[best_j]
        m[best_i, best_j] = new_val
        m[best_j, best_i] = 1.0 / new_val
    return m, max_iter


def build_matrix(items: List[str], comparisons: Dict[Tuple[str, str], float]) -> np.ndarray:
    """Build pairwise comparison matrix from a dict of (item_i, item_j) → value."""
    n = len(items)
    idx = {item: i for i, item in enumerate(items)}
    m = np.ones((n, n))
    for (a, b), v in comparisons.items():
        i, j = idx[a], idx[b]
        m[i, j] = v
        m[j, i] = 1.0 / v
    return m


def dual_synthesis(
    dist_weights: np.ndarray,
    ideal_weights: np.ndarray,
    threshold: float = 0.05,
) -> Tuple[np.ndarray, bool, str]:
    """
    Compare distributive vs ideal mode synthesis.
    Returns (final_weights, rank_reversal_flag, message).
    """
    rank_dist  = np.argsort(-dist_weights)
    rank_ideal = np.argsort(-ideal_weights)
    max_diff   = np.max(np.abs(dist_weights - ideal_weights))
    rank_reversal = not np.array_equal(rank_dist[:3], rank_ideal[:3])
    if rank_reversal or max_diff > threshold:
        msg = (
            f"WARNING: Rank reversal detected (max diff={max_diff:.4f}). "
            "Dual synthesis results diverge — review pairwise inputs."
        )
        # Use average as conservative estimate
        final = (dist_weights + ideal_weights) / 2.0
        final /= final.sum()
        return final, True, msg
    return dist_weights, False, "Dual synthesis stable."


# ─────────────────────────────────────────────────────────────
# 6-LEVEL AHP MODEL CLASS
# ─────────────────────────────────────────────────────────────

class AHPModel:
    """
    Full 6-level AHP model for institutional pension fund asset allocation.
    Implements the complete Khaksari, Kamath & Grieves (1989) framework
    with AI-era enhancements.
    """

    def __init__(self, fund_name: str = "Liberty Bell Pension Fund",
                 aum_billions: float = 3.2):
        self.fund_name    = fund_name
        self.aum_billions = aum_billions

        # Store all pairwise matrices (raw inputs)
        self.matrices: Dict[str, np.ndarray] = {}

        # Derived weights at each level
        self.actor_weights:    Optional[np.ndarray] = None
        self.horizon_weights:  Optional[np.ndarray] = None
        self.scenario_weights: Optional[np.ndarray] = None
        self.criteria_weights: Optional[np.ndarray] = None
        self.risk_sub_weights: Optional[np.ndarray] = None
        self.return_sub_weights: Optional[np.ndarray] = None
        self.asset_weights_by_criterion: Dict[str, np.ndarray] = {}
        self.final_weights:    Optional[np.ndarray] = None

        # Consistency results
        self.cr_results: Dict[str, Dict] = {}

        # ANP feedback factors (default = no feedback)
        self.anp_enabled  = False
        self.anp_feedback = {}

        # Policy constraints
        self.constraints = LIBERTY_BELL_CONSTRAINTS.copy()

        # Monte Carlo results
        self.mc_results: Optional[Dict] = None

    # ── LEVEL 2: Actors ──────────────────────────────────────

    def set_actor_matrix(self, comparisons: Dict[Tuple[str, str], float]):
        """
        Example: {('Sponsor','Beneficiaries'): 4, ('Sponsor','Portfolio Manager'): 5, ...}
        """
        m = build_matrix(ACTORS, comparisons)
        m, iters = repair_matrix(m)
        self.matrices["Actors"] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.actor_weights = w
        self.cr_results["Actors"] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                     "grade": grade, "repair_iters": iters}

    # ── LEVEL 3: Horizon ─────────────────────────────────────

    def set_horizon_matrix(self, comparisons: Dict[Tuple[str, str], float]):
        m = build_matrix(HORIZONS, comparisons)
        m, iters = repair_matrix(m)
        self.matrices["Horizon"] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.horizon_weights = w
        self.cr_results["Horizon"] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                      "grade": grade, "repair_iters": iters}

    # ── LEVEL 4: Scenarios ───────────────────────────────────

    def set_scenario_matrix(self, comparisons: Dict[Tuple[str, str], float]):
        m = build_matrix(SCENARIOS, comparisons)
        m, iters = repair_matrix(m)
        self.matrices["Scenarios"] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.scenario_weights = w
        self.cr_results["Scenarios"] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                        "grade": grade, "repair_iters": iters}

    # ── LEVEL 5: Criteria ────────────────────────────────────

    def set_criteria_matrix(self, comparisons: Dict[Tuple[str, str], float]):
        m = build_matrix(CRITERIA, comparisons)
        m, iters = repair_matrix(m)
        self.matrices["Criteria"] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.criteria_weights = w
        self.cr_results["Criteria"] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                       "grade": grade, "repair_iters": iters}

    def set_risk_sub_matrix(self, comparisons: Dict[Tuple[str, str], float]):
        m = build_matrix(RISK_SUB_CRITERIA, comparisons)
        m, iters = repair_matrix(m)
        self.matrices["Risk_Sub"] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.risk_sub_weights = w
        self.cr_results["Risk_Sub"] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                       "grade": grade, "repair_iters": iters}

    def set_return_sub_matrix(self, comparisons: Dict[Tuple[str, str], float]):
        m = build_matrix(RETURN_SUB_CRITERIA, comparisons)
        m, iters = repair_matrix(m)
        self.matrices["Return_Sub"] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.return_sub_weights = w
        self.cr_results["Return_Sub"] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                         "grade": grade, "repair_iters": iters}

    # ── LEVEL 6: Assets under each criterion ─────────────────

    def set_asset_matrix(self, criterion: str,
                          comparisons: Dict[Tuple[str, str], float]):
        """Set asset comparison matrix under a specific criterion."""
        m = build_matrix(ASSET_CLASSES, comparisons)
        m, iters = repair_matrix(m)
        key = f"Assets_{criterion}"
        self.matrices[key] = m
        w = priority_vector(m)
        lam, ci, cr, grade = consistency_ratio(m, w)
        self.asset_weights_by_criterion[criterion] = w
        self.cr_results[key] = {"CR": cr, "CI": ci, "lambda_max": lam,
                                "grade": grade, "repair_iters": iters}

    # ── ANP Feedback Layer ────────────────────────────────────

    def enable_anp(self):
        """Enable ANP dependency layer with real-world interdependencies."""
        self.anp_enabled = True

    def apply_anp_feedback(self):
        """
        Three ANP interdependencies (from implementation guide):
        1. Scenario → adjusts Horizon weights
        2. Actors   → adjusts Criteria weights
        3. Horizon  → adjusts illiquidity preference in assets
        """
        if not self.anp_enabled:
            return

        # 1. Scenario → Horizon
        if self.scenario_weights is not None and self.horizon_weights is not None:
            # Stagflation boosts short-term; Growth boosts long-term
            sf_idx = SCENARIOS.index("Stagflation")
            sg_idx = SCENARIOS.index("Steady Growth")
            sf_weight = self.scenario_weights[sf_idx]
            sg_weight = self.scenario_weights[sg_idx]
            st_idx = HORIZONS.index("Short-term")
            lt_idx = HORIZONS.index("Long-term")
            adj = self.horizon_weights.copy()
            adj[st_idx] += 0.15 * sf_weight
            adj[lt_idx] += 0.10 * sg_weight
            adj /= adj.sum()
            self.anp_feedback["adjusted_horizon"] = adj

        # 2. Actors → Criteria
        if self.actor_weights is not None and self.criteria_weights is not None:
            sp_idx = ACTORS.index("Sponsor")
            bene_idx = ACTORS.index("Beneficiaries")
            sp_w = self.actor_weights[sp_idx]
            bene_w = self.actor_weights[bene_idx]
            liq_idx = CRITERIA.index("Liquidity")
            ret_idx = CRITERIA.index("Return")
            adj = self.criteria_weights.copy()
            adj[liq_idx] += 0.10 * bene_w   # beneficiaries care about liquidity
            adj[ret_idx] += 0.10 * sp_w      # sponsors care about returns
            adj /= adj.sum()
            self.anp_feedback["adjusted_criteria"] = adj

        # 3. Horizon → Illiquidity discount
        if "adjusted_horizon" in self.anp_feedback:
            h = self.anp_feedback["adjusted_horizon"]
            lt_w = h[HORIZONS.index("Long-term")]
            # Private/illiquid assets boosted when long-term dominates
            illiquid = ["Small Stocks", "Real Estate"]
            liquid   = ["Money Market", "Government Bonds"]
            for crit in list(self.asset_weights_by_criterion.keys()):
                adj = self.asset_weights_by_criterion[crit].copy()
                for a in illiquid:
                    idx = ASSET_CLASSES.index(a)
                    adj[idx] *= (1 + 0.2 * lt_w)
                for a in liquid:
                    idx = ASSET_CLASSES.index(a)
                    adj[idx] *= (1 - 0.1 * lt_w)
                adj = np.clip(adj, 0, None)
                adj /= adj.sum()
                self.anp_feedback[f"adjusted_assets_{crit}"] = adj

    # ── HIERARCHICAL SYNTHESIS ────────────────────────────────

    def compute_final_weights(self) -> np.ndarray:
        """
        Aggregate weights down the 6-level hierarchy.
        Returns unnormalized composite weights (then applied to constraints).
        """
        if not self.asset_weights_by_criterion:
            raise ValueError("No asset comparison matrices set.")
        if self.criteria_weights is None:
            raise ValueError("Criteria matrix not set.")

        # Use ANP-adjusted weights if available
        eff_criteria = self.anp_feedback.get("adjusted_criteria", self.criteria_weights)
        n_assets = len(ASSET_CLASSES)
        composite = np.zeros(n_assets)

        for i, crit in enumerate(CRITERIA):
            if crit in self.asset_weights_by_criterion:
                key = f"adjusted_assets_{crit}"
                asset_w = self.anp_feedback.get(key, self.asset_weights_by_criterion[crit])
                composite += eff_criteria[i] * asset_w

        composite /= composite.sum()

        # Dual synthesis
        ideal_base = {}
        for i, crit in enumerate(CRITERIA):
            if crit in self.asset_weights_by_criterion:
                key = f"adjusted_assets_{crit}"
                w = self.anp_feedback.get(key, self.asset_weights_by_criterion[crit])
                best = w.max()
                ideal_base[crit] = w / best if best > 0 else w

        ideal_composite = np.zeros(n_assets)
        for i, crit in enumerate(CRITERIA):
            if crit in ideal_base:
                ideal_composite += eff_criteria[i] * ideal_base[crit]
        ideal_composite /= ideal_composite.sum()

        final, rr_flag, rr_msg = dual_synthesis(composite, ideal_composite)
        self.rank_reversal_flag = rr_flag
        self.rank_reversal_msg  = rr_msg
        self.final_weights = final
        return final

    # ── POLICY CONSTRAINT ENFORCEMENT ────────────────────────

    def apply_constraints(self, weights: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Enforce fund-specific policy min/max constraints.
        Uses iterative clamping and renormalization.
        """
        w = (self.final_weights if weights is None else weights).copy()
        for _ in range(100):
            changed = False
            for i, asset in enumerate(ASSET_CLASSES):
                lo, hi = self.constraints[asset]
                if w[i] < lo:
                    w[i] = lo; changed = True
                elif w[i] > hi:
                    w[i] = hi; changed = True
            w /= w.sum()
            if not changed:
                break
        return w

    # ── DOLLAR ALLOCATION ─────────────────────────────────────

    def dollar_allocation(self, constrained_weights: np.ndarray) -> Dict[str, float]:
        """Convert weights to dollar amounts ($B)."""
        return {
            asset: round(constrained_weights[i] * self.aum_billions, 4)
            for i, asset in enumerate(ASSET_CLASSES)
        }

    # ── FULL RUN ──────────────────────────────────────────────

    def run(self) -> Dict:
        """
        Execute complete AHP computation pipeline:
        1. Compute final weights
        2. Apply ANP feedback
        3. Apply constraints
        4. Dollar allocation
        5. Consistency audit
        """
        if self.anp_enabled:
            self.apply_anp_feedback()

        raw = self.compute_final_weights()
        constrained = self.apply_constraints(raw)
        dollars = self.dollar_allocation(constrained)

        # Overall consistency grade
        grades = [v["grade"] for v in self.cr_results.values()]
        grade_map = {"A": 4, "B": 3, "C": 2, "F": 0}
        avg_grade = sum(grade_map[g] for g in grades) / len(grades) if grades else 0
        if avg_grade >= 3.5:
            overall = "A"
        elif avg_grade >= 2.5:
            overall = "B"
        elif avg_grade >= 1.5:
            overall = "C"
        else:
            overall = "F"

        return {
            "raw_weights":         dict(zip(ASSET_CLASSES, raw.tolist())),
            "constrained_weights": dict(zip(ASSET_CLASSES, constrained.tolist())),
            "dollar_allocation":   dollars,
            "consistency_results": self.cr_results,
            "overall_grade":       overall,
            "rank_reversal_flag":  getattr(self, "rank_reversal_flag", False),
            "rank_reversal_msg":   getattr(self, "rank_reversal_msg", ""),
            "anp_applied":         self.anp_enabled,
        }

    # ── MONTE CARLO ROBUSTNESS ────────────────────────────────

    def run_monte_carlo(self, n_simulations: int = 1000,
                        noise_pct: float = 0.15) -> Dict:
        """
        Perturb each pairwise matrix by ±noise_pct and re-run synthesis.
        Returns mean, std, P5, P95 for each asset class.
        """
        if self.final_weights is None:
            self.compute_final_weights()

        sim_weights = np.zeros((n_simulations, len(ASSET_CLASSES)))

        for sim in range(n_simulations):
            perturbed_asset_w = {}
            for crit, base_w in self.asset_weights_by_criterion.items():
                noise = 1.0 + np.random.uniform(-noise_pct, noise_pct, len(base_w))
                pw = base_w * noise
                pw = np.clip(pw, 0, None)
                if pw.sum() > 0:
                    pw /= pw.sum()
                perturbed_asset_w[crit] = pw

            crit_noise = 1.0 + np.random.uniform(
                -noise_pct / 2, noise_pct / 2, len(CRITERIA))
            eff_crit = self.criteria_weights * crit_noise
            eff_crit /= eff_crit.sum()

            composite = np.zeros(len(ASSET_CLASSES))
            for i, crit in enumerate(CRITERIA):
                if crit in perturbed_asset_w:
                    composite += eff_crit[i] * perturbed_asset_w[crit]
            if composite.sum() > 0:
                composite /= composite.sum()

            constrained = self.apply_constraints(composite)
            sim_weights[sim] = constrained

        mean_w = sim_weights.mean(axis=0)
        std_w  = sim_weights.std(axis=0)
        p5_w   = np.percentile(sim_weights, 5, axis=0)
        p95_w  = np.percentile(sim_weights, 95, axis=0)

        # Sensitivity rating: HIGH if std/mean > 0.20, MEDIUM if 0.10–0.20, LOW <0.10
        def sensitivity(s, m):
            r = s / m if m > 0 else 0
            return "HIGH" if r > 0.20 else ("MEDIUM" if r > 0.10 else "LOW")

        self.mc_results = {
            asset: {
                "mean":        round(float(mean_w[i]), 4),
                "std":         round(float(std_w[i]), 4),
                "P5":          round(float(p5_w[i]), 4),
                "P95":         round(float(p95_w[i]), 4),
                "sensitivity": sensitivity(std_w[i], mean_w[i]),
            }
            for i, asset in enumerate(ASSET_CLASSES)
        }
        return self.mc_results

    # ── SENSITIVITY ANALYSIS ──────────────────────────────────

    def sensitivity_analysis(self, criterion_to_vary: str,
                              steps: int = 9) -> Dict:
        """
        Vary one criterion's weight from near-0 to near-1,
        report impact on each asset class allocation.
        """
        if self.criteria_weights is None:
            raise ValueError("Criteria not set.")
        idx = CRITERIA.index(criterion_to_vary)
        sweep_vals = np.linspace(0.05, 0.95, steps)
        results = {asset: [] for asset in ASSET_CLASSES}

        for val in sweep_vals:
            adj_crit = self.criteria_weights.copy()
            adj_crit[idx] = val
            remaining = 1.0 - val
            other_sum = sum(adj_crit[j] for j in range(len(CRITERIA)) if j != idx)
            for j in range(len(CRITERIA)):
                if j != idx:
                    adj_crit[j] = adj_crit[j] / other_sum * remaining if other_sum > 0 else remaining / 3
            adj_crit /= adj_crit.sum()

            composite = np.zeros(len(ASSET_CLASSES))
            for i, crit in enumerate(CRITERIA):
                if crit in self.asset_weights_by_criterion:
                    composite += adj_crit[i] * self.asset_weights_by_criterion[crit]
            composite /= composite.sum()
            constrained = self.apply_constraints(composite)
            for j, asset in enumerate(ASSET_CLASSES):
                results[asset].append(round(float(constrained[j]), 4))

        return {"sweep_values": sweep_vals.tolist(), "allocations": results}


# ─────────────────────────────────────────────────────────────
# DEFAULT MODEL — Liberty Bell Pension Fund
# Based on Khaksari et al. (1989) calibrated inputs
# ─────────────────────────────────────────────────────────────

def build_liberty_bell_model() -> AHPModel:
    """
    Instantiate the Liberty Bell model with calibrated pairwise matrices
    from the 1989 paper, ready to run.
    """
    model = AHPModel("Liberty Bell Defined Benefit Pension Fund", aum_billions=3.2)

    # Level 2 — Actors
    model.set_actor_matrix({
        ("Sponsor", "Beneficiaries"):      4,
        ("Sponsor", "Portfolio Manager"):  5,
        ("Beneficiaries", "Portfolio Manager"): 3,
    })

    # Level 3 — Horizon
    model.set_horizon_matrix({
        ("Short-term", "Medium-term"):  1/3,
        ("Short-term", "Long-term"):    1/5,
        ("Medium-term", "Long-term"):   1/3,
    })

    # Level 4 — Scenarios (probability-weighted)
    model.set_scenario_matrix({
        ("Bull Market", "Stagflation"):   3,
        ("Bull Market", "Deflation"):     5,
        ("Bull Market", "Steady Growth"): 1/2,
        ("Stagflation", "Deflation"):     3,
        ("Stagflation", "Steady Growth"): 1/3,
        ("Deflation", "Steady Growth"):   1/5,
    })

    # Level 5 — Criteria
    model.set_criteria_matrix({
        ("Return", "Risk"):          2,
        ("Return", "Liquidity"):     5,
        ("Return", "Diversification"): 3,
        ("Risk", "Liquidity"):       3,
        ("Risk", "Diversification"): 2,
        ("Liquidity", "Diversification"): 1/2,
    })

    # Level 5 — Risk sub-criteria
    model.set_risk_sub_matrix({
        ("Beta", "Volatility"):          1,
        ("Beta", "Max Drawdown"):        2,
        ("Beta", "Liquidity Risk"):      3,
        ("Volatility", "Max Drawdown"):  2,
        ("Volatility", "Liquidity Risk"): 3,
        ("Max Drawdown", "Liquidity Risk"): 2,
    })

    # Level 5 — Return sub-criteria
    model.set_return_sub_matrix({
        ("Expected Return", "Dividend Yield"):     3,
        ("Expected Return", "Growth Potential"):   2,
        ("Dividend Yield", "Growth Potential"):    1/2,
    })

    # Level 6 — Assets under Return
    model.set_asset_matrix("Return", {
        ("Small Stocks", "Large Stocks"):        2,
        ("Small Stocks", "Corporate Bonds"):     5,
        ("Small Stocks", "Government Bonds"):    7,
        ("Small Stocks", "Real Estate"):         3,
        ("Small Stocks", "Money Market"):        9,
        ("Small Stocks", "Commodities"):         3,
        ("Large Stocks", "Corporate Bonds"):     3,
        ("Large Stocks", "Government Bonds"):    5,
        ("Large Stocks", "Real Estate"):         2,
        ("Large Stocks", "Money Market"):        7,
        ("Large Stocks", "Commodities"):         2,
        ("Corporate Bonds", "Government Bonds"): 2,
        ("Corporate Bonds", "Real Estate"):      1/2,
        ("Corporate Bonds", "Money Market"):     4,
        ("Corporate Bonds", "Commodities"):      1/2,
        ("Government Bonds", "Real Estate"):     1/3,
        ("Government Bonds", "Money Market"):    3,
        ("Government Bonds", "Commodities"):     1/3,
        ("Real Estate", "Money Market"):         5,
        ("Real Estate", "Commodities"):          1,
        ("Money Market", "Commodities"):         1/4,
    })

    # Level 6 — Assets under Risk (inverse: lower risk = higher weight)
    model.set_asset_matrix("Risk", {
        ("Small Stocks", "Large Stocks"):        1/2,
        ("Small Stocks", "Corporate Bonds"):     1/5,
        ("Small Stocks", "Government Bonds"):    1/7,
        ("Small Stocks", "Real Estate"):         1/3,
        ("Small Stocks", "Money Market"):        1/9,
        ("Small Stocks", "Commodities"):         1/3,
        ("Large Stocks", "Corporate Bonds"):     1/3,
        ("Large Stocks", "Government Bonds"):    1/5,
        ("Large Stocks", "Real Estate"):         1/2,
        ("Large Stocks", "Money Market"):        1/7,
        ("Large Stocks", "Commodities"):         1/2,
        ("Corporate Bonds", "Government Bonds"): 1/2,
        ("Corporate Bonds", "Real Estate"):      2,
        ("Corporate Bonds", "Money Market"):     1/3,
        ("Corporate Bonds", "Commodities"):      2,
        ("Government Bonds", "Real Estate"):     3,
        ("Government Bonds", "Money Market"):    1/2,
        ("Government Bonds", "Commodities"):     4,
        ("Real Estate", "Money Market"):         1/4,
        ("Real Estate", "Commodities"):          1,
        ("Money Market", "Commodities"):         5,
    })

    # Level 6 — Assets under Liquidity
    model.set_asset_matrix("Liquidity", {
        ("Small Stocks", "Large Stocks"):        1/3,
        ("Small Stocks", "Corporate Bonds"):     1/2,
        ("Small Stocks", "Government Bonds"):    1/4,
        ("Small Stocks", "Real Estate"):         3,
        ("Small Stocks", "Money Market"):        1/5,
        ("Small Stocks", "Commodities"):         2,
        ("Large Stocks", "Corporate Bonds"):     2,
        ("Large Stocks", "Government Bonds"):    1/2,
        ("Large Stocks", "Real Estate"):         5,
        ("Large Stocks", "Money Market"):        1/3,
        ("Large Stocks", "Commodities"):         4,
        ("Corporate Bonds", "Government Bonds"): 1/3,
        ("Corporate Bonds", "Real Estate"):      4,
        ("Corporate Bonds", "Money Market"):     1/4,
        ("Corporate Bonds", "Commodities"):      2,
        ("Government Bonds", "Real Estate"):     7,
        ("Government Bonds", "Money Market"):    1/2,
        ("Government Bonds", "Commodities"):     5,
        ("Real Estate", "Money Market"):         1/7,
        ("Real Estate", "Commodities"):          1/3,
        ("Money Market", "Commodities"):         4,
    })

    # Level 6 — Assets under Diversification (correlation-based)
    model.set_asset_matrix("Diversification", {
        ("Small Stocks", "Large Stocks"):        1/2,
        ("Small Stocks", "Corporate Bonds"):     3,
        ("Small Stocks", "Government Bonds"):    4,
        ("Small Stocks", "Real Estate"):         2,
        ("Small Stocks", "Money Market"):        4,
        ("Small Stocks", "Commodities"):         2,
        ("Large Stocks", "Corporate Bonds"):     4,
        ("Large Stocks", "Government Bonds"):    5,
        ("Large Stocks", "Real Estate"):         3,
        ("Large Stocks", "Money Market"):        5,
        ("Large Stocks", "Commodities"):         3,
        ("Corporate Bonds", "Government Bonds"): 1/2,
        ("Corporate Bonds", "Real Estate"):      1/2,
        ("Corporate Bonds", "Money Market"):     1/2,
        ("Corporate Bonds", "Commodities"):      1/2,
        ("Government Bonds", "Real Estate"):     1/2,
        ("Government Bonds", "Money Market"):    1/3,
        ("Government Bonds", "Commodities"):     1/3,
        ("Real Estate", "Money Market"):         1/2,
        ("Real Estate", "Commodities"):          1,
        ("Money Market", "Commodities"):         2,
    })

    model.enable_anp()
    return model


# ─────────────────────────────────────────────────────────────
# PRACTITIONER PROFILES + STRESS TEST ENGINE
# ─────────────────────────────────────────────────────────────

PRACTITIONER_PROFILES: Dict[str, Dict] = {
    "Conservative DB Fund": {
        "description": (
            "Underfunded US public pension (~70% funded ratio). Capital preservation over "
            "growth. Liability-driven allocation — risk management dominates return seeking."
        ),
        "archetype": "Typical underfunded state pension (e.g., NYCERS 2022-style)",
        "priority": "Risk > Liquidity > Return > Diversification",
        "criteria": {
            ("Return", "Risk"):             0.5,
            ("Return", "Liquidity"):        3.0,
            ("Return", "Diversification"):  2.0,
            ("Risk", "Liquidity"):          4.0,
            ("Risk", "Diversification"):    3.0,
            ("Liquidity", "Diversification"): 1.0,
        },
    },
    "Growth-Oriented Endowment": {
        "description": (
            "Long-horizon sovereign/endowment fund targeting real 7%+ return. "
            "Illiquidity premium accepted. Diversification secondary to absolute return."
        ),
        "archetype": "Yale Endowment / CPPIB / Norges Bank GPFG style",
        "priority": "Return >> Liquidity (illiquid assets tolerated)",
        "criteria": {
            ("Return", "Risk"):             4.0,
            ("Return", "Liquidity"):        7.0,
            ("Return", "Diversification"):  3.0,
            ("Risk", "Liquidity"):          5.0,
            ("Risk", "Diversification"):    2.0,
            ("Liquidity", "Diversification"): 0.33,
        },
    },
    "LDI / Immunization": {
        "description": (
            "UK/European liability-driven investment. Duration-matched government bonds "
            "anchor the portfolio. Risk tolerance very low, liability matching paramount."
        ),
        "archetype": "Ontario Teachers / ABP Netherlands / UK DB scheme",
        "priority": "Risk ≈ Liquidity >> Return (liability matching)",
        "criteria": {
            ("Return", "Risk"):             0.33,
            ("Return", "Liquidity"):        2.0,
            ("Return", "Diversification"):  1.0,
            ("Risk", "Liquidity"):          5.0,
            ("Risk", "Diversification"):    4.0,
            ("Liquidity", "Diversification"): 2.0,
        },
    },
    "Risk Parity": {
        "description": (
            "Equal risk contribution across asset classes via leverage. Diversification "
            "is the dominant criterion. No asset concentrations. All-weather design."
        ),
        "archetype": "Bridgewater All-Weather / AQR style",
        "priority": "Diversification > Risk ≈ Return (leverage neutral)",
        "criteria": {
            ("Return", "Risk"):             1.0,
            ("Return", "Liquidity"):        3.0,
            ("Return", "Diversification"):  0.33,
            ("Risk", "Liquidity"):          3.0,
            ("Risk", "Diversification"):    0.33,
            ("Liquidity", "Diversification"): 0.20,
        },
    },
    "Aggressive Growth": {
        "description": (
            "Maximum return orientation. Equity-heavy, concentration tolerated. "
            "Long investment horizon (20+ years). Liquidity and downside risk de-prioritized."
        ),
        "archetype": "Norway GPFG / GIC Singapore / Abu Dhabi Investment Authority",
        "priority": "Return >> everything else",
        "criteria": {
            ("Return", "Risk"):             5.0,
            ("Return", "Liquidity"):        9.0,
            ("Return", "Diversification"):  5.0,
            ("Risk", "Liquidity"):          3.0,
            ("Risk", "Diversification"):    2.0,
            ("Liquidity", "Diversification"): 0.5,
        },
    },
}

# Saaty 1-9 scale discrete values for UI dropdowns
SAATY_SCALE_OPTIONS = [
    (9,     "9 — Extreme dominance"),
    (8,     "8"),
    (7,     "7 — Very strong"),
    (6,     "6"),
    (5,     "5 — Strong dominance"),
    (4,     "4"),
    (3,     "3 — Moderate dominance"),
    (2,     "2"),
    (1,     "1 — Equal importance"),
    (1/2,   "1/2"),
    (1/3,   "1/3 — Moderate inverse"),
    (1/4,   "1/4"),
    (1/5,   "1/5 — Strong inverse"),
    (1/6,   "1/6"),
    (1/7,   "1/7 — Very strong inverse"),
    (1/8,   "1/8"),
    (1/9,   "1/9 — Extreme inverse"),
]


def _saaty_display(val: float) -> str:
    """Convert numeric Saaty value to string label."""
    if val >= 8.5:   return "9"
    if val >= 7.5:   return "8"
    if val >= 6.5:   return "7"
    if val >= 5.5:   return "6"
    if val >= 4.5:   return "5"
    if val >= 3.5:   return "4"
    if val >= 2.5:   return "3"
    if val >= 1.5:   return "2"
    if val >= 0.85:  return "1"
    if val >= 0.58:  return "1/2"
    if val >= 0.40:  return "1/3"
    if val >= 0.27:  return "1/4"
    if val >= 0.20:  return "1/5"
    if val >= 0.155: return "1/6"
    if val >= 0.125: return "1/7"
    if val >= 0.105: return "1/8"
    return "1/9"


_CRITERIA_PAIRS = [
    ("Return", "Risk"),
    ("Return", "Liquidity"),
    ("Return", "Diversification"),
    ("Risk", "Liquidity"),
    ("Risk", "Diversification"),
    ("Liquidity", "Diversification"),
]

_SAATY_VALS = [1/9, 1/8, 1/7, 1/6, 1/5, 1/4, 1/3, 1/2, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def run_stress_test(
    custom_criteria: Dict[Tuple[str, str], float],
    base_model: Optional[AHPModel] = None,
) -> Dict:
    """
    Practitioner stress-test: compare base Liberty Bell model vs custom criteria weights.

    custom_criteria: upper-triangle only, e.g. {("Return","Risk"): 3.0, ...}
    Returns comprehensive comparison: delta allocations, CR audit, per-pair sensitivity.
    """
    if base_model is None:
        base_model = build_liberty_bell_model()

    base_result  = base_model.run()
    base_weights = base_result["constrained_weights"]

    # ── Build custom model reusing base asset matrices ────────
    custom = AHPModel("Practitioner Stress Test", aum_billions=base_model.aum_billions)

    # Copy level 2-4 matrices verbatim
    for key in ("Actors", "Horizon", "Scenarios"):
        if key in base_model.matrices:
            custom.matrices[key] = base_model.matrices[key].copy()
    if base_model.actor_weights    is not None: custom.actor_weights    = base_model.actor_weights.copy()
    if base_model.horizon_weights  is not None: custom.horizon_weights  = base_model.horizon_weights.copy()
    if base_model.scenario_weights is not None: custom.scenario_weights = base_model.scenario_weights.copy()
    for k in ("Actors", "Horizon", "Scenarios"):
        if k in base_model.cr_results:
            custom.cr_results[k] = base_model.cr_results[k].copy()

    # Apply custom criteria
    custom.set_criteria_matrix(custom_criteria)
    custom.set_risk_sub_matrix({
        ("Beta", "Volatility"): 1, ("Beta", "Max Drawdown"): 2,
        ("Beta", "Liquidity Risk"): 3, ("Volatility", "Max Drawdown"): 2,
        ("Volatility", "Liquidity Risk"): 3, ("Max Drawdown", "Liquidity Risk"): 2,
    })
    custom.set_return_sub_matrix({
        ("Expected Return", "Dividend Yield"): 3,
        ("Expected Return", "Growth Potential"): 2,
        ("Dividend Yield", "Growth Potential"): 1/2,
    })

    # Reuse base asset weight matrices (unchanged by criteria adjustment)
    for crit, w in base_model.asset_weights_by_criterion.items():
        custom.asset_weights_by_criterion[crit] = w.copy()
        key = f"Assets_{crit}"
        if key in base_model.matrices:
            custom.matrices[key]     = base_model.matrices[key].copy()
            custom.cr_results[key]   = base_model.cr_results[key].copy()

    custom.enable_anp()
    custom_result  = custom.run()
    custom_weights = custom_result["constrained_weights"]

    # Monte Carlo for custom model (fast: 400 sims)
    mc = custom.run_monte_carlo(n_simulations=400)

    # ── Delta & criteria comparison ───────────────────────────
    deltas   = {a: round(custom_weights[a] - base_weights.get(a, 0), 4) for a in ASSET_CLASSES}
    base_cw  = (dict(zip(CRITERIA, base_model.criteria_weights.tolist()))
                if base_model.criteria_weights is not None else {})
    cust_cw  = dict(zip(CRITERIA, custom.criteria_weights.tolist()))
    crit_delta = {c: round(cust_cw.get(c, 0) - base_cw.get(c, 0), 4) for c in CRITERIA}

    # ── Per-pair ±1 Saaty-step sensitivity ───────────────────
    sensitivity_map: Dict[str, Dict] = {}
    for pair in _CRITERIA_PAIRS:
        cur_val = float(custom_criteria.get(pair, 1.0))
        cur_idx = min(range(len(_SAATY_VALS)), key=lambda i: abs(_SAATY_VALS[i] - cur_val))
        impacts: Dict[str, Dict] = {}
        for offset, label in [(+1, "up_one_step"), (-1, "down_one_step")]:
            test_idx = max(0, min(len(_SAATY_VALS) - 1, cur_idx + offset))
            test_val = _SAATY_VALS[test_idx]
            test_crit = {**custom_criteria, pair: test_val}
            try:
                m = build_matrix(CRITERIA, test_crit)
                m, _ = repair_matrix(m)
                w = priority_vector(m)
                _, _, cr_t, gr_t = consistency_ratio(m, w)
                comp = np.zeros(len(ASSET_CLASSES))
                for i, c in enumerate(CRITERIA):
                    if c in custom.asset_weights_by_criterion:
                        comp += w[i] * custom.asset_weights_by_criterion[c]
                comp = comp / comp.sum() if comp.sum() > 0 else comp
                constrained = custom.apply_constraints(comp)
                cur_arr = np.array([custom_weights[a] for a in ASSET_CLASSES])
                diff_arr = constrained - cur_arr
                max_ai = int(np.argmax(np.abs(diff_arr)))
                impacts[label] = {
                    "saaty_display": _saaty_display(test_val),
                    "numeric":       round(test_val, 4),
                    "cr":            round(float(cr_t), 4),
                    "grade":         gr_t,
                    "max_shift_asset": ASSET_CLASSES[max_ai],
                    "max_shift_pct":   round(float(diff_arr[max_ai]) * 100, 2),
                    "all_shifts":      {ASSET_CLASSES[i]: round(float(diff_arr[i]) * 100, 2)
                                        for i in range(len(ASSET_CLASSES))},
                }
            except Exception:
                pass
        sensitivity_map[f"{pair[0]} vs {pair[1]}"] = {
            "current_numeric":  round(cur_val, 4),
            "current_display":  _saaty_display(cur_val),
            "impacts":          impacts,
        }

    # ── Consistency check for custom criteria matrix ──────────
    cr_info = custom.cr_results.get("Criteria", {})
    cr_pass = cr_info.get("CR", 1.0) <= 0.10

    return {
        "base_weights":               base_weights,
        "custom_weights":             custom_weights,
        "deltas":                     deltas,
        "base_criteria_weights":      base_cw,
        "custom_criteria_weights":    cust_cw,
        "criteria_delta":             crit_delta,
        "criteria_cr":                round(cr_info.get("CR", 0), 4),
        "criteria_ci":                round(cr_info.get("CI", 0), 4),
        "criteria_lambda_max":        round(cr_info.get("lambda_max", 0), 4),
        "criteria_grade":             cr_info.get("grade", "?"),
        "cr_pass":                    cr_pass,
        "rank_reversal":              custom_result.get("rank_reversal_flag", False),
        "rank_reversal_msg":          custom_result.get("rank_reversal_msg", ""),
        "mc_summary":                 mc,
        "sensitivity_map":            sensitivity_map,
        "custom_overall_grade":       custom_result.get("overall_grade", "?"),
        "n_assets_shifted_gt1pct":    sum(1 for d in deltas.values() if abs(d) > 0.01),
        "largest_shift_asset":        max(deltas, key=lambda a: abs(deltas[a])),
        "largest_shift_pct":          round(max(abs(v) for v in deltas.values()) * 100, 1),
    }


# ─────────────────────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    model = build_liberty_bell_model()
    result = model.run()
    mc     = model.run_monte_carlo(n_simulations=1000)

    print(f"\n{'='*60}")
    print(f"  {model.fund_name}  |  AUM: ${model.aum_billions}B")
    print(f"{'='*60}")
    print(f"\nOverall Consistency Grade: {result['overall_grade']}")
    print(f"Rank Reversal: {result['rank_reversal_flag']} — {result['rank_reversal_msg']}")
    print(f"\n{'Asset Class':<22} {'Weight':>7}  {'$B':>8}  {'MC Mean':>8}  {'Sensitivity'}")
    print("-" * 65)
    for asset in ASSET_CLASSES:
        w  = result["constrained_weights"][asset]
        d  = result["dollar_allocation"][asset]
        mc_m = mc[asset]["mean"]
        sens = mc[asset]["sensitivity"]
        print(f"{asset:<22} {w:>7.3f}  ${d:>7.4f}B  {mc_m:>8.4f}  {sens}")
    print(f"\nConsistency Ratios:")
    for name, cr_info in result["consistency_results"].items():
        print(f"  {name:<20} CR={cr_info['CR']:.4f}  Grade={cr_info['grade']}")
