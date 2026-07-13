---
name: genvid-propagate-change
description: Propagate an asset or scene change across its full closure of downstream shots and media in one billable call, idempotently.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Propagate Change

## What this skill teaches

When an asset or a scene changes, every downstream shot and media that depends on it becomes stale. This skill covers how to carry that change through the full closure — analyzing impact for the human first, then executing the whole set in one billable call, idempotently.

Two tools are used. One is read-only and free. One is billable. They are not interchangeable.

---

## The source is an `asset` or a `scene` — nothing else

The boundary resolves a change closure from exactly two source types:

| `source_type` | `source_id` | What it means |
|---|---|---|
| `asset` | the asset's UUID | An asset changed. **A character or location change is an asset change** — characters and locations are kinds of asset, so use `source_type="asset"` with that asset's id. |
| `scene` | the scene's integer id (as a string) | A scene changed. |

There is no `shot` or `screenplay` source type for propagation — a screenplay is a document you edit, not a propagation source, and shots are resolved as part of a scene or asset closure, not propagated directly. Passing anything other than `asset` or `scene` is rejected at the boundary.

## Two actions: regenerate, or mark stale

Each source type takes one of two `option` values:

| `option` | `asset` | `scene` | What it does |
|---|---|---|---|
| regenerate the closure | `regenerate_images` | `regenerate_first_frames` | Rebuilds every stale downstream item. Billable — fans out one generation per target. |
| flag downstream stale | `mark_stale` | `mark_stale` | Flags the affected downstream media as out-of-date without rebuilding. Cheap; completes immediately. Use it when you want to record that a rebuild is needed but not spend on it now. |

Those four are the supported `(source_type, option)` pairs. `save_only` is **not** a `propagate_change` option — it means "save the edit and do not propagate," so there is nothing to call. `propagate_change` is `billable` regardless of which option you pass (see Step 2). `analyze_change` returns exactly these options in its `propagation_options` field for the source.

---

## Step 1 — Analyze the impact (read, free)

Call `discovery_read` with `method=analyze_change` to see which targets the change touches.

| Parameter | What to supply |
|---|---|
| `method` | `analyze_change` |
| `source_type` | `asset` or `scene` |
| `source_id` | The asset UUID, or the scene integer id as a string |

`discovery_read` is classified `read_only`. It never bills, never mutates, and never gates. Use it as many times as needed. `analyze_change` is a method of `discovery_read`, not a standalone tool — there is no separate analyze tool.

The response includes counts of the affected closure (`affected_scenes`, `affected_shots`, `affected_media`) and a `details` object. **The `details` lists are capped for human display.** They are not the complete work set — they are a truncated sample suitable for showing the human what will be regenerated. Read the counts; present `details` as a preview.

---

## !! WRONG vs RIGHT — read this before writing any loop !!

This is the single most consequential behavior in this skill. Getting it wrong silently corrupts a large change and bypasses the single-call design.

### WRONG: iterating the capped `details` list

```
# DO NOT DO THIS
result = discovery_read(method="analyze_change", source_type="asset", source_id="...")
for target in result["details"]["shots"]:        # details is CAPPED — not the full closure
    generate_something(target_id=target["id"])    # N separate billable calls, N separate client prompts
```

**Two harms, both silent:**

1. **Truncation corrupts the change.** The `details` lists are capped for human display. If the full closure contains 200 stale shots and the cap returns 10, iterating `details` regenerates only those 10. The remaining 190 are never touched. The production appears updated but is not. No error is raised.

2. **N calls bypass the single-call design.** Splitting the work into one billable call per item means N separate client allow-prompts instead of one. The human cannot review the full closure at once, cost accountability is fragmented across N calls, and the closure is no longer atomic.

The `details` lists are for human display only. They are never a work list. Do not iterate them.

---

### RIGHT: call `propagate_change` once for the whole closure

```
# DO THIS
propagate_change(source_type="asset", source_id="...", option="regenerate_images")
```

`propagate_change` is classified `billable`. Call it once for the whole closure.

When you call `propagate_change`, the boundary re-resolves the full closure server-side from the source entity. It does not use the capped `details` from your `discovery_read` result. The full set — all 200 stale shots in the example above — is included in the work. One call covers the complete closure.

The human sees the total scope and total cost in the one client allow-prompt, and the backend meters the whole set against the project budget in a single decision. The boundary then executes the full closure.

---

## Step 2 — Call `propagate_change` once

`propagate_change` is `billable` (see `genvid-boundary-gate`). Call it normally: your MCP client shows its allow-prompt before the call runs, and the backend enforces the acting user's permission and the project budget — a closure that would exceed the budget is refused pre-spend with HTTP 402. There is no separate step and no approval id. Tell the human what the call will do and that it will spend, so the client allow-prompt is informed. If the backend returns an error (402 over-budget, permission denied), surface it; the closure was not performed, so do not retry blindly.

| Parameter | What to supply |
|---|---|
| `source_type` | `asset` or `scene` |
| `source_id` | The asset UUID, or the scene integer id as a string |
| `option` | Regenerate: `regenerate_images` (asset) / `regenerate_first_frames` (scene). Or flag stale: `mark_stale` (either source). |

---

## Step 3 — Idempotency

`propagate_change` is designed to be called once for the whole closure. The boundary re-resolves the full closure server-side from the source entity at execution time, so the complete set of stale targets is always included regardless of what the `details` preview showed. One call covers the entire closure in a single execution.

---

## The contract in three lines

1. `discovery_read(method=analyze_change, source_type, source_id)` — show the human the impact. Free. The `details` are a capped preview, never a work list.
2. `propagate_change(source_type, source_id, option)` — re-resolves the full closure server-side. Billable; your client prompts to allow it and the backend enforces budget + permission. Use `regenerate_images`/`regenerate_first_frames` to rebuild, or `mark_stale` to flag downstream stale without rebuilding.
3. Call it once. The boundary executes the whole closure.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Understand how billable/destructive calls are controlled | `genvid-boundary-gate` |
| Understand signed provenance on each regenerated item | `genvid-generate-with-provenance` |
| Review the full tool surface and classifications | `../../references/boundary-tools.md` |
