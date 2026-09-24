"""The pre-spend budget gate.

Every spending step checks the caller's estimate against the Genvid budget
before anything is generated (genvid-agent-generation/SKILL.md, Step 0b: the
check is required for every generation, a free one included). The check is the
generation-budget headroom read (`production_read` `check_generation_budget` on
the MCP side), which this runner makes itself with
`genvid get-generation-budget-headroom` and records at `m["budget"][<key>]`
with the command, the raw response and the time it was read. Only a literal
`fits: true` in that response clears it; a response that does not answer the
estimate asked about is refused. A refusal is recorded too, and read again on
the next call, so a raised budget clears it without touching the manifest. A
recorded verdict clears only through its own read (`_holds`): a `fits: true`
with no read behind it is ignored and read again.

A verdict covers what it was gated for. `gate()` records the estimate, the
model the caller named (if any) and the item set; an emit that changes any of
them drops the verdict with a note and gates again.
"""
from decimal import Decimal, InvalidOperation
import manifest, genvid_bind, cost

# The first genvid CLI release carrying `get-generation-budget-headroom`.
MIN_CLI_VERSION = "0.0.5"


class BudgetError(RuntimeError):
    """Raised when a spending step is refused by the pre-spend budget gate, or
    its budget read failed."""
    pass


def _argv(m, estimated_cost_usd):
    argv = ["genvid", "get-generation-budget-headroom", str(m["project_id"]), str(estimated_cost_usd)]
    if m.get("asset_id"):
        argv += ["--asset-id", str(m["asset_id"])]
    return argv


def _holds(entry, m, estimated_cost_usd):
    """A recorded verdict clears only when it carries its own read, that read
    asked this question (same project, estimate and asset), and the read's own
    response says `fits: true`. A `fits: true` with no read behind it -- written
    by hand, or by the payload-era gate -- does not hold and is read again."""
    read = (entry or {}).get("read")
    return (entry.get("fits") is True and isinstance(read, dict)
            and read.get("command") == _argv(m, estimated_cost_usd)
            and isinstance(read.get("response"), dict) and read["response"].get("fits") is True)


def _read_verdict(m, key, estimated_cost_usd, extra):
    """Read the headroom for `estimated_cost_usd` and record the verdict with
    its provenance. A read that fails, or that answers a different estimate or
    no asset headroom for an asset check, raises BudgetError and records nothing."""
    asset_id = m.get("asset_id")
    argv = _argv(m, estimated_cost_usd)
    try:
        read = genvid_bind.cli_read(argv)
    except genvid_bind.GenvidCommandMissing:
        raise BudgetError("budget check for %r: genvid CLI %s or newer is required (installed: %s); "
                          "upgrade with `brew upgrade genvid` or install.sh"
                          % (key, MIN_CLI_VERSION, genvid_bind.cli_version()))
    except genvid_bind.GenvidReadError as e:
        raise BudgetError("budget check for %r could not be read: %s" % (key, e))
    resp, cmd = read["response"], " ".join(read["command"])
    checked = (resp.get("project") or {}).get("estimated_cost_usd")
    try:
        same = Decimal(str(checked)) == Decimal(str(estimated_cost_usd))
    except (InvalidOperation, ValueError):
        same = False
    if not same:
        raise BudgetError("budget check for %r: `%s` answered for estimate %r, not %r; refusing it"
                          % (key, cmd, checked, estimated_cost_usd))
    if asset_id and not isinstance(resp.get("asset"), dict):
        raise BudgetError("budget check for %r: `%s` answered no asset headroom for asset %s; refusing it"
                          % (key, cmd, asset_id))
    if not isinstance(resp.get("fits"), bool):
        raise BudgetError("budget check for %r: `%s` answered no boolean fits: %r" % (key, cmd, resp.get("fits")))
    entry = dict({"estimated_cost_usd": estimated_cost_usd, "fits": resp["fits"],
                  "refusal": resp.get("refusal"), "read": read}, **extra)
    m.setdefault("budget", {})[key] = entry
    manifest.save(m)
    return entry


def _check_verdict(entry, key):
    if entry.get("fits") is not True:
        raise BudgetError("budget: %s" % (entry.get("refusal") or "%r has no fits: true verdict" % key))


def budget_gate(m, stage, estimated_cost_usd):
    """Gate `stage` on `estimated_cost_usd` (a USD decimal string). A recorded
    verdict is kept only while it `_holds` for this estimate; otherwise the
    headroom is read again."""
    entry = (m.get("budget") or {}).get(stage)
    if entry is None or not _holds(entry, m, estimated_cost_usd):
        entry = _read_verdict(m, stage, estimated_cost_usd, {})
    _check_verdict(entry, stage)


def gate(m, key, estimate_usd, model=None, items=None):
    """The emit-side gate: `estimate_usd` is the caller's estimate for this request.

    The verdict is keyed on `{estimate, model, items}`. A verdict recorded without
    that key (written for a different spend) is gated again. Returns the budget
    entry, whose `read` and `estimated_cost_usd` the request document carries.
    """
    estimate = cost.validate_amount(estimate_usd)
    gated_for = {"estimate": estimate, "model": model, "items": sorted(items or [])}
    entry = (m.get("budget") or {}).get(key)
    if entry is not None and "fits" in entry and entry.get("gated_for") != gated_for:
        manifest.note(m, "budget %s: verdict was for %r, not %r; gating again"
                         % (key, entry.get("gated_for"), gated_for))
        entry = None
    if entry is None or not _holds(entry, m, estimate):
        entry = _read_verdict(m, key, estimate, {"gated_for": gated_for})
    _check_verdict(entry, key)
    return entry
