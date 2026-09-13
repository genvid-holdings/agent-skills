"""Pinned vendor unit prices and OBSERVED-cost computation.

Ground truth for every price here is the fal BILLING EXPORT
(fal-ai-usage-2026-09-01..2026-09-30.csv, 17 rows, one key, $32.9034 total). It
is what fal actually charged; a pricing API is what fal advertises. Where the
two disagree, the export wins.

Two things this module got wrong by pricing off the catalog instead:

  - meshy/v7/multi-image-to-3d was pinned at $0.00007 per COMPUTE SECOND. The
    export bills it per GENERATION at $0.80 (2026-09-04: 1.5 generations,
    $1.20) -- 143x under, and a wrong axis is not correctable by a better
    quantity. That figure matched no source: re-checked 2026-09-09, the fal
    pricing API itself also reports $0.80 per generation for it.
  - A pricing API gives a RATE on an axis, never the per-call QUANTITY on that
    axis. Checked 2026-09-09, it reports tripo3d/h3.1/image-to-3d and
    multiview-to-3d at "$0.01 per credit" and says nothing about the 30 credits
    a call consumes -- which is the whole number that matters. Only the export
    (or a response that reports its own charge) supplies a quantity.

Two things are separate and must stay separate:

  cost_of(endpoint, response)  -> what the vendor CHARGED for a call that already
                                  happened. It is signed into a C2PA manifest as
                                  genvid.generator.data.cost and stored on
                                  media.attested_cost_amount, so it may never be
                                  a guess: a call whose billable quantity cannot
                                  be read raises CostNotObserved.
  estimate_of(endpoint, calls) -> what a stage is ABOUT to spend, for the
                                  pre-spend budget gate. It runs before the call,
                                  has no response to read, and is therefore
                                  allowed to assume. It is never attested.

`kind` is the AXIS fal actually bills on, one per entry, read off the export's
`unit` column:

  flat            one call = one billable unit (a generation, an image). The
                  quantity is 1 by construction, so the cost is observed without
                  reading the response.
  reported_credit the vendor reports the credits it consumed in its own response.
                  The quantity is read from there; absent, the call raises.
  compute_second  billed per second of inference; the quantity is
                  metrics.inference_time on the response. No endpoint this runner
                  calls is billed this way today -- the axis is kept because fal
                  does bill on it (the export's fal-ai/birefnet/v2 rows), so a
                  compute-second endpoint gets priced on its own axis instead of
                  being shoehorned into `flat` -- the mirror image of the wrong-axis
                  pricing this module carried for a per-generation endpoint.

Unit prices witnessed in the export carry their row's date. Entries with no
export row are labelled (assumption): the label is not a licence to attest a
guessed QUANTITY, which is what cost_of() refuses -- it flags a unit price no
billing row has confirmed yet.
"""
from decimal import Decimal, ROUND_HALF_UP

FOUR_PLACES = Decimal("0.0001")

# The only sanctioned zero cost: a bind with no vendor call behind it (a local
# Blender render, or a re-bind of bytes some other stage already paid for and
# attested). Stages reference this by name so that no cost string is written
# anywhere outside this module: a hardcoded "0.2000" in an ad-hoc driver once
# bypassed it for 62 media, 62% of one project's whole attested total, and never
# touched a unit price at all.
NO_VENDOR_CALL = "0"


class CostNotObserved(RuntimeError):
    """The vendor did not report what it charged, so there is no observed cost.

    Raised rather than estimated: an attested cost is a claim the customer
    makes, so a stage that cannot derive one must refuse in the same
    register as a stage with nothing to attest, not sign a guess and note it.
    """


