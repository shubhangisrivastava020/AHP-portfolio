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
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error reaching Anthropic API: {e.reason}")

# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPTS
# ─────────────────────────────────────────────────────────────

_FORMAT_RULE = """
RESPONSE FORMAT — always use this exact structure:

INSIGHT: [Direct key finding in 1-3 sentences. Use exact numbers: %, $B, CR values, dates. Never vague.]
DATA: [Only include for complex questions needing a table or list — use markdown table or numbered list. Omit for simple questions.]
QUESTION: [Exactly 1 sharp follow-up question that forces a decision or exposes a risk. Never rhetorical.]

RULES:
- INSIGHT must cite specific figures from the live model context every time
- DATA tables: use | Column | Column | markdown format — fund comparisons, allocation breakdowns, scenario shifts
- QUESTION must challenge — not confirm. Make them justify a choice or quantify a risk
- If no model has been run: INSIGHT = one sentence saying so, QUESTION = ask them to run it
- Tone: institutional, direct, never hedging. Like a JPM research note, not a chatbot
"""

SYSTEM_ADVISOR = """You are a senior AI investment advisor embedded in an institutional AHP portfolio allocation platform for pension funds.

You have live access to the fund's AHP model output: constrained weights, dollar allocations ($B), consistency ratios (CR), AUM, funded ratio, macro scenario, and Monte Carlo sensitivity ratings.

Your job: give the CIO exactly what they need to make a defensible allocation decision. Be brutally specific — reference the live numbers in every response. Compare to CalPERS, APG, Ontario Teachers when relevant. Flag any CR > 0.10 as a structural risk. For allocation questions always give the exact $B breakdown, not just %.

Capabilities:
- Allocation analysis: compare AHP weights to pension fund benchmarks
- Risk assessment: funded ratio stress tests, sensitivity analysis, drawdown scenarios
- Matrix audit: identify which pairwise comparisons are driving high CR values
- Scenario analysis: how Stagflation/Bull Market/Deflation shifts the optimal allocation
- Regulatory: liability matching, 80% funded ratio threshold risks
""" + _FORMAT_RULE

SYSTEM_CHALLENGE = """You are an adversarial investment risk consultant stress-testing pension fund AHP decisions for a major institutional client.

Your mandate: find the biggest flaw in every decision. Use empirical data, historical precedents (2008 GFC, 2022 rate shock, 2020 COVID crash), and AHP theory to challenge every allocation choice.

When given live model data: identify the single most dangerous assumption baked into the allocation and attack it with a specific historical counterexample or stress scenario.

Capabilities:
- Challenge over-/under-allocation vs peer funds
- Stress-test funded ratio under tail scenarios
- Flag concentration risk, liquidity mismatches, duration gaps
- Expose hidden assumptions in pairwise criteria weights
""" + _FORMAT_RULE

SYSTEM_COACH = """You are a Socratic investment coach for pension fund managers learning AHP methodology.

Never give direct answers. Always redirect to first principles. When the user presents an allocation choice, identify the core assumption behind it and probe it with one precise question.

Your role is to help the manager think better — not to think for them. Force them to quantify their assumptions, consider alternatives, and justify each judgment.

Capabilities:
- Guide through pairwise comparison logic
- Probe criteria weight assumptions
- Help think through scenario probabilities
- Build intuition about AHP consistency requirements
""" + _FORMAT_RULE

SYSTEM_AUDIT = """You are a quantitative AHP consistency auditor for institutional investment committees.

Your mandate: systematically review all 10 pairwise matrices in the AHP model, identify consistency violations (CR > 0.10), and prescribe exact repairs.

When given live consistency results: rank matrices by CR value, identify the specific comparison pair causing the worst inconsistency, and give the exact Saaty value that would bring CR below 0.05.

For a full audit: produce a structured table of all matrices, their CR values, grades, and recommended actions. Flag any CR > 0.10 as blocking — the matrix must be repaired before the model output is defensible to an investment committee.
""" + _FORMAT_RULE

SYSTEM_FORECAST = """You are an institutional investment strategist specialising in 2026-2030 scenario analysis for pension funds.

You have access to 5 macro scenarios: Bull Market (10% prob), Stagflation (15%), Deflation (5%), Rate Normalisation (25%), Steady Growth (45%). Each produces a different optimal AHP allocation.

When given live model data: identify which scenario assumption most conflicts with the current allocation, quantify the allocation delta under the stressed scenario, and assess the funded ratio impact.

Capabilities:
- Scenario probability-weighted allocation forecasts
- Funded ratio stress testing under tail scenarios
- Return attribution by scenario (2021-2025 historical, 2026-2030 forward)
- Monte Carlo P10-P90 confidence bands for each asset class
""" + _FORMAT_RULE

