"""The caller-attested cost of a generation, as every ingest records it and every
bind attests it.

The runner never prices a call. The caller generated with a model and provider
of its own choosing and reports what that cost; ingest records it here, and the
bind sends it to Genvid as `attested_cost_amount` / `attested_cost_currency`.

A cost record is one of two shapes:

    {"amount": "0.0800", "currency": "USD"}   what the caller attests it paid
    {"unobserved": True}                       charged, but the figure is not known
                                               (also: not separately charged, the spend
                                               is on another row; see params.runner.cost_source)

An unobserved cost is bound with BOTH attested fields omitted, which the
boundary records as unknown. It is never written as "0": zero is a claim that
the generation was free. Only USD counts toward project spend and budget
headroom (Genvid holds no exchange rate), so a non-USD record is stored and
signed verbatim but does not reduce headroom.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

FOUR_PLACES = Decimal("0.0001")

# The only sanctioned zero: a bind with no generation behind it (a local
# Blender step, or a re-bind of bytes whose cost another row already attests).
# Stages reference it by name so that no cost literal is written anywhere else.
NO_VENDOR_CALL = "0"

# The marker for a generation that was charged but whose cost is not known.
COST_UNOBSERVED = "unobserved"

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class CostError(ValueError):
    """An attested cost that cannot be recorded as given."""


def quantize(value):
    """A Decimal (or decimal string) as a 4-place decimal string."""
    return str(Decimal(value).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP))


def validate_amount(amount):
    """`amount` as a non-negative 4-place decimal string; raises CostError otherwise."""
    if not isinstance(amount, str) or not amount.strip():
        raise CostError("attested cost must be a non-empty decimal string, got %r" % (amount,))
    try:
        value = Decimal(amount.strip())
    except InvalidOperation:
        raise CostError("attested cost %r is not a decimal number" % amount)
    if not value.is_finite():
        raise CostError("attested cost %r is not a finite number" % amount)
    if value < 0:
        raise CostError("attested cost %r is negative" % amount)
    return quantize(value)


def validate_currency(currency):
    """`currency` if it is an ISO 4217 code (three uppercase letters); raises CostError otherwise."""
    if not isinstance(currency, str) or not _CURRENCY_RE.match(currency):
        raise CostError("currency must be an ISO 4217 code (three uppercase letters), got %r" % (currency,))
    return currency


def record(amount, currency="USD", unobserved=False):
    """The cost record for an ingest: exactly one of `amount` and `unobserved`."""
    if unobserved:
        if amount is not None:
            raise CostError("give an attested cost or mark it unobserved, not both")
        return {"unobserved": True}
    if amount is None:
        raise CostError("no attested cost: pass --cost <amount> or --cost-unobserved")
    return {"amount": validate_amount(amount), "currency": validate_currency(currency)}


def no_vendor_call():
    """The record for a bind with no generation behind it."""
    return record(NO_VENDOR_CALL)


def is_unobserved(rec):
    return bool(isinstance(rec, dict) and rec.get("unobserved") is True)


def check_record(rec):
    """`rec` normalised if it is a well-formed cost record; raises CostError otherwise."""
    if not isinstance(rec, dict):
        raise CostError("cost record must be an object, got %r" % (rec,))
    if "unobserved" in rec:
        if rec != {"unobserved": True}:
            raise CostError("an unobserved cost record carries nothing else: %r" % (rec,))
        return {"unobserved": True}
    if set(rec) != {"amount", "currency"}:
        raise CostError("cost record needs exactly amount and currency: %r" % (rec,))
    return record(rec["amount"], rec["currency"])


def _is_record(value):
    return isinstance(value, dict) and isinstance(value.get("cost"), dict)


def records_on(m):
    """Yield `(path, record)` for every ingest record on the manifest.

    Records live at `stages.<stage>.generated.<item>`,
    `stages.<stage>.props.<prop>.generated.<item>` and
    `stages.<stage>.fetched.<ref>`. A record is a dict carrying a `cost` dict;
    older keys such as `cost_usd` are not records and are skipped.
    """
    for stage, entry in sorted((m.get("stages") or {}).items()):
        if not isinstance(entry, dict):
            continue
        for item, rec in sorted((entry.get("generated") or {}).items()):
            if _is_record(rec):
                yield "%s.generated.%s" % (stage, item), rec
        for prop, pentry in sorted((entry.get("props") or {}).items()):
            if not isinstance(pentry, dict):
                continue
            for item, rec in sorted((pentry.get("generated") or {}).items()):
                if _is_record(rec):
                    yield "%s.props.%s.generated.%s" % (stage, prop, item), rec
        for ref, rec in sorted((entry.get("fetched") or {}).items()):
            if _is_record(rec):
                yield "%s.fetched.%s" % (stage, ref), rec


def totals(m):
    """The attested spend on a manifest.

    `usd` is the sum of every USD record (a 4-place string), or None when no
    USD record exists. Unobserved and non-USD records are counted beside it,
    never folded in: the total is a floor on what was spent.
    """
    usd, usd_records, unobserved, non_usd, currencies, n = Decimal(0), 0, 0, 0, set(), 0
    for _path, rec in records_on(m):
        n += 1
        c = rec["cost"]
        if is_unobserved(c):
            unobserved += 1
        elif c.get("currency") == "USD":
            usd += Decimal(str(c.get("amount", "0")))
            usd_records += 1
        else:
            non_usd += 1
            currencies.add(str(c.get("currency")))
    return {"usd": quantize(usd) if usd_records else None, "records": n, "usd_records": usd_records,
            "unobserved": unobserved, "non_usd": non_usd, "non_usd_currencies": sorted(currencies)}
