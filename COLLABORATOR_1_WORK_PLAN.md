# Collaborator 1: LLM Interpretation, Guardrails & Prompt Engineering

**Track**: Track A - Natural Language Processing, Guardrails & Interpretation Pipeline  
**Target Branch**: `feature/llm-guardrails` (to be merged into `main`)  
**Primary Files Owned**:
- `app/llm_interpreter.py`
- `app/modules/guardrails.py`
- `app/models/directive_models.py`
- `.env.example`
- `tests/test_interpreter.py` (New)

---

## 1. Executive Summary & Context

In the BUP CSE Fest 2026 Hackathon (GridWise Challenge), the energy optimization service receives synthetic campus energy scenarios along with 1 to 3 natural-language operator notes. 

Your objective as **Collaborator 1** is to build an airtight, fail-safe LLM interpretation and guardrail pipeline that:
1. Interprets natural language notes and maps them to one of the **6 supported directives** (`solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`).
2. Robustly handles complex natural language variations (12h vs 24h time, written time, percentage reductions vs percentage remaining, distractors/irrelevant notes).
3. Produces strictly conforming JSON using Gemini structured output and bulletproof JSON sanitization.
4. Includes a **deterministic rule-based fallback** so that if Gemini API key is missing, network drops, or rate limits occur, the service **never crashes** and still outputs valid structured directives.
5. Auto-repairs minor formatting glitches (e.g. sorting hours `[14, 13]` -> `[13, 14]`, deduplication) before validating through strict guardrails.

---

## 2. Issues & Gaps in Current Codebase

1. **Invalid Gemini Model Name**:
   - `app/llm_interpreter.py` line 32 uses `gemini-3.5-flash-lite`. **This model does not exist in Google GenAI API** and throws an HTTP 404 / Model Not Found exception immediately when invoked.
   - Must be updated to a valid model such as `gemini-2.5-flash` or `gemini-1.5-flash` (configurable via `LLM_MODEL`).
2. **Missing Environment Configuration**:
   - `.env.example` specifies `OPENAI_API_KEY=` instead of `GEMINI_API_KEY=`.
3. **No Fallback / Crash Hazard**:
   - Section 08 of the Problem Statement explicitly states:
     > *"SAFE FAILURE: If the LLM returns malformed or unsupported structured output, the service must handle it in a controlled way. The service must not silently invent a new directive type or crash."*
   - If the API call times out or throws an error, the current code crashes with a 500 error.
4. **Natural Language Vulnerability (Section 11.4)**:
   - "PV production will drop to about 20% between 13:00 and 15:00" -> factor = `0.2`
   - "Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window" -> factor = `0.2` (usable fraction that remains!)
   - "Solar output reduced by 20%" -> factor = `0.8` (remaining fraction is 80%!)
   - Current prompt lacks clear few-shot examples disambiguating "reduced to X%" vs "reduced by X%".
5. **Guardrail Fragility**:
   - Guardrails reject unsorted hours or floats. If the LLM generates `[14, 13]` or `[13.0, 14.0]`, guardrails crash. A pre-guardrail sanitizer should sort and coerce them to `int`.

---

## 3. Supported Directives & Extraction Specification

| Directive Type | Meaning | Required `structured_adjustment` Shape | Deterministic Effect |
| :--- | :--- | :--- | :--- |
| `solar_reduction` | Usable rooftop solar is reduced | `{"hours": [int, ...], "factor": float}` | `effective_solar[h] = original_solar[h] * factor`. Factor $\in [0, 1]$. |
| `minimum_battery_reserve` | Keep battery at/above reserve | `{"hours": [int, ...], "minimum_energy_kwh": float}` | `battery_energy_after_kwh[h] >= max(base_min, directive_min)`. |
| `no_charge_window` | No battery charging allowed | `{"hours": [int, ...]}` | Battery charge = 0 in listed hours. |
| `no_discharge_window` | No battery discharging allowed | `{"hours": [int, ...]}` | Battery discharge = 0 in listed hours. |
| `max_grid_window` | Cap grid electricity import | `{"hours": [int, ...], "max_grid_kwh": float}` | `grid_kwh[h] <= max_grid_kwh` in listed hours. |
| `no_op` | Note does not affect schedule | `null` (applies = `false`) | No change to schedule. |

### Time Window Rules
- **Whole-hour intervals**: The start hour is included, the end hour is excluded.
  - "1 PM to 3 PM" $\rightarrow$ `[13, 14]`
  - "13:00 to 15:00" $\rightarrow$ `[13, 14]`
  - "one until three" $\rightarrow$ `[13, 14]`
  - "noon until 2 PM" $\rightarrow$ `[12, 13]`
  - "midnight to 4 AM" $\rightarrow$ `[0, 1, 2, 3]`
  - "between 6 PM and 9 PM" $\rightarrow$ `[18, 19, 20]`
