# Skill: large_feature

You are a developer analyzing and planning a large system feature.

This skill is called after `new_feature` classifies the request as `large`.

A large feature is broad, architectural, security-sensitive, or affects multiple modules, domains, services, data models, integrations, or workflows.

---

## Input

```json
{
  "classification": "large",
  "feature_request": "<original user request>",
  "reason": "<classification reason>",
  "affected_areas": ["<area 1>", "<area 2>"],
  "risks": ["<risk 1>", "<risk 2>"],
  "required_checks": ["<check 1>", "<check 2>"]
}
Main rule

Do not implement immediately.

First gather context, understand the existing architecture, identify risks, and create an implementation plan.

Implementation is allowed only after the plan is clear and the feature can be safely broken into smaller steps.

Context gathering

Use the minimum context needed, but more than small_feature or medium_feature.

Start with project guidance files when available:

AGENTS.md
README.md
CONTRIBUTING.md
docs/
.codex/
.env.example

Then inspect technical structure as needed:

Project tree.
Dependency files: requirements.txt, pyproject.toml, Pipfile, poetry.lock.
App entrypoints.
API routes/controllers.
Services/use cases.
Schemas/DTOs.
Models/entities.
Repositories/query layer.
Database migrations.
Configuration files.
Docker files.
CI files.
Existing tests in D:\benja\proyectos\postas_api\tests.

Use search tools when useful:

rg "<feature keyword>"
rg "<model name>"
rg "<endpoint>"
rg "<service name>"
git status
git diff
git log --oneline -n 10

Do not read the whole repository without a reason.

Context sources by feature type

Use these context sources depending on the feature.

API or backend feature

Inspect:

Existing routes/controllers.
Request/response schemas.
Services/use cases.
Repositories.
Tests.
API documentation if available.
Database feature

Inspect:

Models/entities.
Existing migrations.
Repository/query patterns.
Seed/fixture files.
Tests involving persistence.
Authentication, authorization, roles, or permissions

Inspect:

Auth middleware/dependencies.
User model.
Role/permission models.
Token/session logic.
Protected routes.
Security tests.
Configuration related to auth.

Do not implement security-sensitive features without a clear design.

External integration

Inspect:

Existing integrations.
HTTP clients.
Environment variables.
Error handling patterns.
Retry/logging patterns.
Webhook handlers if relevant.
Integration tests or mocks.
Agent or AI feature

Inspect:

Graph/pipeline structure.
Agent nodes.
Tools.
Prompts.
Schemas.
Memory/state handling.
Existing tests.
Multi-module or architecture feature

Inspect:

Module boundaries.
Shared utilities.
Existing architectural patterns.
Dependency direction.
Configuration.
Tests across affected modules.
Planning rules

Create a plan before editing.

The plan must include:

Current behavior.
Desired behavior.
Affected modules.
Data model changes.
API changes.
Migration needs.
Test strategy.
Documentation updates.
Risks.
Implementation phases.

Prefer splitting the feature into smaller tasks that could be handled later by small_feature or medium_feature.

Implementation rules

If implementation proceeds:

Keep changes incremental.
Avoid large rewrites.
Preserve existing architecture unless the feature explicitly requires changing it.
Create or update tests.
Update documentation when behavior, commands, endpoints, schemas, models, or environment variables change.
Use migrations if database schema changes are required.
Do not introduce dependencies unless justified.
Do not modify unrelated code.
Python checks

Prefer targeted tests first:

pytest D:\benja\proyectos\postas_api\tests\path\to\test_file.py

Then run the full test suite if appropriate:

pytest D:\benja\proyectos\postas_api\tests

If available, also run:

ruff check .
mypy .

If the project has a harness, run it after targeted checks:

make codex-check

If a command is not available, do not invent alternatives. Report it as not available.

Documentation rules

Update documentation if the feature changes:

Public API behavior.
Request or response schemas.
Environment variables.
Setup steps.
Commands.
Database models.
Auth/permission behavior.
Agent behavior.
External integration behavior.
Implementation summary file

After planning or implementation, create a .txt file with the same name as the feature.

Use a safe filename:

Lowercase.
Replace spaces with _.
Remove special characters.
End with .txt.

Example:

role_authorization_system.txt

The file must contain:

Feature:
<feature name>

Classification:
large

Context reviewed:
- <file or area>
- <file or area>

Current behavior:
<summary>

Proposed behavior:
<summary>

Implementation plan:
1. <step>
2. <step>
3. <step>

Files changed:
- <file or "None">

Tests created or updated:
- <test file or "None">

Documentation updated:
- <doc file or "None">

Checks run:
- <command>: passed | failed | not available

Risks:
- <risk or "None">

Important notes:
- <note or "None">
Output format before implementation
Large feature context review.

Feature:
<feature request>

Current understanding:
<brief summary>

Context reviewed:
- <file or area>
- <file or area>

Affected areas:
- <area 1>
- <area 2>

Risks:
- <risk 1>
- <risk 2>

Implementation plan:
1. <step>
2. <step>
3. <step>

Suggested breakdown:
- <small/medium task 1>
- <small/medium task 2>

Tests needed:
- <test area>

Documentation updates:
- <doc file or "None">

Implementation summary file:
- <feature_name>.txt
Output format after implementation
Large feature implemented.

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
Output format if not implemented
Large feature not implemented.

Reason:
<clear explanation>

Context reviewed:
- <file or area>
- <file or area>

What is needed:
- <missing requirement, decision, dependency, or design detail>

Recommended next step:
<next action>
Core principle

For large features, prioritize understanding and planning before implementation.

Gather enough context to avoid unsafe architectural decisions, then break the feature into smaller, verifiable changes.