---
name: genvid-orientation
description: Read first. How to drive the Genvid governed boundary — authenticate with your JWT, discover tools, and the cardinal rules for reads, controlled writes, and provenance.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Genvid Orientation

Read this before invoking any other skill. It establishes the contract every agent must understand before touching the Genvid governed boundary.

---

## What the boundary is

Genvid exposes its production capabilities as a governed boundary over MCP (and REST). Any MCP-capable agent can drive it. Tools are discovered via MCP; the live surface is method-based — for example, `screenplay_read(method=…)` for reads and `screenplay_write(method=…)` for mutations. The naming pattern holds across the boundary: `*_read` tools are free, and `*_write` tools mutate. Classification on a `*_write` tool is per method: a method that only adds new state (the `create_*` methods, e.g. `production_write(method=create_project)`) is additive, while a method that overwrites or removes existing state (the `update_*` methods) is `destructive`.

A call's classification — `billable` (spends) or `destructive` (overwrites/removes) — is an informational risk signal, not identifiable by name alone: a `*_write` tool's overwriting methods are `destructive` while its `create_*` methods are additive, and billable tools such as `breakdown_assets` have their own names. Check each tool's classification in `references/boundary-tools.md`.

For the full tool list, classifications, and parameter shapes, see `references/boundary-tools.md`.

---

## Cardinal rules

Follow these without exception on every call:

- **Your JWT is the security boundary.** Every call runs under your JWT. The boundary enforces row-level security (RLS) — you can only see and touch what your token is scoped to. There is no elevation path within these skills.

- **Reads are free.** `*_read` tools run immediately. No cost.

- **`billable` and `destructive` calls are controlled by your client plus the backend.** Call the tool normally. Your MCP client shows its own native tool-permission prompt ("allow this tool? once / always / deny") before the call runs — exactly like any standard MCP server — and that is where the human decides. The backend then enforces the acting user's permission (RBAC) and the project budget: a billable run that would exceed the budget is refused pre-spend with HTTP 402. There is no separate web step, no approval id. If the backend returns an error, surface it to the human. See `genvid-boundary-gate`.

- **Provenance is attested on every signed media — two paths.** The primary path is agent-side: your own agent generates locally (its own provider key, which never reaches Genvid), and you bind the result with `ingest_generated_media`; Genvid signs it `externally_attested`. See `genvid-agent-generation`. The secondary path is Genvid-runs-it: a billable generation tool routes through a registered connection and Genvid signs `genvid_witnessed`. See `genvid-generate-with-provenance`. Either way the boundary captures provenance at the point of creation — you do not instrument it yourself.

- **Speak OMC vocabulary.** The boundary and its tooling use canonical OMC terminology. Required preferred terms include: keyframe, character, project, storyboard, tone. See `references/omc-vocabulary.md` for the full avoid→use table. Using a banned term surfaces as a validation failure at the boundary.

---

## Read posture: what the boundary does and does not protect

Reads are free. A studio running its own agent against the boundary accepts that a compromised or careless skill can read everything the JWT is scoped to — data exfiltration within scope is a studio-side risk. The boundary's guarantees are on writes, billing, and provenance integrity — not on read confidentiality. Design your skills accordingly: do not assume that restricting write access is sufficient to protect sensitive project data.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Run a controlled (billable or destructive) call | `genvid-boundary-gate` |
| Generate locally with your own provider and bind the result (primary) | `genvid-agent-generation` |
| Have Genvid run the generation, with signed provenance | `genvid-generate-with-provenance` |
| Full tool list and parameter reference | `references/boundary-tools.md` |
| OMC vocabulary quick reference | `references/omc-vocabulary.md` |
