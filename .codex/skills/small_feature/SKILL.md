---
name: small_feature
description: Use this skill to implement small, isolated system features.
---

# Skill: small_feature

You are a developer implementing a small, isolated system feature.

This skill is used when the feature has already been classified as `small` by the `new_feature` skill.

A small feature is specific, low-risk, and limited in scope. It should usually affect one file or one small area of the codebase.

---

## Input context

This skill receives context in the following format:

```json
{
  "classification": "small",
  "feature_request": "<original user request>",
  "reason": "<why the feature was classified as small>",
  "affected_areas": ["<area 1>", "<area 2>"],
  "risks": ["<risk 1>", "<risk 2>"],
  "required_checks": ["<check 1>", "<check 2>"]
}
```
## Rules
- Implement only the requested feature.
- Make the smallest safe change.
- Follow existing project patterns.
- Do not refactor unrelated code.
- Do not add unnecessary abstractions.
- Do not introduce new dependencies unless required.
- If the project structure is unclear, read AGENTS.md first.
- Use AGENTS.md only to understand structure, conventions, commands, and where to navigate.
- Do not read the whole repository unnecessarily.

## Navigation

Before editing, identify the smallest relevant area.

Examples:

- API endpoint → inspect routes/controllers.
- Business logic → inspect services/use cases.
- Validation → inspect schemas/models.
- Database query → inspect repositories/queries.
- Tests → inspect D:\benja\proyectos\postas_api\tests.

## Python checks

After implementing, run the most relevant Python checks available.

Prefer:

pytest D:\benja\proyectos\postas_api\tests

If there are targeted tests for the changed feature, prefer running only those first:

pytest D:\benja\proyectos\postas_api\tests\path\to\test_file.py

If available, also run:

ruff check .
mypy .

If a command is not available, do not invent alternatives. Report it as not available.

## Escalation

Stop and reclassify as medium or large if the feature requires:

- Multiple modules.
- Database migrations.
- Authentication, authorization, permissions, payments, or security-sensitive logic.
- New business rules.
- New architecture or a new subsystem.
- Large context to implement safely.

Use this format:

Reclassification required: medium | large

Reason:
<why this is not a small feature>

Recommended delegated skill:
<medium_feature | large_feature>
Output format

If completed:

Small feature implemented.

Summary:
- <change 1>
- <change 2>

Files changed:
- <file 1>
- <file 2>

Checks run:
- <command>: passed | failed | not available

Notes:
- <important detail or "None">

If not completed:

Small feature not completed.

Reason:
<clear explanation>

Files inspected:
- <file 1>
- <file 2>

What is needed:
- <missing detail, dependency, or decision>

## After implementation

After implementation, create a .txt file with the same name as the feature in docs/.

Use a safe filename:

Lowercase.
Replace spaces with _.
Remove special characters.
End with .txt.

Example:

best_selling_products.txt

The file must contain:

Feature:
<feature name>

Summary:
<what was implemented>

Files changed:
- <file 1>
- <file 2>

Tests created or updated:
- <test file or "None">

Documentation updated:
- <doc file or "None">

Checks run:
- <command>: passed | failed | not available

Important notes:
- <note or "None">