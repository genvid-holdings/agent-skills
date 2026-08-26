# Genvid Skills Pack

## What this is

This is the Genvid reference skill pack: a runtime-agnostic [Agent Skills](https://agentskills.io) (`SKILL.md`) pack that teaches any agent that loads Agent Skills to drive the Genvid governed boundary out of the box.

The pack carries no tenant data. Each skill describes how to call the Genvid boundary: orienting the agent, connecting to generators, generating with provenance, gating destructive operations, propagating changes, and driving the production workflow from screenplay through storyboard. The pack version is matched to the boundary via `boundary_compat` in `pack.json`; see Compatibility below.

Two skills are the exception. **`genvid-article50-readiness`** drives no boundary tool at all and runs entirely offline: start there if you have never heard of Genvid. **`genvid-roblox-studio-ops`** drives Roblox Studio directly over its own built-in MCP server, not the Genvid boundary.

## Article 50 readiness (no account, no network)

Article 50 of the EU AI Act ([Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj)) applies from **2 August 2026**. It puts transparency duties on the providers and deployers of systems that generate or manipulate media: machine-readable marking of synthetic output, and disclosure of deep fakes.

`skills/genvid-article50-readiness/` ships a standalone CLI that audits a local directory of assets against those duties and emits two artifacts: a **machine-readable disclosure report** (JSON, one record per asset) and a **gap list** (Markdown, one entry per unresolved item with the remediation that closes it).

```sh
git clone https://github.com/genvid-holdings/agent-skills.git
python3 agent-skills/skills/genvid-article50-readiness/article50_scan.py /path/to/production -o ./article50-out
```

**No Genvid account, no sign-up, no upload, no network call, and no dependency outside the Python 3.9+ standard library.** Your material never leaves the machine. Exit status is `0` when every file was read and no gaps were recorded, `1` when at least one gap was, and `2` when the scan could not run or could not finish: a bad path, an unreadable declaration, or artifacts that could not be delivered. So it works as a delivery gate in CI, and `2` is the code that must not be read as "gaps found": there is no usable report behind it.

It reads what each file actually carries: content credentials (JPEG APP11 JUMBF, PNG `caBX`, WebP `C2PA` chunk, BMFF `uuid` box, `.c2pa` sidecars), the IPTC digital source type in XMP, and generator metadata left by common pipelines. It reconciles that against an operator-authored `article50.json` declaration ([format](skills/genvid-article50-readiness/DECLARATION.md)).

It also keeps two things apart that are commonly conflated: Article 50(2) requires marking **and** detectability, not just marking; and a machine-readable marking does not discharge the Article 50(4) deep-fake disclosure duty, because such markings are not clear and distinguishable to the people exposed to the content. A signed manifest with no on-screen disclosure is reported as the gap it is. Article 50(2)'s own exception is modelled as well, because post-production meets it constantly: declare `assistive_editing` where the system performed an assistive function for standard editing or did not substantially alter the input data or its semantics (AI denoise, upscale and cleanup), and the marking duty is recorded as disapplied for that asset instead of asserted against it. That is a declaration, recorded and never verified. The paragraph's law-enforcement clause is not modelled at all, and the report's limits say so.

**What it does not do.** It reports evidence and the absence of evidence. It does not determine compliance, and its output is not legal advice. That turns on facts a file scan cannot see. It does not assess imperceptible watermarks, because detecting one requires the detector matching the embedder; a watermark can be declared in the declaration but is never confirmed here. Its content-credential detection is presence-only: finding a manifest says nothing about whether the signature validates or whether the signer is one anyone downstream recognizes. Absence of a signal is not evidence of a camera: embedded metadata does not survive a transcode or a re-encode, so unmarked assets are reported as undetermined rather than guessed at. And the formats it reads are industry conventions: neither content credentials nor the IPTC digital source type is named in the Regulation, the Commission's guidelines, or the code of practice, none of which mandates a particular standard. The full scope limits are in the skill's [SKILL.md](skills/genvid-article50-readiness/SKILL.md) and are printed in every report.

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

Note: `.claude-plugin/` is a Claude Code convenience shim and is ignored by other runtimes. The pack itself is not Claude-only: all skill content lives in `skills/` and is runtime-agnostic.

## Model requirements

The pack puts creative and structural judgment on your agent, not on the boundary.
Breakdown, beat and shot decomposition, and asset authoring are yours: the boundary
validates and records what you author, it does not infer it for you.

These skills need a high-reasoning model with a large context window, running with the
strongest reasoning setting your runtime exposes. Faster, cheaper, or low-reasoning
models tend to fail in two specific ways. They paraphrase content anchors instead of
quoting the screenplay verbatim, and the boundary rejects those. And they
under-decompose scenes, producing coverage that does not hold up. Because
`propagate_change` and the generation paths are billable and gated, weak reasoning
costs money as well as quality.

The offline `genvid-article50-readiness` scan is the exception: it drives no boundary
tool and has no model requirement.

## Connecting your agent to a Genvid boundary

Installing the pack teaches your agent *how* to drive the boundary; connecting is a separate, explicit step that points it at the live Genvid MCP server and logs it in. There is no API key or JWT to paste: Genvid is a single, multitenant server (`mcp.genvid.com`); tenant scoping comes from your signed-in identity and row-level security, not from a per-customer host.

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
   This only writes the config; it does not log you in.
2. Log in: inside a Claude Code session, run `/mcp` and follow the browser OAuth prompt (or run `claude mcp login genvid` from the CLI for a headless flow). Claude Code opens a browser to the Genvid sign-in, you approve the access request, and the agent receives and refreshes the token on its own.

Every call then runs under your Genvid identity, with row-level security applied; see the `genvid-orientation` skill.

The flow is standard OAuth 2.1 with PKCE and dynamic client registration (RFC 7591 / RFC 9728), so any MCP client that supports browser login (OpenAI Codex, Claude Code, Cursor, and others) connects the same way: point it at `https://mcp.genvid.com` and complete that client's equivalent login step.

## The `genvid` CLI: required to bind locally-generated files

The skills + MCP connection above cover everything **except one path**: binding media your agent generated to a **local file** (OpenAI Codex's built-in image generation, a local ComfyUI; anything that writes bytes to disk rather than returning a hosted provider URL). The MCP server is remote and cannot read your disk, and a full-resolution file is too large to pass reliably through an MCP message payload, so this bind runs through the `genvid` CLI, which streams the file losslessly from the machine that holds it.

If your agent only uses hosted-URL providers (FAL and most cloud generators), you don't need the CLI: `ingest_generated_media` with `source_url` covers you. Install it when you need the local-file path:

```sh
brew install genvid-holdings/genvid/genvid   # macOS/Linux (Homebrew)
# or the install script:
curl -fsSL https://github.com/genvid-holdings/genvid-cli/releases/latest/download/install.sh | sh
```

Then log in once (browser OAuth, same identity as your MCP connection):

```sh
genvid login
```

The `genvid-agent-generation` skill drives the rest: it routes a local file to `genvid import-generated-media <project> -c multipart 'rendered_output: @<path>'`, which binds the bytes byte-for-byte and signs the same attested provenance as the MCP tool.

## Fork & extend

Fork the public repo, add your own skills alongside the reference ones, and fill in `AGENTS.md` with your studio's house rules (naming conventions, tightened gates, show-specific prompt conventions). The reference skills in `skills/` are unchanged and continue to teach the boundary; your additions layer on top.

## Compatibility

The `version` field in `pack.json` is matched to a boundary release via `boundary_compat`. The boundary reports its own contract version as `serverInfo.version` in the MCP `initialize` handshake, so an agent can read it at runtime and confirm the pack and the boundary are compatible before making calls.

```json
{
  "boundary_compat": ">=0.5.0 <0.6.0"
}
```

When the boundary ships a breaking change the minor version increments, `boundary_compat` narrows, and the pack version bumps. Pin to a pack version in your deployment if you need stability across boundary upgrades.

Every version bump to `pack.json` must be mirrored in `.claude-plugin/marketplace.json`'s self-referencing plugin entry (`source: "./"`): `scripts/validate_pack.py` enforces this in CI, but if you fork the pack and drop that check, know that a stale marketplace version makes `claude plugin update` silently report "already at the latest version".

The range is checked against a real boundary, not just asserted here. `scripts/boundary_client.py` is a stdlib-only MCP client that reads the contract version off the `initialize` handshake and the tool surface off `tools/list`. Gate 2 in `scripts/smoke_test.py` loads `boundary_compat` from `pack.json` and, when `BOUNDARY_URL` points at a boundary, fails on a missing tool, a drifted parameter, or a contract version outside the declared range. With no boundary configured it reports `SKIPPED` and exits zero, which is neither a pass nor a failure: there is nothing to validate against.
