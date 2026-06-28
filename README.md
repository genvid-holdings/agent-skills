# Genvid Skills Pack

## What this is

This is the Genvid reference skill pack: a runtime-agnostic [Agent Skills](https://agentskills.io) (`SKILL.md`) pack that teaches any MCP-capable agent to drive the Genvid governed boundary out of the box.

The pack carries no tenant data. Each skill describes how to call the Genvid boundary — orienting the agent, connecting to generators, generating with provenance, gating destructive operations, propagating changes, and driving the production workflow from screenplay through storyboard. The pack version is matched to the boundary via `boundary_compat` in `pack.json`; see Compatibility below.

## Install

**Claude Code:**

```
/plugin marketplace add genvid-holdings/genvid-skills
/plugin install genvid-skills@genvid-skills
```

**Other runtimes** (Codex, Gemini CLI, Cursor, OpenHands, and any other agent that loads skills from a directory):

Clone the repo and place the `skills/` folder where your agent loads skills:

```sh
git clone https://github.com/genvid-holdings/genvid-skills.git
# then point your agent at genvid-skills/skills/
```

Note: `.claude-plugin/` is a Claude Code convenience shim and is ignored by other runtimes. The pack itself is not Claude-only — all skill content lives in `skills/` and is runtime-agnostic.

## Connecting your agent to a Genvid boundary

Installing the pack teaches your agent *how* to drive the boundary; connecting points it at a live Genvid MCP server. Connection uses a standard OAuth browser login — your agent signs in the same way you sign in to the Genvid web app. There is no API key or JWT to paste.

**Claude Code:**

```
claude mcp add --transport http genvid https://<your-genvid-host>/mcp
```

On first use your agent opens a browser to the Genvid sign-in, you approve the access request, and the agent receives and refreshes the token on its own. Every call then runs under your Genvid identity, with row-level security applied — see the `genvid-orientation` skill.

The flow is standard OAuth 2.1 with PKCE and dynamic client registration (RFC 7591 / RFC 9728), so any MCP client that supports browser login (Claude Code, Cursor, and others) connects the same way — point it at `https://<your-genvid-host>/mcp`.

## Fork & extend

Fork the public repo, add your own skills alongside the reference ones, and fill in `AGENTS.md` with your studio's house rules (naming conventions, tightened gates, show-specific prompt conventions). The reference skills in `skills/` are unchanged and continue to teach the boundary; your additions layer on top.

## Compatibility

The `version` field in `pack.json` is matched to a boundary release via `boundary_compat`. At runtime, agents can check the `boundary_contract_version` field exposed over MCP to confirm the pack and boundary are compatible before making calls.

```json
{
  "boundary_compat": ">=0.1.0 <0.2.0"
}
```

When the boundary ships a breaking change the minor version increments, `boundary_compat` narrows, and the pack version bumps. Pin to a pack version in your deployment if you need stability across boundary upgrades.
