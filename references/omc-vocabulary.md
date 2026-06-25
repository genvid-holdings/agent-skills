<!-- GENERATED from backend/genvidagent/vocabulary/vocabulary.json — do not edit by hand. -->

# OMC Vocabulary

**Vocabulary version**: 1.0.0

> Canonical terminology used by the Genvid agent and OMC pipeline.
> Use the preferred terms in all user-facing copy, prompts, and API field names.

## Avoid → Use

| Avoid | Use instead |
| ----- | ----------- |
| asset sync | breakdown |
| audience | content_rating |
| chapter | not a Genvid concept — use scene or sequence |
| concept art | reference image |
| elevator pitch | logline |
| episodes | not a Genvid entity — each project IS an episode. Do not refer to 'episodes within a project'. |
| extract assets | sync assets |
| feel | tone |
| film | project |
| look | color_palette or art_medium |
| mood | tone |
| movie | project |
| picture | keyframe |
| pull out characters | sync assets |
| rating | content_rating |
| reference photo | reference image |
| season | not a Genvid concept — use project |
| series | not a Genvid entity — a series is a collection of projects, but only individual projects exist in the data model. Refer to each project by name. |
| shot list | storyboard |
| style parameter in generate_asset_images | removed — configure art_medium in the project's production settings before calling generate_asset_images |
| summary | logline |
| time period | era |
| type of film | genre |
| vibe | tone |
| video clip | video |
| visual style | set art_medium and production parameters — do not use the legacy styles system |
| when it's set | era |

## Preferred Terms by Category

### Assets

Media asset terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `keyframe` | keyframe | A reference image representing a shot's visual composition |
| `reference_image` | reference image | Visual reference for an asset (character portrait, location environment art, prop render). Generated during visual development phase. |
| `video` | video | Generated moving image content |

### Camera

Cinematography vocabulary

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `camera_angle` | camera angle | The vertical angle of the camera relative to the subject (i.e. 'angle of framing') |
| `camera_movement` | camera movement | How the camera moves during the shot (i.e. 'mobile framing') |
| `shot_framing` | shot framing | How subjects are arranged in the frame |
| `shot_size` | shot size | How much of the scene is visible in the frame (i.e. 'distance of framing') |

### Characters

Character-related terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `character` | character | A person or entity appearing in the narrative |

### Context

Scene and shot structure terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `scene` | scene | A continuous unit of action in one location and time |
| `shot` | shot | A single continuous recording from one camera setup |

### Creative Works

Project and narrative structure terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `project` | project | A complete production composed of sequences, scenes, scenebeats, and shots. A project IS the top-level narrative entity in Genvid — there is no 'episodes' or 'seasons' table above it. NEVER use the word 'episode' in responses; say 'project' instead. |
| `screenplay` | screenplay | The written narrative script for a project |
| `storyboard` | storyboard | Visual breakdown of the screenplay into individual shots with scene and location assignments |

### Generation

AI generation process terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `image_to_video` | image-to-video | Generating video from a reference image |
| `text_to_image` | text-to-image | Generating images from text descriptions |

### Locations

Setting and location terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `location` | location | A place where scenes occur |

### Participants

Team and workflow participant terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `creator` | creator | User who creates and manages projects |

### Pipeline

Production pipeline phases and state

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `breakdown` | breakdown | 1st AD screenplay breakdown — asset extraction, enrichment, and scene-asset linking. Phase A of the production pipeline. |
| `production` | production | Storyboard generation, camera angles, and first frame composition — all with full visual context. Phase C of the production pipeline. |
| `staleness` | stale | Media that is out of date relative to upstream changes. Tracked via stale_since timestamp on media rows. |
| `visual_dev` | visual development | Reference image generation for approved assets — character portraits, location environments, prop renders. Phase B of the production pipeline. |

### Props And Wardrobe

Props and costume terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `prop` | prop | An object used by characters or present in scenes |

### Scene

Scene-level mise-en-scene properties defining visual context

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `ambient_sound` | ambient sound | Free-text description of the scene's sonic environment |
| `atmosphere` | atmosphere | Free-text description of the scene's mood and environmental feel |
| `director_notes` | director's notes | Creative intent notes that concatenate across show, scene, and shot levels |
| `interior_exterior` | interior/exterior | Spatial context of the scene (WGA slug line format) |
| `lighting_notes` | lighting notes | Free-text specific lighting instructions for the scene |
| `lighting_style` | lighting style | Overall lighting approach for the scene (Bordwell pp. 124-132) |
| `time_of_day` | time of day | Temporal context of the scene (WGA slug line format) |
| `weather` | weather | Environmental weather conditions affecting the scene |

### Status

Status and state terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `approved` | approved | Content that has been reviewed and accepted |
| `draft` | draft | Content that is in progress and not finalized |

### Tasks

Workflow and task terminology

| Term | Preferred label | Definition |
| ---- | --------------- | ---------- |
| `asset_sync` | asset sync | LLM-powered extraction of narrative elements (cast, props, locations, costumes) from the screenplay into the asset database |
| `generation_job` | generation job | An AI generation task in progress |
