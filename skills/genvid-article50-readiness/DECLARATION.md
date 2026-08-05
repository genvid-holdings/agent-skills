# The operator declaration (`article50.json`)

A scan with no declaration can only report what generating tools happened to
leave behind in the bytes. That is a weak basis for anything: metadata is
stripped by any transcode, screenshot or re-encode, and its absence is not
evidence that a file was captured rather than generated.

The declaration is where a human records what is actually true about the work.
It is a plain JSON file, written by hand or by an agent and reviewed by a
person, that lives at the root of the directory being scanned. Put it under
version control next to the assets; its history is the record of who said what
about the material, and when.

## Shape

```json
{
  "schema": "genvid.article50-declaration/v1",
  "production": {
    "title": "Sample Production",
    "operator": "Example Post House Ltd",
    "role": "deployer",
    "artistic_work": true,
    "public_interest_text": false,
    "editorial_responsibility": null,
    "disclosure_statement": "Contains scenes altered using generative AI."
  },
  "defaults": {},
  "assets": {
    "shots/sh020_bg_matte.png": {
      "ai_generated": true,
      "deep_fake": false,
      "model": "stable-diffusion-xl-base-1.0",
      "human_review": true
    },
    "shots/sh040_likeness_replace.mp4": {
      "ai_generated": true,
      "deep_fake": true,
      "model": "example-video-model-1.0",
      "human_review": true,
      "disclosure": "This sequence contains a digitally replaced likeness."
    },
    "shots/sh010_plate_exterior.jpg": {
      "ai_generated": false
    }
  }
}
```

## `production`

| Field | Meaning |
| --- | --- |
| `title` | Free text. Carried into the report so a report can be identified later. |
| `operator` | The legal entity. Article 50 assigns duties to a provider and to a deployer; naming the entity is what lets anyone work out which one you are. |
| `role` | `provider`, `deployer`, or `both`, and nothing else — see below. Article 50(2) binds the provider of the generating system; 50(4) binds the deployer of a system producing a deep fake. If you generated with someone else's model and published the result, you are typically the deployer, but that is a determination for counsel, not for this file. |
| `artistic_work` | `true` where the work is evidently artistic, creative, satirical or fictional. Under 50(4) that narrows the disclosure duty to a form that does not hamper the work's display. It does not remove it. Declared here it covers every asset; an asset entry (or `defaults`) overrides it for that asset. |
| `public_interest_text` | `true` if the production publishes AI-generated text to inform the public on matters of public interest. |
| `editorial_responsibility` | Who held editorial responsibility for that text, if anyone. Relevant only when `public_interest_text` is `true`, and it is one of two limbs — see below. |
| `human_review` | `true` where a person reviewed the published text before it went out. The production-level counterpart of the per-asset field; either one evidences review. |
| `disclosure_statement` | The wording a person is actually shown. Not a note to yourself: the words that appear on screen, in the credits, or in the player. |

### How `public_interest_text` is scored

Article 50(4)'s second subparagraph makes **disclosure the duty**. The scan
follows that structure rather than inverting it:

- A `disclosure_statement` clears it. Disclosing is the thing the paragraph asks
  for, so having disclosed is never itself a finding.
- Otherwise the duty lifts only on the statutory exception, which is
  **conjunctive**: the text underwent human review or editorial control, *and* a
  person holds editorial responsibility. Both limbs, not either. So
  `editorial_responsibility` alone does not clear it — record `human_review` as
  well.
- Neither present raises `public-interest-text-undisclosed`.

An exception nobody evidenced is not one, so the scan's default when a
declaration is silent is that the duty stands.

The review limb is read as follows. It is scoped to **text**, because that is
what the paragraph covers: whether an image was reviewed says nothing about
whether the published article was read by a person. `production.human_review`
states it for the publication; `human_review` on a declared text asset states it
for that text. `defaults.human_review` counts only where it actually reaches a
declared text asset, because `defaults` is a per-asset default rather than a
statement about the publication — a review flag covering a production's images
does not lift the duty on text nobody read. An explicit `human_review: false` on
any declared text is
**decisive** and outranks a positive record elsewhere — a publication containing
AI text the operator states nobody reviewed is not one the exception reaches,
and setting the field to `false` says exactly that.

### Booleans are read as booleans

These fields are JSON booleans, and are checked **at both levels they appear**:

| Level | Fields | Where the gap lands |
| --- | --- | --- |
| Asset entry (and `defaults`, which is merged into every entry) | `ai_generated`, `deep_fake`, `artistic_work`, `human_review` | on that asset |
| `production` | `artistic_work`, `public_interest_text`, `human_review` | on the directory |

A value that is neither `true` nor `false` — `"true"` as a string, `1`, `"yes"` —
raises `declaration-field-malformed` at high severity and does not resolve the
field. "Does not resolve" means exactly as if the key were absent: an asset entry
whose `artistic_work` is malformed inherits the production declaration, the same
as an entry that never mentioned it.

The scan does not guess what was meant. A declaration is a statement someone
stands behind, so coercing `"true"` into `true` would put words in the operator's
mouth. And the coercion that looks obvious runs backwards: `"false"` is a
non-empty string, so a bare truth test reads the word **false** as **true**. That
is the reading this check exists to prevent, which is why it is applied to the
production block and not only to the entries.

### The shape has to be the documented one

A declaration that parses as JSON but is not the shape above — a top-level array,
a `production` holding a string, an `assets` entry that is not an object — is as
unusable as one that does not parse, and is reported the same way: the scan runs
without it and raises the high-severity `declaration-unparsable` gap naming what
is wrong with it. Where the declaration was named explicitly with `--declaration`,
the scan refuses and exits `2` instead, because reading that file was part of the
question it was asked.

