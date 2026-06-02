---
name: delivery_review
description: "Use this skill after implementing a feature to run a multi-agent delivery workflow: test creation/update, code review, checks, and optional git commit."
---

# Skill: delivery_review

You are responsible for closing a feature safely after implementation.

Use this skill after `small_feature`, `medium_feature`, or `large_feature` has made code changes.

## Main workflow

1. Inspect `git status --short`.
2. Inspect the current diff.
3. Spawn subagents in parallel:
   - `test_engineer`: inspect changed behavior, find missing coverage, and create or update tests when necessary.
   - `code_reviewer`: review the diff for bugs, regressions, security, tenant isolation, permissions, migrations, and missing tests.
4. Wait for all subagents to finish.
5. Summarize their findings.
6. Fix blocker/high issues before testing.
7. If `test_engineer` created or updated tests, include those files in the final summary.
8. Run targeted tests first.
9. Run broader checks when appropriate.
10. If the user explicitly requested a commit, spawn `commit_preparer`.
11. Commit only if checks pass and the commit is safe.

## Test command priority

Prefer targeted tests first:

```bat
pytest D:\benja\proyectos\postas_api\tests\path\to\test_file.py
```

Then, when appropriate:

pytest D:\benja\proyectos\postas_api\tests

If available:

ruff check .
mypy .

If a command is unavailable, report it as not available. Do not invent commands.

Commit rules

Only commit when the user explicitly asks for it.

Before committing:

Run git status --short.
Run git diff --check.
Verify no secret or local-only file is included.
Verify tests passed, unless the user explicitly requested a WIP commit.
Stage only files related to the implemented feature.
Use a conventional commit message.

Never commit:

.env
credentials
tokens
local database files
cache files
unrelated generated files
unrelated formatting changes
Output format

Delivery review completed.

Subagent results:

test_engineer:
<summary>
code_reviewer:
<summary>
commit_preparer:
<summary or "Not used">

Tests created/updated:

<test file or "None">

Fixes after review:

<fix or "None">

Checks run:

<command>: passed | failed | not available

Commit:

Created: yes | no
Message: <message or "None">
Reason if not committed: <reason or "None">