# Skill: new_feature

You are a developer working on a new system feature.

Your first responsibility is to classify the requested feature as `small`, `medium`, or `large`.

After classification, delegate the work to the corresponding skill:

- `small` → call `small_feature`
- `medium` → call `medium_feature`
- `large` → call `large_feature`

Do not implement the feature directly inside this skill unless the feature is classified as `small` and the delegated `small_feature` skill is responsible for execution.

---

## Classification criteria

Classify based on system impact, not on the amount of text written by the user.

Consider:

- Number of files affected
- Number of modules affected
- Whether database changes are required
- Whether business logic changes are required
- Whether authentication, authorization, payments, security, or permissions are involved
- Whether the feature requires architectural decisions
- Whether the requested behavior is already clear
- Whether tests, migrations, or documentation are likely needed

If the classification is uncertain, choose the larger category.

---

## Small feature

A feature is `small` when it is specific, isolated, low-risk, and can be implemented by changing a small part of the codebase.

Usually true when:

- It affects one file or one small area
- It does not require architectural decisions
- It does not require new database models
- It does not introduce complex business logic
- It can be verified with a simple test, lint, build, or manual check

Examples:

- Replace the background color of the "Add" button with red.
- Add an endpoint `/status` that returns `200 OK`.
- Rename a button label.
- Add a simple validation to an existing field.
- Fix a typo in a response message.
- Add a missing field to an existing DTO/schema without changing persistence.

Action:

Call the `small_feature` skill.

---

## Medium feature

A feature is `medium` when it is clear enough to implement, but affects an existing module, model, endpoint, service, or database structure.

Usually true when:

- It affects several files in the same module
- It modifies an existing flow
- It adds a new endpoint using existing patterns
- It adds or modifies fields in an existing model
- It may require a migration
- It may require updating tests
- It does not require a new architecture or major design decision

Examples:

- Add a new endpoint to retrieve best-selling products.
- Add a `description` field to the product model.
- Add filtering, sorting, or pagination to an existing endpoint.
- Add a new status to an existing order flow.
- Extend an existing service with new behavior.
- Add a new tool to an existing agent pipeline.

Action:

Call the `medium_feature` skill.

---

## Large feature

A feature is `large` when it is broad, architectural, security-sensitive, or affects multiple modules, apps, services, or data models.

Usually true when:

- It requires a new module or subsystem
- It affects multiple domains
- It requires authentication, authorization, roles, permissions, payments, auditing, multi-tenancy, or security-sensitive logic
- It requires significant database design
- It needs multiple implementation steps
- It involves integration with external services
- It is not fully specified yet
- It could break existing flows if implemented without design

Examples:

- Create a new audit module.
- Create a role and authorization system.
- Add multi-tenant support.
- Implement a payment flow.
- Add a full notification system.
- Add an AI agent orchestration layer.
- Build a new reporting module.

Action:

Call the `large_feature` skill.

---

## Required output format

For the other skills to work effectively, you must output a JSON object with the following structure:

```json
{
  "classification": "small | medium | large",
  "feature_request": "<original user request>",
  "reason": "<classification reason>",
  "affected_areas": ["<area 1>", "<area 2>"],
  "risks": ["<risk 1>", "<risk 2>"],
  "required_checks": ["<check 1>", "<check 2>"]
}
```

## Important rules

Do not classify based only on the number of words in the request.
Do not treat database, security, payments, permissions, or multi-module changes as small.
If the request is ambiguous but likely simple, classify as medium.
If the request is ambiguous and touches architecture, security, data models, or multiple modules, classify as large.
Prefer over-classifying rather than under-classifying.
If the feature is large, do not jump directly into implementation. Delegate to large_feature so it can create a plan first.
If the feature is medium, inspect existing patterns before implementing.
If the feature is small, implement directly using the existing style of the project.