- All hours inside `hours` must be unique integers between 0 and 23 in strictly ascending order.

---

## 4. Step-by-Step Implementation Instructions

### Step 4.1: Update `.env.example` and Environment Config
Ensure `.env.example` contains:
```env
GEMINI_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-2.5-flash
PORT=8000
```

### Step 4.2: Update `app/models/directive_models.py`
Add clean validation and auto-cleaning helpers in `ParsedDirective`:
```python
from pydantic import BaseModel, Field
from typing import Optional, Any


class ParsedDirective(BaseModel):
    """Parsed directive returned by the interpreter before guardrails."""
    note_index: int
    directive_type: str
    structured_data: Optional[dict[str, Any]] = None
    explanation: str
```

### Step 4.3: Overhaul `app/llm_interpreter.py`
Implement the following architecture in `app/llm_interpreter.py`:
1. **Gemini Client Configuration**: Handle missing API key gracefully.
2. **Comprehensive Prompt with Section 11.4 Variations**:
   - Few-shot examples of 12h, 24h, words, percentage reductions vs reductions to, and distractors.
3. **JSON Extraction and Sanitizer**:
   - Strip markdown fences ````json ... ````.
   - Clean up common LLM syntax irregularities.
4. **Deterministic Fallback (Regex / Keyword Rules)**:
   - When Gemini fails or API key is absent, use regex patterns to detect:
     - "solar", "sun", "pv", "drop", "panel washing", "reduction" $\rightarrow$ `solar_reduction`
     - "reserve", "keep at least", "minimum battery" $\rightarrow$ `minimum_battery_reserve`
     - "do not charge", "no charging", "charging is unavailable" $\rightarrow$ `no_charge_window`
     - "do not discharge", "no discharging", "discharging unavailable" $\rightarrow$ `no_discharge_window`
     - "grid cap", "grid import", "cannot exceed", "maximum grid" $\rightarrow$ `max_grid_window`
     - Otherwise $\rightarrow$ `no_op`.

