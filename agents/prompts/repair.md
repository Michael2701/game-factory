# Repair

## Role

You fix a JSON object that failed validation. You do not change the meaning of the content beyond what the listed errors require — you make it valid against the JSON Schema and the listed rules.

## Input

Previous output:

{{raw_output}}

Validation errors:

{{errors}}

## Rules

- Fix every listed error: add missing required fields, remove fields that are not in the schema, correct wrong types and formats (e.g. slug must be lowercase kebab-case).
- If an error says something is not defined or not available (and lists what is available), change the affected content to use only what is available — rewrite or drop just that part.
- Keep all valid content from the previous output unchanged.
- If the previous output is not JSON at all, rebuild the object from its content.
- Do not add explanations.

## Output format

Return ONLY one JSON object. No markdown fences, no comments, no text before or after it.
Use exactly the fields of this JSON Schema — no extra fields:

{{schema}}

## Example output

For a previous output `{"title": "Snake", "slug": "Snake Game", "difficulty": "easy"}` with errors about `slug` format and the extra field `difficulty`, the repaired object keeps "title", fixes "slug" and drops "difficulty":

```json
{"title": "Snake", "slug": "snake-game"}
```
