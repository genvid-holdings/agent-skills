---
name: genvid-boundary-gate
description: How a billable or destructive boundary call is controlled — your MCP client asks you to allow the tool, and the backend enforces permission and budget.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Boundary Controls

## Why some calls are controlled

Some boundary calls cost money (`billable` — they run generations) or change existing data irreversibly (`destructive` — they overwrite or remove). Read-only and additive `create_*` calls run freely. The `billable` and `destructive` classifications are an **informational risk signal** so you know which calls spend or overwrite. See `genvid-orientation` for the classification surface.

There is no bespoke server-side approval step inside the boundary, and no separate web page to visit. A controlled call is governed by exactly two things: your MCP client's own tool-permission prompt, and the backend.

---

## How a billable or destructive call is controlled

You call the tool **normally**, with the parameters you intend. You do not call a separate propose or approve tool, and there is no approval id to pass. Two layers act:

1. **Your MCP client asks you to allow the tool.** Exactly like any standard MCP server (the same prompt you get for, say, Supabase's MCP), your client shows its native tool-use permission prompt — "allow this tool? once / always / deny" — before the call runs. That prompt is where the human decides. Answer it in the client you are already in.

2. **The backend enforces permission and budget.** When the call reaches the Genvid REST API, the API checks the acting user's permission (RBAC) and the project's budget. A billable generation that would push the project over its budget is **refused before any spend** with an HTTP 402. A call the user is not permitted to make is refused with a permission error. These checks are server-side truth — they hold no matter how the client prompt was answered.

If the backend refuses, the tool returns that error (e.g. a 402 over-budget or a permission error). **Surface it to the human** — say plainly that the action was not performed and why, and ask how they want to proceed. Do not retry the same call expecting a different result.

---

## What you, the agent, do

1. **Before a billable call, tell the human what it will do.** Summarize the scope and that it will spend (for example "this regenerates 12 keyframes"). This makes the client's allow prompt an informed decision.
2. **Call the tool once, normally.** Do not invent an approval step or pass an approval id.
3. **If the backend returns an error** (402 over-budget, permission denied, ...), surface it. The action did not happen; tell the human what was refused and why.

---

## Two backstops you can rely on

- **Budget.** Billable generation is bounded by the project's budget on the server. A run that would exceed it is refused pre-spend with HTTP 402 — spend cannot run away. This matters most when the human has clicked "always allow" in their client: the allow prompt no longer pauses, so the project budget is the backstop that bounds spend.
- **Audit.** Every billable or destructive action is recorded in the `entity_events` audit log, attributed to the acting user and tagged `change_source='agent'` when it came through an agent. An admin can reconstruct exactly what happened, who did it, and when.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Run a closure regeneration via `propagate_change` | `genvid-propagate-change` |
| Generate with signed provenance | `genvid-generate-with-provenance` |
| Understand the full tool surface and classifications | `../../references/boundary-tools.md` |
