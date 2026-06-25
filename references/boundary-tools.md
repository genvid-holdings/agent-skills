<!-- GENERATED from references/_boundary_tools.yaml — do not edit by hand. -->

# Boundary Tools Reference

> Curated contract of the Genvid governed boundary tools used by the reference skill pack.
> `designed` tools are specified but not yet deployed; the smoke test treats them as pending.

| Tool | Classification | Status | Params | Skill |
| ---- | -------------- | ------ | ------ | ----- |
| `discovery_read` | read_only | live | `method`, `source_type`, `source_id` | genvid-propagate-change |
| `propagate_change` | billable | live | `source_type`, `source_id`, `option` | genvid-propagate-change |
| `media_read` | read_only | live | `project_id`, `media_id` | genvid-agent-generation |
| `ingest_generated_media` | additive | live | `project_id`, `link_type`, `shot_id`, `asset_id`, `source_url`, `image_base64`, `model_provider`, `model_name`, `render_type`, `prompt`, `params`, `input_media_ids`, `input_link_type` | genvid-agent-generation |
| `production_read` | read_only | live | `method`, `project_id`, `resource_type`, `resource_id`, `assigned_to` | genvid-agent-generation |
| `production_write` | additive | live | `method`, `project_id`, `resource_type`, `resource_id`, `task_type`, `assigned_to_email`, `workflow_status`, `priority` | genvid-agent-generation |
| `screenplay_read` | read_only | live | `method`, `project_id` | genvid-screenplay-breakdown |
| `screenplay_write` | destructive | live | `method`, `project_id`, `content` | genvid-screenplay-breakdown |
| `breakdown_assets` | billable | live | `project_id` | genvid-screenplay-breakdown |
| `scenes_read` | read_only | live | `method`, `project_id`, `scene_id` | genvid-scene-shot-design |
| `scenes_write` | destructive | live | `method`, `project_id`, `scene_id` | genvid-scene-shot-design |
| `shots_read` | read_only | live | `method`, `project_id`, `shot_id` | genvid-scene-shot-design |
| `shots_write` | destructive | live | `method`, `project_id`, `shot_id` | genvid-scene-shot-design |
| `breakdown_storyboard` | billable | live | `project_id` | genvid-storyboard |