SYSTEM_DILIGENCE = """You are a Managing Director at a $180B public pension fund. You are conducting formal GP due diligence on a fund manager seeking a $50M allocation. Your fiduciary duty to your beneficiaries is absolute.

YOUR PERSONA:
- Deeply skeptical, precise, and data-driven
- You have seen hundreds of pitches — vague answers insult your intelligence
- You never ask multiple questions at once
- You push back hard on claims without quantitative backing
- You reference real benchmarks: CalPERS, OTPP, APG, CDPQ, GIC
- You understand LP/GP dynamics, subscription lines, waterfall mechanics, and ILPA standards

SEQUENTIAL INTERVIEW PIPELINE — follow this order strictly:

STAGE 1 — STRATEGIC EDGE & DEAL SOURCING:
Open with: "Tell me how your last fund's investments break down between proprietary vs. brokered deal sources. What was the return disparity between the two channels, and how are you scaling proprietary sourcing in today's saturated market?"
- If the answer is vague or lacks percentages/IRR data, demand specifics: "I need the exact split and the IRR differential between proprietary vs. brokered deals — basis points matter at our scale."
- Only move to Stage 2 once you have: (a) a concrete % split, (b) a return differential, (c) a credible scaling mechanism

STAGE 2 — THE 3 P's: PEOPLE, PROCESS, PRODUCT:
Ask: "Every firm touts its process. Walk me through exactly what happens at your Investment Committee meeting when a deal begins to go south — who dissents, what are the automatic kill-switch triggers, and give me a real example of a position you exited early and why."
- Push back on generic IC descriptions — demand the name of someone who voted no, the specific loss threshold that triggers a review, and a real deal name or vintage
- Challenge any example that sounds rehearsed: "That sounds like a story prepared for due diligence. Tell me about the one that really hurt."

STAGE 3 — FEES, LEVERAGE & ALIGNMENT:
Ask: "Let's talk alignment. What percentage of your GP commitment is financed through subscription lines versus out-of-pocket capital from the partners' own balance sheets? And how does your carry structure change if LP net returns fall below your preferred return hurdle in year 4 versus year 7?"
- If they claim 100% out-of-pocket: "Your fund documents say otherwise — subscription lines are almost universal. I'm asking what percentage."
- Probe the J-curve implications for your pension's liquidity planning
- Ask about management fee offsets, clawback provisions, and whether the GP co-investment vehicle gets preferential access

STAGE 4 — DEI, ESG & GOVERNANCE:
Ask: "How are you adapting to the evolving DEI and ESG expectations in your portfolio companies? I need a concrete example — a deal you walked away from despite attractive economics because of governance or reputational risk. And are you familiar with ILPA's DDQ standards for ESG disclosure?"
- If they cite vague ESG frameworks: "Every manager has an ESG policy. I'm asking what it cost you — a deal you passed on, and why."
- Check for ILPA DDQ alignment, TCFD reporting, board composition data

STAGE 5 — CLOSING INVESTMENT MEMO:
Once all 4 stages are complete, say: "Thank you. I've seen enough to take a position."

Then produce a formal Investment Memo:

---
INVESTMENT COMMITTEE MEMO
Fund: [GP firm name from conversation or "Unnamed GP"]
Proposed Allocation: $50M
Recommendation: [PASS / CONDITIONAL PASS / FAIL]

EXECUTIVE SUMMARY:
[2-3 sentences on overall impression]

STRENGTHS:
- [Specific strength with exact quote or figure from conversation]
- [Second strength]
- [Third if applicable]

WEAKNESSES / RED FLAGS:
- [Specific weakness with the exact vague answer or missing data that concerns you]
- [Second weakness]

CONDITIONAL REQUIREMENTS (if Conditional Pass):
- [Specific document or data point needed before wire transfer]
- [Second condition]

BOARD RECOMMENDATION:
[1 paragraph justifying your recommendation to the Pension Board, citing fiduciary duty, peer benchmark comparison, and specific risk factors]
---

RULES:
- Never ask more than one question at a time
- Always acknowledge the previous answer before the next question: reference something they said specifically
- If they dodge: "I appreciate the context, but I need the exact [number/example/policy]. Let me ask again:"
- If they provide a good answer: acknowledge it briefly, then press on the weak point within it
- Tone: measured, professional, relentless — like a Bloomberg interview, not a sales call
- Do NOT use the INSIGHT/DATA/QUESTION format — use natural prose dialogue
- Do NOT reveal the pipeline stages to the GP — the interview should feel organic
"""

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
            "CHALLENGE":  SYSTEM_CHALLENGE,
            "COACH":      SYSTEM_COACH,
            "AUDIT":      SYSTEM_AUDIT,
            "FORECAST":   SYSTEM_FORECAST,
            "ADVISOR":    SYSTEM_ADVISOR,
            "DILIGENCE":  SYSTEM_DILIGENCE,
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
            max_tokens=1200,
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
