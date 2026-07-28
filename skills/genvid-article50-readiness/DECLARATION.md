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
| `role` | `provider`, `deployer`, or `both`. Article 50(2) binds the provider of the generating system; 50(4) binds the deployer of a system producing a deep fake. If you generated with someone else's model and published the result, you are typically the deployer, but that is a determination for counsel, not for this file. |
| `artistic_work` | `true` where the work is evidently artistic, creative, satirical or fictional. Under 50(4) that narrows the disclosure duty to a form that does not hamper the work's display. It does not remove it. |
| `public_interest_text` | `true` if the production publishes AI-generated text to inform the public on matters of public interest. |
| `editorial_responsibility` | Who held editorial responsibility for that text, if anyone. Relevant only when `public_interest_text` is `true`. |
| `disclosure_statement` | The wording a person is actually shown. Not a note to yourself: the words that appear on screen, in the credits, or in the player. |

## `assets`

Keys are paths relative to the scanned directory, in POSIX form. Every value is
an object:

| Field | Meaning |
| --- | --- |
| `ai_generated` | `true`, `false`, or omitted. Omitted is not the same as `false`: the scan reports it as undetermined and raises a gap, because an obligation cannot be scoped or ruled out while the origin is unknown. |
| `deep_fake` | `true` where the asset is generated or manipulated image, audio or video content resembling real people, objects, places or events, presented as authentic. |
| `model` | Model and version. This is what makes the declaration auditable a year later, when the pipeline has moved on. |
| `human_review` | Whether a person reviewed the output before it went into the cut. |
| `disclosure` | Per-asset disclosure wording, where it differs from the production-level statement. |
| `watermark` | The imperceptible watermark carried by this asset, if any; name the method or tool. The code of practice expects two layers of machine-readable marking, signed metadata *and* a watermark, and this scan can read only the first. Recording it here is you asserting the second layer exists; the scan takes your word for it, marks it `declared` rather than verified, and closes the `second-marking-layer-unevidenced` gap. Leave it out if you are not sure. |

`defaults` applies to every asset and is overridden per entry. Use it sparingly:
a directory-wide `{"ai_generated": true}` is honest for a fully synthetic
sequence and misleading for a mixed one.

## What the scan does with it

The declaration and the bytes are reconciled, not merged. Where they disagree, when
the declaration says captured but the file's own metadata names a model, the scan
records the asset as `contested` and raises a high-severity gap rather than
quietly preferring one source. Both readings stay in the report so a person can
resolve it.

Nothing here is validated against an external registry, and no field is
attested by anyone. The declaration records what the operator says. It is a
statement, not a proof, and the report presents it that way.
