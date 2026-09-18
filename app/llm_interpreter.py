import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models.directive_models import ParsedDirective


load_dotenv()


def configure_gemini():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")

    return genai.Client(api_key=api_key)


def interpret_operator_notes(
    operator_notes: list[str]
) -> list[ParsedDirective]:

    client = configure_gemini()

    prompt = build_interpretation_prompt(operator_notes)

    response = client.models.generate_content(
        model=os.getenv("LLM_MODEL", "gemini-3.5-flash-lite"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    return parse_gemini_response(
        response.text,
        len(operator_notes)
    )


def build_interpretation_prompt(
    operator_notes: list[str]
) -> str:

    notes_str = "\n".join(
        f"{i}. {note}"
        for i, note in enumerate(operator_notes)
    )

    return f"""You are an energy scheduling expert.

Interpret these operator notes for a 24-hour campus energy schedule.

OPERATOR NOTES:
{notes_str}

SUPPORTED DIRECTIVES:

1. solar_reduction

Structured data:
{{"hours": [...], "factor": number}}

The factor is the fraction of normal solar output remaining.

Examples:
- "20% of normal solar" = factor 0.2
- "80% reduction" = factor 0.2
- "half of normal solar" = factor 0.5

2. minimum_battery_reserve

Structured data:
{{"hours": [...], "minimum_energy_kwh": number}}

3. no_charge_window

Structured data:
{{"hours": [...]}}

4. no_discharge_window

Structured data:
{{"hours": [...]}}

5. max_grid_window

Structured data:
{{"hours": [...], "max_grid_kwh": number}}

6. no_op

Structured data:
null

TIME CONVENTION:

Whole-hour intervals are start-inclusive and end-exclusive.

Examples:

"1 PM to 3 PM" = [13, 14]

"6 PM to 10 PM" = [18, 19, 20, 21]

"noon until 2 PM" = [12, 13]

IMPORTANT RULES:

- Return exactly one interpretation for every note.
- Return interpretations in note_index order: 0, 1, 2, ...
- Use no_op only when the note does not affect the energy schedule.
- Do not invent demand, solar, tariff, battery, or other numerical values.
- Do not invent unsupported directive types.
- Hours must be unique integers from 0 to 23.
- Hours must be in ascending order.
- For solar_reduction, factor means the fraction remaining.
- An 80% reduction means factor 0.2.
- A reduction to 20% means factor 0.2.
- A note about an unrelated topic must be no_op.
- A future event that does not apply to the current scenario must be no_op.
- Every note must receive exactly one interpretation.

Return a JSON array in exactly this structure:

[
  {{
    "note_index": 0,
    "directive_type": "solar_reduction",
    "structured_data": {{
      "hours": [13, 14],
      "factor": 0.2
    }},
    "explanation": "Solar output is reduced during the specified window."
  }},
  {{
    "note_index": 1,
    "directive_type": "no_op",
    "structured_data": null,
    "explanation": "This note does not affect the energy schedule."
  }}
]

Now interpret the operator notes.

Return ONLY the JSON array.
"""


def parse_gemini_response(
    raw_text: str,
    num_notes: int
) -> list[ParsedDirective]:

    try:
        data = json.loads(raw_text)

        if not isinstance(data, list):
            raise ValueError(
                "Gemini response is not a JSON array"
            )

        if len(data) != num_notes:
            raise ValueError(
                f"Expected {num_notes} interpretations, "
                f"got {len(data)}"
            )

        parsed = []

        for item in data:
            parsed.append(
                ParsedDirective(**item)
            )

        return parsed

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise ValueError(
            f"Failed to parse Gemini response: {e}"
        )