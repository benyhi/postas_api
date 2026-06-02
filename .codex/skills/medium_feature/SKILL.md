---
name: medium_feature
description: Use this skill to implement medium-sized Python/Django features that affect several files in an existing module and require tests or documentation updates.
---
# Skill: medium_feature

You are a developer implementing a medium-sized feature.

This skill is called after `new_feature` classifies the request as `medium`.

A medium feature is clear enough to implement, but may affect several files inside an existing module, endpoint, model, service, repository, documentation, or test area.

---

## Input

```json
{
  "classification": "medium",
  "feature_request": "<original user request>",
  "reason": "<classification reason>",
  "affected_areas": ["<area 1>", "<area 2>"],
  "risks": ["<risk 1>", "<risk 2>"],
  "required_checks": ["<check 1>", "<check 2>"]
}
```

## Rules
- Understand the existing implementation before editing.
- Read AGENTS.md if project structure, conventions, commands, or navigation are unclear.
- Follow existing project patterns.
- Keep the implementation scoped to the requested feature.
Do not refactor unrelated code.
Do not introduce new architecture unless required.
Reuse existing models, services, repositories, schemas, utilities, and patterns when possible.
Create or update tests when behavior changes.
Update documentation if the feature changes usage, endpoints, commands, environment variables, models, or expected behavior.
If database changes are required, check existing migration patterns before editing.

## Navigation

Inspect only the relevant parts of the project.

Examples:

API endpoint → routes/controllers, schemas, services, tests, docs.
New model field → model, schema, migration, service, tests, docs.
Query/filtering logic → repository/query layer, service, endpoint, tests.
Agent/tool behavior → graph/node/tool definitions, schemas, tests, docs.
Tests → inspect D:\benja\proyectos\postas_api\tests.
Documentation → inspect README.md, AGENTS.md, docs/, or related markdown files.

Do not read the whole repository unless needed.

Implementation flow
Inspect AGENTS.md if needed.
Locate the existing pattern closest to the requested feature.
Create a short implementation plan.
Modify the relevant files.
Create or update tests when applicable.
Update documentation when needed.
Run targeted checks first.
Run broader Python checks if available.
Create a .txt implementation summary file in docs/.
Python checks

Prefer targeted tests first:

pytest D:\benja\proyectos\postas_api\tests\path\to\test_file.py

Then run the full test suite if appropriate:

pytest D:\benja\proyectos\postas_api\tests

If available, also run:

ruff check .
mypy .

If the project has a harness, prefer it after targeted tests:

make codex-check

If a command is not available, do not invent alternatives. Report it as not available.

Documentation rules

Update documentation only when needed.

Documentation should be updated if the feature changes:

Public API behavior.
Request or response schemas.
Environment variables.
Setup or execution steps.
Database models that users or developers need to know about.
Commands or workflows.
Agent behavior, tools, routes, or expected inputs/outputs.

Do not update documentation for purely internal implementation details unless they affect usage or maintenance.

Implementation summary file

After implementation, create a .txt file with the same name as the feature.

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
Escalation

Stop and reclassify as large if the feature requires:

New subsystem or module architecture.
Authentication, authorization, permissions, payments, or security-sensitive design.
Multi-tenant behavior.
Large database redesign.
Multiple bounded contexts or applications.
External service integration with unclear requirements.
Broad changes that could affect many flows.
Product/design decisions that are not specified.

Use this format:

Reclassification required: large

Reason:
<why this is not a medium feature>

Recommended delegated skill:
<large_feature>
Output format

Before implementation, output:

Medium feature plan.

Summary:
<what will be implemented>

Affected areas:
- <area 1>
- <area 2>

Planned tests:
- <test file or test area>

Planned documentation updates:
- <doc file or "None">

Planned checks:
- <check 1>
- <check 2>

After implementation, return:

Medium feature implemented.

Summary:
- <change 1>
- <change 2>

Files changed:
- <file 1>
- <file 2>

Tests created/updated:
- <test file or "None">

Documentation updated:
- <doc file or "None">

Implementation summary file:
- <feature_name>.txt

Checks run:
- <command>: passed | failed | not available

Notes:
- <important detail or "None">

If not completed:

Medium feature not completed.

Reason:
<clear explanation>

Files inspected:
- <file 1>
- <file 2>

What is needed:
- <missing detail, dependency, or decision>