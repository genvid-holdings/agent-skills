"""The per-title DESIGN DOCUMENT: the one place a production's own world design
reaches this pack.

A biome palette, a HUD's token hexes, a prop kit's contents, the words that name
a game's art direction and the names of its own Luau design modules are all
design decisions owned by ONE title. They are not general Roblox
character-generation technique, and this pack is mirrored publicly, so none of
them may live here as a constant. What lives here is the SHAPE they arrive in
and the accessors that read them:

    m["design"] = {
        "palettes":     {"<biome name>": ["#RRGGBB", ...], ...},
        "hud_tokens":   {"<role>": "#RRGGBB", ...},
        "kit_props":    ["<prop name>", ...],
        "style":        "<prompt fragment naming the art direction>",
        "hud_style":    "<prompt fragment describing the HUD's own layout>",
        "luau_modules": {"design_tokens": "<module name>", "lighting": "<module name>"},
    }

A per-title skill stamps the document onto the manifest (the same seam
`production_title` and `studio.park_folder` arrive through); `biome init
--design <file.json>` is the other way in, for a caller driving this pack
directly. Every read goes through `load()` or one of the typed accessors below,
and every one of them RAISES naming the missing key rather than falling back:
a default here would either be one production's design wearing a generic name,
or a placeholder silently conditioning a paid generation and a governed
`params` row. Neither is recoverable after the fact.

Stdlib-only, like every other runner module.
"""

# Every key a complete design document carries, and what reads it.
REQUIRED_KEYS = ("palettes", "hud_tokens", "kit_props", "style", "hud_style", "luau_modules")
# The Luau modules a title names for itself. `design_tokens` holds the HUD's token
# hexes; `lighting` holds the per-biome lighting presets `biome lighting` prints a
# snippet for. This pack never writes either file -- a title's repo is not its to
# edit -- it only needs the names to say where a value is meant to land.
LUAU_ROLES = ("design_tokens", "lighting")

_WHY = {
    "palettes": "the biome palettes every establishing-shot plate is conditioned on",
    "hud_tokens": "the HUD token hexes the HUD plate is conditioned on",
    "kit_props": "the prop kit's contents",
    "style": "the prompt fragment naming this title's art direction",
    "hud_style": "the prompt fragment describing this title's HUD layout",
    "luau_modules": "the names of this title's own design Luau modules",
}


def _missing(key):
    return ValueError(
        "no design[%r] on the manifest (%s). The design document belongs to the "
        "production, not to this pack, and there is no default to fall back to: a "
        "per-title skill stamps m['design'], or pass `biome init --design <file.json>`. "
        "Required keys: %s" % (key, _WHY.get(key, "a per-title design value"),
                              ", ".join(REQUIRED_KEYS)))


def load(m):
    """This manifest's design document, or a ValueError naming what is missing.

    Checks the whole shape at once so a caller that only needs one key still
    fails on an incomplete document at the first read rather than three stages
    later, on a manifest that has already spent vendor credit."""
    doc = m.get("design")
    if not doc:
        raise _missing("design")
    if not isinstance(doc, dict):
        raise ValueError("m['design'] is not a mapping (%s); see runner/design.py for the shape"
                         % type(doc).__name__)
    for key in REQUIRED_KEYS:
        if not doc.get(key):
            raise _missing(key)
    modules = doc["luau_modules"]
    if not isinstance(modules, dict):
        raise ValueError("design['luau_modules'] is not a mapping (%s); expected roles %s"
                         % (type(modules).__name__, ", ".join(LUAU_ROLES)))
    for role in LUAU_ROLES:
        if not modules.get(role):
            raise ValueError("design['luau_modules'][%r] is missing: name the title's own "
                             "module for that role (roles: %s)" % (role, ", ".join(LUAU_ROLES)))
    return doc


def palettes(m):
    """`{biome name: [hex, ...]}` -- also the set of biome names this title HAS,
    which is what `biome init --biome` validates against and what its error
    message lists. The pack knows no biome names of its own."""
    return dict(load(m)["palettes"])


def biome_names(m):
    return tuple(sorted(load(m)["palettes"]))


def palette(m, biome):
    """One biome's palette by role, or a ValueError listing the title's own names."""
    pal = load(m)["palettes"]
    if biome not in pal:
        raise ValueError("unknown biome %r: this title's design document names %s"
                         % (biome, ", ".join(sorted(pal))))
    return list(pal[biome])


def hud_tokens(m):
    return dict(load(m)["hud_tokens"])


def kit_props(m):
    return tuple(load(m)["kit_props"])


def style(m):
    return load(m)["style"]


def hud_style(m):
    return load(m)["hud_style"]


def luau_module(m, role):
    """The title's own module name for one role in LUAU_ROLES."""
    if role not in LUAU_ROLES:
        raise ValueError("unknown design module role %r: choose from %s" % (role, ", ".join(LUAU_ROLES)))
    return load(m)["luau_modules"][role]


def attach(m, doc):
    """Put a design document on a manifest, validating it FIRST: an invalid one is
    refused at `init`, where the caller can still fix it, rather than at the first
    stage that reads a key -- and the manifest is left untouched when it is refused,
    so a caller that catches the error is not holding a manifest carrying a document
    this module has already rejected."""
    candidate = dict(doc)
    load({"design": candidate})
    m["design"] = candidate
    return m