PRICES = {
    # --- witnessed against the billing export ---
    # 2026-09-04: 1.5 "generations", $1.20, unit_price 0.80.
    "meshy/v7/multi-image-to-3d": {"kind": "flat", "unit": Decimal("0.80")},
    # 2026-09-04: 2.55 "generations", $0.204, unit_price 0.08. fal bills this one
    # FRACTIONALLY -- 2.55 generations for 3 calls -- and the response reports no
    # fraction, so one call is the only quantity observable from a response and a
    # per-call $0.08 does not sum to the billed figure. The exact amount is in
    # the export, at reconciliation time.
    "fal-ai/meshy/rigging/multi-animation": {"kind": "flat", "unit": Decimal("0.08")},
    # 2026-09-04/05: "images", unit_price 0.08.
    "fal-ai/nano-banana-2": {"kind": "flat", "unit": Decimal("0.08")},
    # 2026-09-04/06/07/08: "images", unit_price 0.08 (also billed fractionally:
    # 6.575 images on 09-04).
    "fal-ai/nano-banana-2/edit": {"kind": "flat", "unit": Decimal("0.08")},
    # 2026-09-05/07: "images", unit_price 0.15.
    "fal-ai/hunyuan_world": {"kind": "flat", "unit": Decimal("0.15")},
    # Billed in fal credits at $0.01, 30 credits per call = $0.30 flat, pinned
    # from the export rather than read per call. Two reasons it is pinned:
    #   - The count cannot be read back. No recorded fal-hosted tripo response
    #     body was available to inspect here; what is witnessed is that every
    #     tripo call in the reconciled month took the assumed-credits path (the
    #     old "cost estimated" note fired on all of them), which means neither
    #     `credits` nor `output.credits` was present on any of them. The one
    #     recorded fal rig response, a different endpoint, likewise reports no
    #     charge field of any kind.
    #   - In the export the count is exact and repeated: 2026-09-05 450 credits
    #     / 15 media = 30.0, 2026-09-08 780 / 26 = 30.0, and the single
    #     multiview call on 2026-09-04 billed exactly 30 credits ($0.30).
    # 30 held across two DIFFERENT parameter sets, which is why it is pinned as
    # a per-call price and not as a property of one configuration: the multiview
    # call ran at this runner's face_limit 20000 with pbr off, and the 77
    # single-image calls came from an ad-hoc driver, not from this runner, at
    # face_limit 6000 with pbr on -- so that half of the evidence is not
    # re-derivable from this tree, only from the export row it produced. Tripo
    # does charge by what the generation asks for, so a change beyond that range
    # is still worth re-witnessing against a new export row.
    "tripo3d/h3.1/multiview-to-3d": {"kind": "flat", "unit": Decimal("0.30")},
    "tripo3d/h3.1/image-to-3d": {"kind": "flat", "unit": Decimal("0.30")},

    # --- Tripo's DIRECT API (bake-off leg C; TRIPO_API_KEY, not fal) ---
    # Not on the fal export at all -- Tripo bills these separately -- but its own
    # task response reports the charge as `consumed_credit`, so the quantity IS
    # observed per call and the $0.01/credit rate is the same one fal passes
    # through. Witnessed 2026-09-04 on the leg C animate_rig task: 25 credits.
    "tripo-direct-rig": {"kind": "reported_credit", "unit": Decimal("0.01")},
    "tripo-direct-mesh": {"kind": "reported_credit", "unit": Decimal("0.01")},

    # --- (assumption): catalog price, no billing row has confirmed it ---
    # Both read from fal's pricing API on 2026-09-09 at $0.80 per generation,
    # the same axis and rate the export confirms for their multi-image sibling.
    # Neither has ever been spent on by this runner, so neither appears on any
    # billing export -- the axis is corroborated, the charge is not.
    # fal-ai/meshy/rigging: meshy.RIG is defined but unused; the multi-animation
    # sibling above is the live rig endpoint.
    "fal-ai/meshy/rigging": {"kind": "flat", "unit": Decimal("0.80")},
    # meshy/v7/image-to-3d: the static-prop chain, single-image variant.
    "meshy/v7/image-to-3d": {"kind": "flat", "unit": Decimal("0.80")},
}

# Quantities the pre-spend budget gate assumes, for endpoints whose billable
# quantity is only knowable from a response that does not exist yet. GATE ONLY:
# estimate_of() reads this, cost_of() must not, and nothing here is ever
# attested. Deliberately ceilings, not best guesses -- a gate that overestimates
# refuses visibly, one that underestimates lets spend through silently.
ESTIMATED_QUANTITY = {
    # 30 credits is what a Tripo biped animate_rig was expected to cost; the one
    # witnessed run charged 25 (2026-09-04), so 30 stands as the ceiling.
    "tripo-direct-rig": 30,
    # Same task shape and face_limit as the fal-hosted multiview endpoint, which
    # bills 30 credits.
    "tripo-direct-mesh": 30,
}