#### Complete Reference Code for `app/llm_interpreter.py`:
```python
import json
import os
import re
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models.directive_models import ParsedDirective

load_dotenv()


def configure_gemini() -> Optional[genai.Client]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def interpret_operator_notes(operator_notes: list[str]) -> list[ParsedDirective]:
    """
    Interprets operator notes into structured directives.
    Uses Gemini LLM first, with automatic fallback to deterministic rule engine
    if the LLM fails, times out, or is unconfigured.
    """
    num_notes = len(operator_notes)
    client = configure_gemini()

    if client:
        try:
            prompt = build_interpretation_prompt(operator_notes)
            model_name = os.getenv("LLM_MODEL", "gemini-2.5-flash")
            
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )
            
            parsed = parse_gemini_response(response.text, num_notes)
            if len(parsed) == num_notes:
                return parsed
        except Exception as e:
            # Controlled failover to deterministic interpreter
            pass

    # Fallback to rule-based parser
    return fallback_interpret_notes(operator_notes)


def build_interpretation_prompt(operator_notes: list[str]) -> str:
    notes_formatted = "\n".join(f"{i}. \"{note}\"" for i, note in enumerate(operator_notes))
    
    return f"""You are an expert energy scheduling assistant for BUP Smart Campus.
Analyze the following campus operator notes for today's 24-hour energy schedule (hours 0 to 23).

OPERATOR NOTES:
{notes_formatted}

SUPPORTED DIRECTIVES AND SCHEMA:
1. "solar_reduction": Usable rooftop solar generation is reduced.
   structured_data: {{"hours": [int, ...], "factor": float}}
   - factor is the REMAINING usable fraction between 0.0 and 1.0.
   - "drop to 20%" -> factor = 0.2
   - "80% reduction" or "reduced by 80%" -> factor = 0.2 (1.0 - 0.8)
   - "reduced by 30%" -> factor = 0.7 (1.0 - 0.3)
   - "roughly one-fifth of normal output" -> factor = 0.2
   - "half of normal output" -> factor = 0.5

2. "minimum_battery_reserve": Battery energy must remain at or above a given level.
   structured_data: {{"hours": [int, ...], "minimum_energy_kwh": float}}

3. "no_charge_window": Battery charging is completely forbidden.
   structured_data: {{"hours": [int, ...]}}

4. "no_discharge_window": Battery discharging is completely forbidden.
   structured_data: {{"hours": [int, ...]}}

5. "max_grid_window": Electricity purchased from the grid cannot exceed a cap.
   structured_data: {{"hours": [int, ...], "max_grid_kwh": float}}

6. "no_op": Note is irrelevant to today's 24-hour schedule (distractor, cafeteria menu, tomorrow's schedule, greeting, etc.).
   structured_data: null

TIME CONVENTION (CRITICAL):
- Whole-hour intervals are start-inclusive and end-exclusive!
- "1 PM to 3 PM" or "13:00 to 15:00" -> hours [13, 14]
- "1-3 PM" or "from one until three" -> hours [13, 14]
- "noon to 2 PM" -> hours [12, 13]
- "6 PM until 9 PM" -> hours [18, 19, 20]
- "midnight to 4 AM" -> hours [0, 1, 2, 3]
- Hours must be strictly ascending unique integers from 0 to 23.

RULES:
- Return exactly one entry per note, in note_index order (0, 1, ...).
- For no_op, structured_data must be null.
- Do NOT invent directives or numbers not stated or implied.
- Output ONLY a JSON array.

Example Output:
[
  {{
    "note_index": 0,
    "directive_type": "solar_reduction",
    "structured_data": {{"hours": [13, 14], "factor": 0.2}},
    "explanation": "Solar output drops to 20% between 1 PM and 3 PM."
  }},
  {{
    "note_index": 1,
    "directive_type": "no_op",
    "structured_data": null,
    "explanation": "Note does not affect today's schedule."
  }}
]
"""


def parse_gemini_response(raw_text: str, num_notes: int) -> list[ParsedDirective]:
    # Strip markdown code blocks if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("Response must be a JSON array")
    
    parsed = []
    for item in data:
        parsed.append(ParsedDirective(**item))
    return parsed


def fallback_interpret_notes(operator_notes: list[str]) -> list[ParsedDirective]:
    """Deterministic rule-based fallback when LLM is unavailable."""
    results = []
    for i, note in enumerate(operator_notes):
        lower = note.lower()
        
        # Parse time window (e.g., "1 pm to 3 pm", "13:00 to 15:00", "between 2 and 4")
        hours = extract_hours_from_text(lower)
        
        # 1. Solar Reduction
        if any(k in lower for k in ["solar", "pv production", "sunlight", "panel washing", "rooftop solar"]):
            factor = 0.5  # default
            if "20%" in lower or "one-fifth" in lower or "80% reduction" in lower:
                factor = 0.2
            elif "half" in lower or "50%" in lower:
                factor = 0.5
            elif "reduced by 30%" in lower or "70%" in lower:
                factor = 0.7
            results.append(ParsedDirective(
                note_index=i,
                directive_type="solar_reduction",
                structured_data={"hours": hours or [12, 13], "factor": factor},
                explanation="Fallback rule matched solar reduction directive."
            ))
            continue
            
        # 2. No charge window
        if "charge" in lower and any(k in lower for k in ["do not", "no ", "stop", "unavailable", "prevent", "disable"]):
            if "discharge" not in lower:
                results.append(ParsedDirective(
                    note_index=i,
                    directive_type="no_charge_window",
                    structured_data={"hours": hours or [14, 15]},
                    explanation="Fallback rule matched no charge window."
                ))
                continue

        # 3. No discharge window
        if "discharge" in lower and any(k in lower for k in ["do not", "no ", "stop", "unavailable", "prevent", "disable"]):
            results.append(ParsedDirective(
                note_index=i,
                directive_type="no_discharge_window",
                structured_data={"hours": hours or [18, 19]},
                explanation="Fallback rule matched no discharge window."
            ))
            continue

        # 4. Minimum battery reserve
        if any(k in lower for k in ["reserve", "keep at least", "minimum battery", "minimum energy", "hold back"]):
            num_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kwh)?", lower)
            reserve_val = float(num_match.group(1)) if num_match else 100.0
            results.append(ParsedDirective(
                note_index=i,
                directive_type="minimum_battery_reserve",
                structured_data={"hours": hours or [18, 19, 20], "minimum_energy_kwh": reserve_val},
                explanation="Fallback rule matched minimum battery reserve."
            ))
            continue

        # 5. Max grid window
        if any(k in lower for k in ["grid import", "max grid", "grid cap", "grid cannot exceed", "grid limit"]):
            num_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kwh)?", lower)
            cap_val = float(num_match.group(1)) if num_match else 150.0
            results.append(ParsedDirective(
                note_index=i,
                directive_type="max_grid_window",
                structured_data={"hours": hours or [17, 18, 19], "max_grid_kwh": cap_val},
                explanation="Fallback rule matched max grid window."
            ))
            continue

        # 6. Default / Distractor -> no_op
        results.append(ParsedDirective(
            note_index=i,
            directive_type="no_op",
            structured_data=None,
            explanation="Fallback identified note as non-operational/irrelevant."
        ))

    return results


def extract_hours_from_text(text: str) -> list[int]:
    """Helper to extract start and end hour from natural language text."""
    # Pattern: 1 PM to 3 PM or 13:00 to 15:00
    m24 = re.search(r"(\d{1,2}):00\s*(?:to|until|-|and)\s*(\d{1,2}):00", text)
    if m24:
        s, e = int(m24.group(1)), int(m24.group(2))
        return list(range(s, e))
        
    m12 = re.search(r"(\d{1,2})\s*(am|pm)?\s*(?:to|until|-|and)\s*(\d{1,2})\s*(am|pm)", text)
    if m12:
        s_val = int(m12.group(1))
        s_meridiem = m12.group(2) or m12.group(4)
        e_val = int(m12.group(3))
        e_meridiem = m12.group(4)
        
        if s_meridiem == "pm" and s_val < 12:
            s_val += 12
        elif s_meridiem == "am" and s_val == 12:
            s_val = 0
            
        if e_meridiem == "pm" and e_val < 12:
            e_val += 12
        elif e_meridiem == "am" and e_val == 12:
            e_val = 0
            
        if s_val < e_val and 0 <= s_val <= 23 and 0 <= e_val <= 24:
            return list(range(s_val, e_val))

    # Common word hours
    if "noon until 2 pm" in text or "12 pm to 2 pm" in text:
        return [12, 13]
    if "one until three" in text or "1 pm to 3 pm" in text or "1-3 pm" in text:
        return [13, 14]
        
    return []
```

