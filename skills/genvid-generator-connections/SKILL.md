---
name: genvid-generator-connections
description: How the boundary's Genvid-runs-it generation path knows which provider and model to use — registered connections, bring-your-own-key, and automatic selection by render type.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Generator Connections

A generator connection is a durable, tenant-scoped configuration record that tells the boundary which external provider and model to route a generation through. It is the routing config — provider, model, endpoint, and transport — for the path where **Genvid runs the generation** on your behalf: platform-run *media* generation (for example, generating a shot's keyframes), billed to your organization. Today that boundary-run generation is triggered platform-side only — the remote MCP surface exposes no generation-invoke tool — but connections still determine which provider and model those platform runs use.

Composition is **not** a Genvid-run path. Screenplay breakdown and storyboard authoring are done by your own agent, which composes the structure and cites verbatim screenplay quotes through the governed write tools (`scenes_write`, `assets_write`, `shots_write`, `storyboard_write`) — Genvid funds no composition inference. Connections govern only the media-generation path where you ask the boundary itself to run a provider.

You do not need a connection for the primary, agent-side path either. If your own agent generates the media locally and hands Genvid the result, no connection is involved — see `genvid-agent-generation`. Reach for connections only when you want the boundary itself to run the provider.

---

## There is no register tool and no select tool over MCP

Two things the boundary does **not** expose as MCP tools, despite older guidance you may have seen:

- **Registration is not an MCP call.** A connection is created through the Genvid REST API (`POST /organizations/{org}/generators`) or the Genvid console, as an administrative step. The MCP boundary has no `register_generator_connection` tool.
- **Selection is automatic.** There is no `select_generator_connection` step and no "active connection" state to set. At dispatch the boundary deterministically picks the enabled connection registered for the generation's `render_type`. You register connections; the boundary selects among them.

If a skill or agent tells you to call `register_generator_connection` or `select_generator_connection`, that guidance is stale — neither tool exists.

---

## Bring-your-own-key (BYOK)

Genvid never owns your provider credentials. A connection references your key by indirection, and the key is resolved per call at invocation time and never returned by the boundary — not over the API (only the last four characters are ever exposed), not retained in logs. Self-hosted deployments resolve the key from their own environment. Hosted-tier tenants store the key once through Genvid's encrypted provider settings — the same store the Genvid web app uses — and generation resolves it per call, scoped to your organization. The boundary holds the routing record plus, for hosted tenants, the encrypted key it decrypts only at the moment of an outbound provider call.

---

## How selection works at dispatch

When a billable generation tool runs, the boundary:

1. Lists the enabled connections for your organization.
2. Filters to those whose `render_type` matches the generation being requested.
3. Picks one deterministically (stable tie-break), and routes the submit through it.

So the contract you control is **which connections are registered and enabled**, not which one is active at call time. To change routing, register or enable the connection you want for that `render_type`; to retire a route, disable its connection.

---

## What gets signed is the connection the boundary selects

For a platform generation, the provider/model of the **enabled connection** the boundary selects for the call's `render_type` is written into the submit-record and bound into the C2PA Content Credentials — you do not pass model identifiers on this path. Confirm the right connection is registered and enabled before you call; there is no correction path after submission — see `genvid-generate-with-provenance`.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Generate locally with your own provider and bind the result (primary path) | `genvid-agent-generation` |
| Have Genvid run the generation, with signed provenance | `genvid-generate-with-provenance` |
| Generate storyboard keyframes through a connection | `genvid-storyboard` |
| Full tool list and classifications | `../../references/boundary-tools.md` |