def _quantize(cost):
    return str(cost.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP))


def _price(endpoint):
    price = PRICES.get(endpoint)
    if price is None:
        # An endpoint missing from PRICES (unlisted or misspelled) has no unit price to
        # cost from -- returning "0" would silently attest $0.00 spent into a governed
        # Genvid record. Raise loud instead; the caller adds the model id to PRICES.
        raise KeyError("no PRICES entry for endpoint %r; add it to vendors/pricing.PRICES" % endpoint)
    return price


def _credits(response):
    """The credit count the vendor reports for a call, or None if it reports none.

    Tripo's direct API says `consumed_credit` (witnessed 2026-09-04, leg C
    animate_rig: 25). `credits` / `output.credits` are the shapes this module
    looked for first and never matched; they are still accepted, and are the
    reason the observed 25 was discarded in favour of an assumed 30.
    """
    output = response.get("output") or {}
    for source in (response, output):
        for key in ("consumed_credit", "credits"):
            value = source.get(key)
            if value is not None:
                return value
    return None


def cost_of(endpoint, response):
    """Decimal-string cost of one vendor call that already happened, 4 places.

    endpoint: a PRICES key, or "local"/falsy for a bind with no vendor call.
    response: the vendor response dict (fal queue response, or a Tripo direct task).

    Raises CostNotObserved when the vendor reported no billable quantity, and
    KeyError when the endpoint has no pinned price. It never estimates: the
    caller attests this figure into a signed manifest.
    """
    if not endpoint or endpoint == "local":
        return NO_VENDOR_CALL
    price = _price(endpoint)
    response = response or {}
    kind = price["kind"]
    if kind == "flat":
        # One call, one billable unit: the quantity is 1 by construction and the
        # response has nothing to add.
        cost = price["unit"]
    elif kind == "reported_credit":
        credits = _credits(response)
        if credits is None:
            raise CostNotObserved(
                "endpoint %r is billed in vendor credits and its response reports none "
                "(looked for consumed_credit/credits, top level and under output); refusing "
                "to attest an assumed quantity as an observed cost" % endpoint)
        cost = price["unit"] * Decimal(str(credits))
    elif kind == "compute_second":
        secs = (response.get("metrics") or {}).get("inference_time")
        if secs is None:
            raise CostNotObserved(
                "endpoint %r is billed per compute second and its response reports no "
                "metrics.inference_time; refusing to attest an assumed duration as an "
                "observed cost" % endpoint)
        cost = price["unit"] * Decimal(str(secs))
    else:
        raise CostNotObserved(
            "endpoint %r has unknown billing kind %r; add its axis to cost_of rather than "
            "attesting a cost derived on no axis at all" % (endpoint, kind))
    return _quantize(cost)


def estimate_of(endpoint, calls=1):
    """Decimal-string PRE-SPEND estimate for `calls` calls, for the budget gate only.

    This runs before the vendor call, so it has no response to read and may use
    ESTIMATED_QUANTITY. It goes into a check_generation_budget payload and never
    into an attested_cost_usd -- attestation is cost_of()'s job, and cost_of()
    raises rather than reaching for these numbers.
    """
    if not endpoint or endpoint == "local":
        return NO_VENDOR_CALL
    price = _price(endpoint)
    kind = price["kind"]
    if kind == "flat":
        unit_cost = price["unit"]
    elif kind in ("reported_credit", "compute_second"):
        quantity = ESTIMATED_QUANTITY.get(endpoint)
        if quantity is None:
            raise KeyError(
                "endpoint %r is billed per %s and has no ESTIMATED_QUANTITY entry to gate "
                "on; add one to vendors/pricing.ESTIMATED_QUANTITY" % (endpoint, kind))
        unit_cost = price["unit"] * Decimal(str(quantity))
    else:
        raise KeyError("endpoint %r has unknown billing kind %r" % (endpoint, kind))
    return _quantize(unit_cost * Decimal(str(calls)))
