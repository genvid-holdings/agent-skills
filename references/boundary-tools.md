<!-- GENERATED from references/_boundary_tools.yaml — do not edit by hand. -->

# Boundary Tools Reference

> The supported contract of the Genvid governed boundary.
> `designed` tools are specified but not yet deployed; the smoke test treats them as pending.
> A blank Skill cell means no skill in this pack teaches that tool yet — read the tool's own
> description over MCP.

| Tool | Classification | Status | Params | Skill |
| ---- | -------------- | ------ | ------ | ----- |
| `discovery_read` | read_only | live | `method`, `project_id`, `query`, `model_type`, `source_type`, `source_id`, `run_id` | genvid-propagate-change |
| `analytics_read` | read_only | live | `method`, `project_id`, `project_ids`, `breakdown_by`, `date_from`, `date_to`, `asset_type` |  |
| `propagate_change` | billable | live | `source_type`, `source_id`, `option` | genvid-propagate-change |
| `media_read` | read_only | live | `project_id`, `media_ids` | genvid-agent-generation |
| `ingest_generated_media` | additive | live | `project_id`, `link_type`, `shot_id`, `asset_id`, `source_url`, `image_base64`, `filename`, `model_provider`, `model_name`, `render_type`, `prompt`, `params`, `input_media_ids`, `input_link_type` | genvid-agent-generation |
| `register_media` | additive | live | `project_id`, `link_type`, `shot_id`, `asset_id`, `filename`, `mime_type`, `proxy_filename`, `storage_class`, `connection_name` | genvid-media-registration |
| `finalize_media_registration` | additive | live | `project_id`, `media_id`, `link_type`, `shot_id`, `asset_id`, `content_hash`, `fingerprint_iscc`, `fingerprint_iscc_content`, `filename`, `mime_type`, `size_bytes`, `duration_seconds`, `timecode`, `locator`, `locator_type`, `pre_signed_c2pa_manifest`, `input_media_ids`, `storage_class`, `connection_name` | genvid-media-registration |
| `resolve_media` | read_only | live | `project_id`, `media_id` | genvid-agent-generation |
| `check_conformance` | read_only | live | `project_id`, `asset_id`, `media_id` | genvid-agent-generation |
| `verify_media` | additive | live | `project_id`, `media_id`, `content_hash`, `locator`, `locator_type` | genvid-media-registration |
| `connect_media` | additive | live | `project_id`, `media_id`, `locator`, `connection_name` | genvid-media-registration |
| `approve_media` | destructive | live | `project_id`, `media_id`, `selection_status` |  |
| `record_approved_corrections` | destructive | live | `project_id`, `asset_id`, `target`, `stage`, `media_id`, `link_type`, `payload`, `note` |  |
| `export_provenance_report` | read_only | live | `project_id`, `format` |  |
| `production_read` | read_only | live | `method`, `project_id`, `resource_type`, `resource_id`, `assigned_to`, `task_type`, `generation_type`, `model_id` | genvid-agent-generation |
| `production_write` | destructive | live | `method`, `project_id`, `resource_type`, `resource_id`, `task_type`, `assigned_to_email`, `workflow_status`, `priority` | genvid-agent-generation |
| `review_read` | read_only | live | `method`, `resource_type`, `resource_id`, `task_type`, `page`, `page_size` | genvid-agent-generation |
| `review_write` | additive | live | `method`, `project_id`, `media_id`, `assignment_id`, `note`, `critique_tags`, `scope_target`, `dimension`, `severity`, `chain_id` | genvid-agent-generation |
| `screenplay_read` | read_only | live | `method`, `project_id` | genvid-screenplay-breakdown |
| `screenplay_write` | destructive | live | `method`, `project_id`, `content`, `message` | genvid-screenplay-breakdown |
| `assets_read` | read_only | live | `method`, `project_id`, `asset_id`, `asset_type`, `render_type`, `budget_preference`, `shot_complexity`, `max_results` | genvid-agent-generation |
| `assets_write` | destructive | live | `method`, `project_id`, `asset_id`, `name`, `asset_type`, `description`, `assets` | genvid-screenplay-breakdown |
| `locations_write` | destructive | live | `method`, `project_id`, `scene_id`, `location_id` |  |
| `scenes_read` | read_only | live | `method`, `project_id`, `scene_id` | genvid-scene-shot-design |
| `scenes_write` | destructive | live | `method`, `project_id`, `scene_id`, `linked_assets` | genvid-scene-shot-design |
| `shots_read` | read_only | live | `method`, `project_id`, `shot_id`, `limit`, `cursor`, `detail` | genvid-scene-shot-design |
| `shots_write` | destructive | live | `method`, `project_id`, `shot_id`, `prompt`, `description`, `shot_size`, `camera_angle`, `camera_movement`, `shot_framing`, `transition` | genvid-scene-shot-design |
| `storyboard_write` | destructive | live | `method`, `project_id`, `scenes`, `scene_id`, `beat`, `shots` | genvid-scene-shot-design |
| `get_storyboard` | read_only | live | `project_id` | genvid-scene-shot-design |