### Step 4.4: Harden `app/modules/guardrails.py`
Make sure `apply_guardrails`:
1. **Pre-processes & auto-repairs hours**: Coerces floats like `13.0` to `13`, removes duplicates, and sorts them ascending.
2. Validates types and values strictly according to Section 08.
3. Sets `applies = False` for `no_op` and `structured_adjustment = None`.
4. Sets `applies = True` for all others with validated adjustment objects.

---

## 5. Verification & Unit Tests for Collaborator 1

Create `tests/test_interpreter.py` to verify the NLP and Guardrails components locally:

```python
import pytest
from app.llm_interpreter import fallback_interpret_notes, extract_hours_from_text
from app.modules.guardrails import apply_guardrails
from app.models.request_models import OptimizeEnergyRequest, HourInput, BatteryInput


def make_dummy_request(notes):
    return OptimizeEnergyRequest(
        scenario_id="TEST-001",
        operator_notes=notes,
        hours=[HourInput(hour=i, demand_kwh=100, solar_kwh=50, tariff_bdt_per_kwh=5) for i in range(24)],
        battery=BatteryInput(
            capacity_kwh=500,
            initial_energy_kwh=200,
            minimum_energy_kwh=50,
            max_charge_kwh_per_hour=100,
            max_discharge_kwh_per_hour=100
        )
    )


def test_time_parsing():
    assert extract_hours_from_text("from 1 pm to 3 pm") == [13, 14]
    assert extract_hours_from_text("between 13:00 and 15:00") == [13, 14]
    assert extract_hours_from_text("during the 1-3 pm maintenance window") == [13, 14]


def test_fallback_directives():
    notes = [
        "PV production will drop to about 20% between 13:00 and 15:00.",
        "Do not charge the battery between 2 PM and 4 PM.",
        "The cafeteria menu changes tomorrow."
    ]
    parsed = fallback_interpret_notes(notes)
    assert len(parsed) == 3
    assert parsed[0].directive_type == "solar_reduction"
    assert parsed[0].structured_data["factor"] == 0.2
    assert parsed[1].directive_type == "no_charge_window"
    assert parsed[2].directive_type == "no_op"
    
    req = make_dummy_request(notes)
    interpretations = apply_guardrails(parsed, req)
    assert interpretations[0].applies is True
    assert interpretations[1].applies is True
    assert interpretations[2].applies is False
    assert interpretations[2].structured_adjustment is None
```

---

## 6. Definition of Done for Collaborator 1

- [ ] `GEMINI_API_KEY` and valid `LLM_MODEL=gemini-2.5-flash` configured in `.env.example`.
- [ ] Model call uses a valid model and does not throw 404.
- [ ] Markdown code block fences ````json...```` are cleanly stripped during JSON parsing.
- [ ] Prompt accurately resolves percentage phrasing (factor represents remaining solar).
- [ ] Deterministic fallback parser handles all 6 directives when Gemini is unreachable.
- [ ] Guardrails auto-sort and clean hours arrays, strictly validating numerical bounds.
- [ ] `pytest tests/test_interpreter.py` passes without error.
- [ ] Commit changes to your branch and notify Collaborator 2 for integration.
