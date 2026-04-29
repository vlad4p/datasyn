---
name: improve-response-format
description: >-
  Improve the structure and readability of the assistant response without
  changing factual content. Use when the user asks to "improve format",
  "reformat", "make clearer", or "present better".
---

# Improve response format

Use this skill when the user asks for a better response format rather than new analysis.

## Goal

Return the same meaning with cleaner structure, concise wording, and scannable output.

## Workflow

```text
- [ ] 1) Identify user intent and required language (EN/ES)
- [ ] 2) Keep facts unchanged; remove filler
- [ ] 3) Reformat into short sections/bullets/tables if useful
- [ ] 4) Ensure actionability: include next steps when relevant
- [ ] 5) Return only the improved response (no meta commentary)
```

## Rules

- Do not invent data, metrics, or tool results.
- Do not claim actions that were not executed.
- Preserve technical identifiers, paths, SQL names, and tool names verbatim.
- Prefer:
  - short intro line
  - 3-6 bullets for findings
  - optional section for "Next steps"
- If the original response is already concise, apply minimal edits.

## Output template (optional)

```md
<one-line outcome>

- Key point 1
- Key point 2
- Key point 3

Next step: <single concrete action>
```
