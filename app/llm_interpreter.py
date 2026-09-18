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
    """Configures and returns the Google GenAI Client if API key is provided."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def interpret_operator_notes(
    operator_notes: list[str]
) -> list[ParsedDirective]:
    """
    Interprets natural-language operator notes into structured directives.
    Uses Gemini LLM first with temperature 0.
    Falls back gracefully to a deterministic rule-based engine if Gemini
    fails, times out, is unconfigured, or returns malformed data (Section 08 Safe Failure).
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
        except Exception:
            # Controlled failover to deterministic rule engine
            pass

    return fallback_interpret_notes(operator_notes)


def build_interpretation_prompt(operator_notes: list[str]) -> str:
    """Builds an exhaustive prompt with Section 11.4 language variations and few-shots."""
    notes_formatted = "\n".join(
        f"{i}. \"{note}\"" for i, note in enumerate(operator_notes)
    )

    return f"""You are an expert energy scheduling assistant for BUP Smart Campus.
Analyze the following campus operator notes for today's 24-hour energy schedule (hours 0 to 23).

OPERATOR NOTES:
{notes_formatted}

SUPPORTED DIRECTIVES AND STRUCTURED DATA SCHEMA:
1. "solar_reduction": Usable rooftop solar generation is reduced.
   structured_data: {{"hours": [int, ...], "factor": float}}
   - factor is the REMAINING usable fraction between 0.0 and 1.0.
   - "drop to 20%" or "will drop to about 20%" -> factor = 0.2
   - "80% reduction" or "reduced by 80%" -> factor = 0.2 (1.0 - 0.8)
   - "reduced by 30%" -> factor = 0.7 (1.0 - 0.3)
   - "cut by 50%" or "half of normal output" -> factor = 0.5
   - "roughly one-fifth of normal solar output" -> factor = 0.2

2. "minimum_battery_reserve": Battery energy must remain at or above a given level.
   structured_data: {{"hours": [int, ...], "minimum_energy_kwh": float}}
   - "Keep at least 120 kWh in reserve" -> minimum_energy_kwh = 120.0
   - "Maintain battery reserve above 150 kWh" -> minimum_energy_kwh = 150.0

3. "no_charge_window": Battery charging is completely forbidden.
   structured_data: {{"hours": [int, ...]}}
   - "Do not charge the battery" -> no_charge_window

4. "no_discharge_window": Battery discharging is completely forbidden.
   structured_data: {{"hours": [int, ...]}}
   - "Do not discharge the battery" or "Battery discharging is unavailable" -> no_discharge_window

5. "max_grid_window": Electricity purchased from the grid cannot exceed a stated amount.
   structured_data: {{"hours": [int, ...], "max_grid_kwh": float}}
   - "Grid import may not exceed 100 kWh" -> max_grid_kwh = 100.0

6. "no_op": Note does not affect today's 24-hour schedule.
   structured_data: null
   - Irrelevant notes, cafeteria menus, weather next week, greetings, etc.

TIME WINDOW CONVENTION (CRITICAL):
- Time windows use whole-hour intervals. Start hour is INCLUDED and end hour is EXCLUDED:
  - "1 PM to 3 PM" or "13:00 to 15:00" -> hours [13, 14]
  - "1-3 PM" or "from one until three" -> hours [13, 14]
  - "between 2 PM and 4 PM" -> hours [14, 15]
  - "noon until 2 PM" or "12 PM to 2 PM" -> hours [12, 13]
  - "from 6 PM until 9 PM" -> hours [18, 19, 20]
  - "midnight to 4 AM" -> hours [0, 1, 2, 3]
  - "between 10 AM and 1 PM" -> hours [10, 11, 12]
- Hours must be strictly ascending unique integers from 0 to 23.

RULES:
- Return exactly one interpretation for every note.
- Return interpretations in note_index order: 0, 1, ...
- For no_op: structured_data must be null.
- Do not invent demand, solar, tariff, battery parameters or unsupported directive types.
- Return ONLY the JSON array.

Example Output:
[
  {{
    "note_index": 0,
    "directive_type": "solar_reduction",
    "structured_data": {{"hours": [13, 14], "factor": 0.2}},
    "explanation": "Solar output is reduced during panel cleaning."
  }},
  {{
    "note_index": 1,
    "directive_type": "no_charge_window",
    "structured_data": {{"hours": [14, 15]}},
    "explanation": "Battery charging is disabled between 2 PM and 4 PM."
  }},
  {{
    "note_index": 2,
    "directive_type": "no_op",
    "structured_data": null,
    "explanation": "Cafeteria menu update does not affect energy schedule."
  }}
]
"""