### Wording fields must contain wording

Every field above holding wording — `disclosure_statement`, the per-asset
`disclosure`, `editorial_responsibility`, `operator`, `role` — must hold a
**non-empty string once stripped**. Read as absent, all of them: `""`, `"   "`,
`true`, `0.0001`, `{}`, `[]`, `null`. A whitespace-only field is almost always a
form that wrote a space where it meant to omit the key, and a bare `true` is a
checkbox rather than a sentence. None of them is an answer: for the disclosure
fields, treating one as wording discharges a duty on an empty string, and for
`operator` and `role` it produces a report whose responsible entity is a space.
`operator` blank raises `operator-unnamed`, `role` blank raises `role-unstated`
— the same gaps as omitting the key, which is what a blank value means.

### `role` is one of three words

`role` is a closed vocabulary: `provider`, `deployer`, `both`. Anything else —
a typo like `deploeyr`, or a job title like `post house` — raises
`role-unrecognized` at medium severity, the same severity as saying nothing,
because that is how much it settles about which paragraphs bind. The value is
quoted back in the gap and never guessed at, for the reason a malformed boolean
is not coerced: a near-miss is as likely to be the wrong role as a misspelling
of the right one, and reading it as one would have this tool record a duty claim
the operator never made.

Matching ignores case and surrounding space, so `Deployer` and `" both "` are
accepted as written. What it does **not** do is change the scan: every Article
50(2) and 50(4) check in this tool runs the same way whatever `role` says. The
field is recorded for the person reading the declaration and the duties are
assigned by the Regulation, not by this file.

## `assets`

Keys are paths relative to the scanned directory, in POSIX form. Every value is
an object:

| Field | Meaning |
| --- | --- |
| `ai_generated` | `true`, `false`, or omitted. Omitted is not the same as `false`: the scan reports it as undetermined and raises a gap, because an obligation cannot be scoped or ruled out while the origin is unknown. |
| `deep_fake` | `true` where the asset is generated or manipulated **image, audio or video** content resembling real people, objects, places or events, presented as authentic. Article 50(4)'s first subparagraph reaches those three modalities only, so declaring it on a text asset — or on anything else the scan does not read as image, audio or video — raises `deep-fake-declared-on-non-av-asset` instead of engaging the deep-fake duty. AI-generated text belongs under `production.public_interest_text`, whose duty and exception are different. |
| `model` | Model and version. This is what makes the declaration auditable a year later, when the pipeline has moved on. |
| `human_review` | Whether a person reviewed the output before it went into the cut. For AI-generated text under `public_interest_text`, this is one of the two limbs of the exception that lifts the disclosure duty. |
| `disclosure` | Per-asset disclosure wording, where it differs from the production-level statement. |
| `watermark` | The imperceptible watermark carried by this asset, if any; name the method or tool. The code of practice expects two layers of machine-readable marking, signed metadata *and* a watermark, and this scan can read only the first. Recording it here is you asserting the second layer exists; the scan takes your word for it, marks it `declared` rather than verified, and closes the `second-marking-layer-unevidenced` gap. Leave it out if you are not sure. |

`defaults` applies to every asset and is overridden per entry. Use it sparingly:
a directory-wide `{"ai_generated": true}` is honest for a fully synthetic
sequence and misleading for a mixed one.

## What the scan does with it

The declaration and the bytes are reconciled, not merged. Where they disagree the
scan records the asset as `contested` and raises a high-severity gap rather than
quietly preferring one source, and it does so in both directions: the declaration
saying captured over metadata naming a model, and the declaration saying
model-generated over metadata asserting a camera. The second is not the lesser
case. A `digitalCapture` claim goes on telling every downstream C2PA and IPTC
reader the asset came out of a camera no matter what the declaration beside it
says, so the fix is usually in the material rather than in the declaration. The
report says which artifact carries the claim — the asset's own metadata, or a
sidecar next to it — because those need different corrections and editing the
file when the claim is in a sidecar leaves it standing. Both readings stay in the
report so a person can resolve it.

Nor does a declaration close an Article 50(2) marking gap. Declaring an asset
AI-generated is what engages the paragraph; what discharges it is the delivered
bytes carrying a marking that says so. See SKILL.md on what a marking has to
assert to count.

Reconciliation runs in both directions. A key here that matches no file in the
directory raises `declared-asset-not-found` and fails the scan, and its
declaration still counts toward the production-level checks. Otherwise a typo or
a rename would discharge every duty attached to the asset by making it
disappear, and the tool would report a clean directory because it had been given
a path that does not exist.

**Keys match exactly, including case.** `sh040_likeness.png` does not match a
delivered `SH040_Likeness.PNG`; the scan names the near-match in the gap so the
fix is one line, but it will not apply the declaration for you. That is
deliberate: on a case-sensitive filesystem two files can differ only in capitals,
and guessing which one was meant would attach a deep-fake duty to the wrong
asset. Note this is the realistic form of the failure — the file was delivered,
the declaration describes it, and nothing connects them, so the asset is scanned
as though nobody declared anything about it.

A declared asset that is present but could not be read is kept distinct from
both of those outcomes. It was seen, so it is not `declared-asset-not-found`;
its bytes were never examined, so it is not clean either. It raises
`asset-unreadable` and fails the scan. Whatever this file says about that asset
stands unchecked against the file itself until the read succeeds.

Nothing here is validated against an external registry, and no field is
attested by anyone. The declaration records what the operator says. It is a
statement, not a proof, and the report presents it that way.
