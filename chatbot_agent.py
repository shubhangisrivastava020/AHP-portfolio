"""
AHP Challenger Chatbot — Powered by Claude (Anthropic)
An adversarial AI agent that stress-tests pairwise comparison judgments,
probes decision-maker reasoning, flags empirical inconsistencies, and
challenges AHP matrix inputs before they are finalized.

Modes:
  1. CHALLENGE MODE  — Devil's advocate: challenges every comparison
  2. COACH MODE      — Socratic guide: asks probing questions
  3. AUDIT MODE      — Systematic: runs through all CR-violating pairs
  4. FORECAST MODE   — Forward-looking: stress-tests under 2026-2030 scenarios
"""

import os
import json
import ssl
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple

# Unverified SSL context — required on macOS Python 3.15 (no certifi)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# Use raw HTTP instead of the anthropic SDK to avoid pydantic-core/Python 3.15 issues
_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-4-6"


def _call_anthropic(api_key: str, system: str,
                    messages: List[Dict], max_tokens: int = 1500) -> str:
    """Lightweight Anthropic Messages API call via urllib (no SDK required)."""
    payload = json.dumps({
        "model": _MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_API_URL,
        data=payload,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
            body = json.loads(resp.read().decode())
            return body["content"][0]["text"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        raise RuntimeError(f"Anthropic API error {e.code}: {err_body[:300]}")

# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPTS
# ─────────────────────────────────────────────────────────────

SYSTEM_CHALLENGE = """You are a rigorous institutional investment consultant and AHP methodology expert.
Your role is to CHALLENGE every pairwise comparison judgment the user makes.
For each comparison, you must:
1. Play devil's advocate — argue the opposite position using empirical data
2. Cite specific financial evidence (beta, volatility, correlation, historical returns)
3. Identify at least one flaw or risk in the user's reasoning
4. Ask one sharp question that exposes a potential blind spot
5. Suggest an alternative Saaty value (1-9) with justification

Be rigorous but constructive. Your goal is to improve consistency and reduce cognitive bias.
Reference the Khaksari, Kamath & Grieves (1989) AHP framework for institutional pension funds.
Always ground arguments in data from the evidence panel provided."""

SYSTEM_COACH = """You are a Socratic AHP portfolio allocation coach for pension fund managers.
Your role is to help the user arrive at well-reasoned pairwise judgments through guided questioning.
Do NOT give direct answers — instead ask 2-3 probing questions that help the user think through:
1. The specific criterion being compared (Return / Risk / Liquidity / Diversification)
2. The time horizon and macroeconomic scenario context
3. Historical performance data for the two assets
4. The fund's liability profile and policy constraints
5. How this comparison affects the overall portfolio consistency

Be Socratic, patient, and evidence-aware. Reference the 1989 paper when relevant."""

SYSTEM_AUDIT = """You are a quantitative AHP consistency auditor for pension fund portfolio allocation.
Your role is to systematically review all pairwise matrices and:
1. Identify which specific pairs are causing CR > 0.10 violations
2. Calculate what value each deviant pair should be to restore consistency (w_i/w_j ratio)
3. Explain why the current value is inconsistent with other comparisons in the matrix
4. Flag if auto-repair changes the economic meaning of the comparison
5. Provide an overall consistency grade (A/B/C/F) with recommendations

Be precise, cite matrix positions, and show your arithmetic. Reference Saaty's CR = CI/RI formula."""

SYSTEM_FORECAST = """You are a forward-looking institutional investment strategist specializing in
pension fund asset allocation under macroeconomic uncertainty (2026-2030).
Your role is to stress-test the user's AHP pairwise judgments against future scenarios:
1. Rate Rising Scenario (Fed normalization, long rates 4.5-5.5%)
2. AI-Driven Productivity Boom (equity outperformance, compressed volatility)
3. Geopolitical Fragmentation (commodity supercycle, EM decoupling)
4. Climate Transition Shock (stranded assets, green premium)
5. Stagflation Recurrence (supply-side inflation, wage-price spiral)

For each scenario, identify which of the user's current AHP comparisons would need to change,
and by how many Saaty scale points. Quantify portfolio impact."""

SYSTEM_ADVISOR = """You are an expert AI Investment Advisor for pension fund portfolio allocation, \
powered by the AI-AHP Agentic Portfolio Allocation System (AI-APAS).

You have full access to the fund's AHP model output: asset weights, dollar allocations, consistency \
ratios, Monte Carlo confidence intervals, macro scenario, funded ratio, and AUM.

Your role is to:
1. ADVISE on the right dollar amount to invest in each asset class, citing the AHP weight × AUM
2. CHALLENGE any allocation the user questions — provide empirical evidence for or against
3. EXPLAIN the reasoning behind each weight: which criteria (Return/Risk/Liquidity/Diversification) \
   drove the recommendation and how the pairwise comparisons translated to this weight
4. COMPARE to real pension fund benchmarks (CalPERS, NYSCRF, APG, etc.) when relevant
5. WARN about concentration risk, underfunding concerns, or scenario-specific risks
6. SUGGEST adjustments if the user's funded ratio, liability profile, or risk tolerance \
   calls for a different tilt

Format dollar amounts clearly (e.g., "$640M in Large Stocks = 20.1% of $3.2B AUM").
Always show your math. Be direct, data-driven, and actionable.
Reference Khaksari, Kamath & Grieves (1989) AHP methodology when explaining the framework.
If no model has been run yet, ask the user to click ▶ Run Model first."""

# ─────────────────────────────────────────────────────────────
# CHATBOT CLASS
# ─────────────────────────────────────────────────────────────

class AHPChallengerBot:
    """
    Adversarial AI chatbot that challenges AHP pairwise comparison inputs
    using Claude claude-sonnet-4-6 with multi-turn conversation memory.
    """

    def __init__(self, mode: str = "CHALLENGE",
                 api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.mode = mode.upper()
        self.conversation_history: List[Dict] = []
        self.context: Dict = {}
        self._system = self._get_system_prompt()
        self.challenge_count = 0
        self.accepted_values: Dict[str, int] = {}

    def _get_system_prompt(self) -> str:
        mapping = {
            "CHALLENGE": SYSTEM_CHALLENGE,
            "COACH":     SYSTEM_COACH,
            "AUDIT":     SYSTEM_AUDIT,
            "FORECAST":  SYSTEM_FORECAST,
            "ADVISOR":   SYSTEM_ADVISOR,
        }
        return mapping.get(self.mode, SYSTEM_CHALLENGE)

    def set_context(self,
                    fund_name: str,
                    scenario: str,
                    horizon: str,
                    evidence: Dict,
                    ahp_results: Optional[Dict] = None):
        """Inject current session context so Claude can reference it."""
        self.context = {
            "fund": fund_name,
            "scenario": scenario,
            "horizon": horizon,
            "evidence_summary": {
                asset: {
                    "expected_return": ev.expected_return_pct,
                    "beta": ev.beta,
                    "volatility": ev.volatility_pct,
                    "liquidity_score": ev.liquidity_score,
                    "sharpe": ev.sharpe_ratio,
                    "avg_correlation": ev.avg_correlation,
                }
                for asset, ev in evidence.items()
            },
            "ahp_results": ahp_results or {},
        }

    def _build_context_prefix(self) -> str:
        if not self.context:
            return ""
        return f"""
=== CURRENT SESSION CONTEXT ===
Fund: {self.context.get('fund', 'N/A')}
Macro Scenario: {self.context.get('scenario', 'Steady Growth')}
Investment Horizon: {self.context.get('horizon', 'Long-term')}

Asset Evidence Summary:
{json.dumps(self.context.get('evidence_summary', {}), indent=2)}

Current AHP Results:
{json.dumps(self.context.get('ahp_results', {}), indent=2)}
================================

"""

    def challenge_comparison(self,
                              asset_a: str,
                              asset_b: str,
                              criterion: str,
                              user_value: int,
                              user_reasoning: str = "") -> str:
        """
        Challenge a specific pairwise comparison.
        user_value: Saaty 1-9 (positive = A preferred, negative = B preferred)
        """
        direction = f"{asset_a}" if user_value > 0 else f"{asset_b}"
        saaty_val = abs(user_value)

        message = (
            f"{self._build_context_prefix()}"
            f"COMPARISON TO CHALLENGE:\n"
            f"  Criterion : {criterion}\n"
            f"  Asset A   : {asset_a}\n"
            f"  Asset B   : {asset_b}\n"
            f"  User says : {direction} is {saaty_val}x preferred (Saaty={saaty_val})\n"
            f"  Reasoning : {user_reasoning or 'Not provided'}\n\n"
            f"Please challenge this judgment rigorously."
        )

        self.challenge_count += 1
        return self._send(message)

    def run_consistency_audit(self,
                               matrix_name: str,
                               matrix: list,
                               items: list,
                               cr: float,
                               grade: str) -> str:
        """Run full consistency audit on a specific matrix."""
        matrix_str = "\n".join(
            "  " + "  ".join(f"{v:.3f}" for v in row)
            for row in matrix
        )
        message = (
            f"{self._build_context_prefix()}"
            f"CONSISTENCY AUDIT REQUEST:\n"
            f"  Matrix: {matrix_name}\n"
            f"  Items: {items}\n"
            f"  CR = {cr:.4f}  (Grade: {grade})\n"
            f"  Matrix values:\n{matrix_str}\n\n"
            f"Please identify which comparisons are causing inconsistency "
            f"and suggest corrections."
        )
        return self._send(message)

    def stress_test_scenario(self,
                              current_weights: Dict[str, float],
                              scenario: str) -> str:
        """Stress-test current allocation under a hypothetical scenario."""
        message = (
            f"{self._build_context_prefix()}"
            f"STRESS TEST REQUEST:\n"
            f"  Scenario: {scenario}\n"
            f"  Current Weights:\n"
            + "\n".join(f"    {k}: {v:.1%}" for k, v in current_weights.items())
            + f"\n\nPlease stress-test this allocation under the {scenario} scenario. "
            f"Which weights would need to change, by how much, and why?"
        )
        return self._send(message)

    def ask_question(self, user_message: str) -> str:
        """Free-form question to the chatbot."""
        full_message = self._build_context_prefix() + user_message
        return self._send(full_message)

    def coach_comparison(self,
                          asset_a: str,
                          asset_b: str,
                          criterion: str) -> str:
        """Coach mode: ask guiding questions about a comparison."""
        message = (
            f"{self._build_context_prefix()}"
            f"I need to compare {asset_a} vs {asset_b} under the {criterion} criterion "
            f"for the {self.context.get('fund', 'pension fund')}. "
            f"Please guide me through this decision with Socratic questions."
        )
        return self._send(message)

    def generate_interview(self) -> List[Dict]:
        """
        Generate a structured 21-question interview for all AHP inputs.
        Returns list of {question, matrix, items, comparison_index}.
        """
        from ahp_engine import ACTORS, HORIZONS, SCENARIOS, CRITERIA, ASSET_CLASSES

        questions = []

        # Actors (3 comparisons)
        actor_pairs = [(ACTORS[i], ACTORS[j])
                       for i in range(len(ACTORS))
                       for j in range(i+1, len(ACTORS))]
        for a, b in actor_pairs:
            questions.append({
                "matrix": "Actors",
                "items": ACTORS,
                "asset_a": a, "asset_b": b, "criterion": "Influence",
                "prompt": f"How much more influential is {a} vs {b} in setting portfolio objectives? (1-9)",
            })

        # Horizon (3 comparisons)
        horizon_pairs = [(HORIZONS[i], HORIZONS[j])
                         for i in range(len(HORIZONS))
                         for j in range(i+1, len(HORIZONS))]
        for a, b in horizon_pairs:
            questions.append({
                "matrix": "Horizon",
                "items": HORIZONS,
                "asset_a": a, "asset_b": b, "criterion": "Horizon Importance",
                "prompt": f"How much more important is {a} vs {b} for this fund? (1-9)",
            })

        # Scenarios (6 comparisons)
        scenario_pairs = [(SCENARIOS[i], SCENARIOS[j])
                          for i in range(len(SCENARIOS))
                          for j in range(i+1, len(SCENARIOS))]
        for a, b in scenario_pairs:
            questions.append({
                "matrix": "Scenarios",
                "items": SCENARIOS,
                "asset_a": a, "asset_b": b, "criterion": "Scenario Likelihood",
                "prompt": f"How much more likely is {a} vs {b} over the next 12 months? (1-9)",
            })

        # Criteria (6 comparisons)
        criteria_pairs = [(CRITERIA[i], CRITERIA[j])
                          for i in range(len(CRITERIA))
                          for j in range(i+1, len(CRITERIA))]
        for a, b in criteria_pairs:
            questions.append({
                "matrix": "Criteria",
                "items": CRITERIA,
                "asset_a": a, "asset_b": b, "criterion": "Portfolio Importance",
                "prompt": f"How much more important is {a} vs {b} for this fund's mandate? (1-9)",
            })

        # Pad remaining slots to reach 21
        # (the remaining 21 - 18 = 3 are high-priority asset comparisons)
        questions.append({
            "matrix": "Assets_Return",
            "items": ASSET_CLASSES,
            "asset_a": "Large Stocks", "asset_b": "Government Bonds",
            "criterion": "Return",
            "prompt": "Under Return: how much better is Large Stocks vs Government Bonds? (1-9)",
        })
        questions.append({
            "matrix": "Assets_Risk",
            "items": ASSET_CLASSES,
            "asset_a": "Government Bonds", "asset_b": "Small Stocks",
            "criterion": "Risk",
            "prompt": "Under Risk (safety): how much safer is Government Bonds vs Small Stocks? (1-9)",
        })
        questions.append({
            "matrix": "Assets_Liquidity",
            "items": ASSET_CLASSES,
            "asset_a": "Money Market", "asset_b": "Real Estate",
            "criterion": "Liquidity",
            "prompt": "Under Liquidity: how much more liquid is Money Market vs Real Estate? (1-9)",
        })

        return questions[:21]

    def _send(self, user_message: str) -> str:
        """Send message to Claude and maintain conversation history."""
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        reply = _call_anthropic(
            api_key=self.api_key,
            system=self._system,
            messages=self.conversation_history,
            max_tokens=1500,
        )

        self.conversation_history.append({
            "role": "assistant",
            "content": reply,
        })

        return reply

    def reset(self):
        """Clear conversation history for new session."""
        self.conversation_history = []
        self.challenge_count = 0

    def export_session(self) -> Dict:
        """Export full conversation for audit trail."""
        return {
            "mode": self.mode,
            "challenge_count": self.challenge_count,
            "context": self.context,
            "accepted_values": self.accepted_values,
            "conversation": self.conversation_history,
        }


# ─────────────────────────────────────────────────────────────
# INTERVIEW ENGINE — Guided 21-question AHP input collection
# ─────────────────────────────────────────────────────────────

class AHPInterviewEngine:
    """
    Conversational 21-question engine that collects all AHP inputs
    one at a time, validates each answer, and builds the AHP model.
    """

    def __init__(self, chatbot: AHPChallengerBot):
        self.bot = chatbot
        self.questions = chatbot.generate_interview()
        self.current_q = 0
        self.answers: Dict[int, int] = {}
        self.completed = False

    def get_current_question(self) -> Optional[Dict]:
        if self.current_q >= len(self.questions):
            self.completed = True
            return None
        q = self.questions[self.current_q]
        q["index"] = self.current_q + 1
        q["total"]  = len(self.questions)
        return q

    def validate_answer(self, value: int) -> Tuple[bool, str]:
        """Validate that answer is in Saaty 1-9 range."""
        if 1 <= value <= 9:
            return True, f"Valid. ({value} recorded)"
        return False, f"Invalid value {value}. Please enter 1-9."

    def submit_answer(self, value: int) -> Tuple[bool, str, Optional[str]]:
        """
        Submit answer for current question.
        Returns (success, message, ai_challenge_or_none).
        """
        valid, msg = self.validate_answer(value)
        if not valid:
            return False, msg, None

        q = self.questions[self.current_q]
        self.answers[self.current_q] = value

        # Challenge mode: challenge every answer
        challenge = None
        if self.bot.mode == "CHALLENGE":
            challenge = self.bot.challenge_comparison(
                q["asset_a"], q["asset_b"], q["criterion"],
                value, f"User entered {value}"
            )

        self.current_q += 1
        progress = f"{self.current_q}/{len(self.questions)}"
        return True, f"Saved! Progress: {progress}", challenge

    def build_ahp_inputs(self) -> Dict[str, Dict]:
        """Convert interview answers to AHP matrix inputs."""
        from ahp_engine import ACTORS, HORIZONS, SCENARIOS, CRITERIA

        result = {
            "actors": {}, "horizon": {}, "scenarios": {}, "criteria": {}
        }
        for i, q in enumerate(self.questions):
            if i not in self.answers:
                continue
            val = self.answers[i]
            matrix = q["matrix"]
            a, b   = q["asset_a"], q["asset_b"]
            if matrix == "Actors":
                result["actors"][(a, b)] = val
            elif matrix == "Horizon":
                result["horizon"][(a, b)] = val
            elif matrix == "Scenarios":
                result["scenarios"][(a, b)] = val
            elif matrix == "Criteria":
                result["criteria"][(a, b)] = val
        return result

    def get_summary(self) -> str:
        """Human-readable summary of all answers given."""
        lines = ["=== AHP Interview Answers ==="]
        for i, q in enumerate(self.questions):
            val = self.answers.get(i, "NOT ANSWERED")
            lines.append(f"Q{i+1:02d}. {q['asset_a']} vs {q['asset_b']} "
                         f"[{q['criterion']}]: {val}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# DEMO — Run chatbot in terminal
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("AHP Challenger Chatbot")
    print("Modes: CHALLENGE | COACH | AUDIT | FORECAST")
    mode = input("Select mode [CHALLENGE]: ").strip().upper() or "CHALLENGE"

    bot = AHPChallengerBot(mode=mode)

    # Demo challenge
    response = bot.challenge_comparison(
        asset_a="Large Stocks",
        asset_b="Government Bonds",
        criterion="Return",
        user_value=5,
        user_reasoning="Equities historically outperform bonds over long horizon"
    )
    print("\n" + "="*60)
    print(f"Bot ({mode} mode):")
    print("="*60)
    print(response)
    print("\n" + "="*60)

    # Interactive loop
    print("\nEntering interactive mode. Type 'exit' to quit.")
    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit", "q"):
            break
        if not user_input:
            continue
        reply = bot.ask_question(user_input)
        print(f"\nBot: {reply}")