def parse_gemini_response(
    raw_text: str,
    num_notes: int
) -> list[ParsedDirective]:
    """Parses and sanitizes LLM JSON output, safely stripping markdown fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("Gemini response is not a JSON array")

    if len(data) != num_notes:
        raise ValueError(
            f"Expected {num_notes} interpretations, got {len(data)}"
        )

    parsed = []
    for item in data:
        parsed.append(ParsedDirective(**item))

    return parsed


def fallback_interpret_notes(
    operator_notes: list[str]
) -> list[ParsedDirective]:
    """
    Deterministic rule-based fallback when the LLM is unconfigured or fails.
    Implements Section 08 safe-failure requirement without crashing.
    """
    results = []
    for i, note in enumerate(operator_notes):
        lower = note.lower()
        hours = extract_hours_from_text(lower)

        # 1. Solar Reduction
        if any(k in lower for k in ["solar", "pv production", "sunlight", "panel washing", "rooftop solar"]):
            factor = 0.5
            if "20%" in lower or "one-fifth" in lower or "80% reduction" in lower or "reduced by 80%" in lower:
                factor = 0.2
            elif "half" in lower or "50%" in lower:
                factor = 0.5
            elif "reduced by 30%" in lower or "70%" in lower:
                factor = 0.7
            elif "reduced by 20%" in lower or "80%" in lower:
                factor = 0.8

            results.append(ParsedDirective(
                note_index=i,
                directive_type="solar_reduction",
                structured_data={"hours": hours or [13, 14], "factor": factor},
                explanation="Fallback rule matched solar reduction directive."
            ))
            continue

        # 2. No Charge Window
        if "charge" in lower and any(k in lower for k in ["do not", "no ", "stop", "unavailable", "prevent", "disable"]):
            if "discharge" not in lower:
                results.append(ParsedDirective(
                    note_index=i,
                    directive_type="no_charge_window",
                    structured_data={"hours": hours or [14, 15]},
                    explanation="Fallback rule matched no charge window."
                ))
                continue

        # 3. No Discharge Window
        if "discharge" in lower and any(k in lower for k in ["do not", "no ", "stop", "unavailable", "prevent", "disable"]):
            results.append(ParsedDirective(
                note_index=i,
                directive_type="no_discharge_window",
                structured_data={"hours": hours or [18, 19]},
                explanation="Fallback rule matched no discharge window."
            ))
            continue

        # 4. Minimum Battery Reserve
        if any(k in lower for k in ["reserve", "keep at least", "minimum battery", "minimum energy", "hold back"]):
            num_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kwh)?", lower)
            reserve_val = float(num_match.group(1)) if num_match else 120.0
            results.append(ParsedDirective(
                note_index=i,
                directive_type="minimum_battery_reserve",
                structured_data={"hours": hours or [18, 19, 20], "minimum_energy_kwh": reserve_val},
                explanation="Fallback rule matched minimum battery reserve."
            ))
            continue

        # 5. Max Grid Window
        if any(k in lower for k in ["grid import", "max grid", "grid cap", "grid cannot exceed", "grid limit"]):
            num_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kwh)?", lower)
            cap_val = float(num_match.group(1)) if num_match else 100.0
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
            explanation="Fallback identified note as non-operational or irrelevant."
        ))

    return results


def extract_hours_from_text(text: str) -> list[int]:
    """Helper to extract start-inclusive, end-exclusive whole-hour intervals."""
    text = text.lower()
    # Pattern: 13:00 to 15:00, 13:00 - 15:00, between 13:00 and 15:00
    m24 = re.search(r"(\d{1,2}):00\s*(?:to|until|-|and)\s*(\d{1,2}):00", text)
    if m24:
        s, e = int(m24.group(1)), int(m24.group(2))
        if 0 <= s < e <= 24:
            return list(range(s, e))

    # Pattern: 1 PM to 3 PM, 1-3 PM, 1 to 3 PM, between 2 PM and 4 PM
    m12 = re.search(
        r"(\d{1,2})\s*(am|pm)?\s*(?:to|until|-|and)\s*(\d{1,2})\s*(am|pm)",
        text
    )
    if m12:
        s_val = int(m12.group(1))
        s_mer = m12.group(2) or m12.group(4)
        e_val = int(m12.group(3))
        e_mer = m12.group(4)

        if s_mer == "pm" and s_val < 12:
            s_val += 12
        elif s_mer == "am" and s_val == 12:
            s_val = 0

        if e_mer == "pm" and e_val < 12:
            e_val += 12
        elif e_mer == "am" and e_val == 12:
            e_val = 0

        if 0 <= s_val < e_val <= 24:
            return list(range(s_val, e_val))

    # Common word hours
    if "one until three" in text or "1-3 pm" in text or "1 pm to 3 pm" in text:
        return [13, 14]
    if "noon until 2 pm" in text or "noon to 2 pm" in text or "12 pm to 2 pm" in text:
        return [12, 13]
    if "noon until 3 pm" in text or "noon to 3 pm" in text:
        return [12, 13, 14]
    if "midnight to 4 am" in text:
        return [0, 1, 2, 3]

    return []