# Genvid Skills Pack

## What this is

This is the Genvid reference skill pack: a runtime-agnostic [Agent Skills](https://agentskills.io) (`SKILL.md`) pack that teaches any MCP-capable agent to drive the Genvid governed boundary out of the box.

The pack carries no tenant data. Each skill describes how to call the Genvid boundary — orienting the agent, connecting to generators, generating with provenance, gating destructive operations, propagating changes, and driving the production workflow from screenplay through storyboard. The pack version is matched to the boundary via `boundary_compat` in `pack.json`; see Compatibility below.

## Install

**Claude Code:**

```
claude plugin marketplace add genvid-holdings/agent-skills
claude plugin install genvid-skills@genvid-skills
```

**OpenAI Codex:**

Codex loads user skills from `~/.agents/skills`. Clone this repository, then copy
or symlink each skill directory into that location:

```sh
git clone https://github.com/genvid-holdings/agent-skills.git
mkdir -p ~/.agents/skills
ln -s "$PWD/agent-skills"/skills/genvid-* ~/.agents/skills/
```

Restart Codex if the new skills do not appear immediately. In the Codex CLI or
IDE extension, run `/skills` or type `$genvid-` to invoke a Genvid skill
explicitly.

**Other runtimes** (Gemini CLI, Cursor, OpenHands, and any other agent that loads skills from a directory):

Clone the repo and place the `skills/` folder where your agent loads skills:

```sh
git clone https://github.com/genvid-holdings/agent-skills.git
# then point your agent at agent-skills/skills/
```

Note: `.claude-plugin/` is a Claude Code convenience shim and is ignored by other runtimes. The pack itself is not Claude-only — all skill content lives in `skills/` and is runtime-agnostic.

## Connecting your agent to a Genvid boundary

Installing the pack teaches your agent *how* to drive the boundary; connecting is a separate, explicit step that points it at the live Genvid MCP server and logs it in. There is no API key or JWT to paste — Genvid is a single, multitenant server (`mcp.genvid.com`); tenant scoping comes from your signed-in identity and row-level security, not from a per-customer host.

**OpenAI Codex:**

```sh
codex mcp add genvid --url https://mcp.genvid.com
```

If Codex does not start the browser login during `mcp add`, run:

```sh
codex mcp login genvid
```

After authentication, run `codex mcp list` to confirm the server is enabled.
The ChatGPT desktop app, Codex CLI, and Codex IDE extension share this local
MCP configuration for the same Codex host. In the Codex TUI, use `/mcp` to view
connected servers.

**Claude Code:**

1. Register the server:
   ```
   claude mcp add --transport http genvid https://mcp.genvid.com
   ```
   This only writes the config — it does not log you in.
2. Log in: inside a Claude Code session, run `/mcp` and follow the browser OAuth prompt (or run `claude mcp login genvid` from the CLI for a headless flow). Claude Code opens a browser to the Genvid sign-in, you approve the access request, and the agent receives and refreshes the token on its own.

Every call then runs under your Genvid identity, with row-level security applied — see the `genvid-orientation` skill.

The flow is standard OAuth 2.1 with PKCE and dynamic client registration (RFC 7591 / RFC 9728), so any MCP client that supports browser login (OpenAI Codex, Claude Code, Cursor, and others) connects the same way — point it at `https://mcp.genvid.com` and complete that client's equivalent login step.

## The `genvid` CLI — required to bind locally-generated files

The skills + MCP connection above cover everything **except one path**: binding media your agent generated to a **local file** (OpenAI Codex's built-in image generation, a local ComfyUI — anything that writes bytes to disk rather than returning a hosted provider URL). The MCP server is remote and cannot read your disk, and base64 corrupts a full-resolution image, so this bind runs through the `genvid` CLI, which streams the file losslessly from the machine that holds it.

If your agent only uses hosted-URL providers (FAL and most cloud generators), you don't need the CLI — `ingest_generated_media` with `source_url` covers you. Install it when you need the local-file path:

```sh
brew install genvid-holdings/genvid/genvid   # macOS/Linux (Homebrew)
# or the install script:
curl -fsSL https://github.com/genvid-holdings/genvid-cli/releases/latest/download/install.sh | sh
```

Then log in once (browser OAuth, same identity as your MCP connection):

```sh
genvid login
```

The `genvid-agent-generation` skill drives the rest — it routes a local file to `genvid import-generated-media <project> -c multipart 'rendered_output: @<path>'`, which binds the bytes byte-for-byte and signs the same attested provenance as the MCP tool.

## Fork & extend

Fork the public repo, add your own skills alongside the reference ones, and fill in `AGENTS.md` with your studio's house rules (naming conventions, tightened gates, show-specific prompt conventions). The reference skills in `skills/` are unchanged and continue to teach the boundary; your additions layer on top.

## Compatibility

The `version` field in `pack.json` is matched to a boundary release via `boundary_compat`. At runtime, agents can check the `boundary_contract_version` field exposed over MCP to confirm the pack and boundary are compatible before making calls.

```json
{
  "boundary_compat": ">=0.2.0 <0.3.0"
}
```

When the boundary ships a breaking change the minor version increments, `boundary_compat` narrows, and the pack version bumps. Pin to a pack version in your deployment if you need stability across boundary upgrades.

Every version bump to `pack.json` must be mirrored in `.claude-plugin/marketplace.json`'s self-referencing plugin entry (`source: "./"`) — `scripts/validate_pack.py` enforces this in CI, but if you fork the pack and drop that check, know that a stale marketplace version makes `claude plugin update` silently report "already at the latest version" (#1667).

**Caveat (as of #1966):** the range above is narrowed to match the pack's own `0.2.0` version per this policy, but that match is not yet CI-verified against a live boundary. `get_boundary_contract()` and a `boundary_client` module don't exist on the boundary side yet, so Gate 2 in `scripts/smoke_test.py` still SKIPS instead of checking the real contract version (see the comment near that check). Treat the narrowed range as a documentation-correctness fix, not a verified compatibility claim, until that gate goes live.
