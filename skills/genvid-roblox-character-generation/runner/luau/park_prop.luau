-- Prop park: parks a Cube-generated kit prop under
-- ServerStorage/Assets/Props/<Biome>/<PropName>, the same never-delete-a-prior-version
-- shape park.luau uses for a character template and a per-title skill's own park step
-- uses for a static prop mesh. Anchors and disables collision the way that step does for
-- its own static asset. No rescale here: the kitbash placement step places and
-- recolors props from the JSON layout, not this park step, and no per-prop height
-- figure is carried on the prop manifest.
local HttpService = game:GetService("HttpService")
local ServerStorage = game:GetService("ServerStorage")
local model = {{MODEL_PATH}}
-- model may already be a bare MeshPart (Cube's own return, or a single-mesh 3D
-- Importer result) or a wrapping Model; either way the thing we park is the
-- MeshPart itself.
local mesh = model:IsA("MeshPart") and model or model:FindFirstChildWhichIsA("MeshPart", true)
assert(mesh, "park_prop: no MeshPart under " .. model:GetFullName())
mesh.Anchored = true
mesh.CanCollide = false
local assets = ServerStorage:FindFirstChild("Assets") or Instance.new("Folder", ServerStorage); assets.Name = "Assets"
local propsFolder = assets:FindFirstChild("Props") or Instance.new("Folder", assets); propsFolder.Name = "Props"
local biomeFolder = propsFolder:FindFirstChild("{{BIOME}}") or Instance.new("Folder", propsFolder); biomeFolder.Name = "{{BIOME}}"
local prev = biomeFolder:FindFirstChild("{{PROP}}")
if prev then prev.Name = "{{PROP}}_prev_" .. os.time() end -- never delete; the orchestrator asks before removing
mesh.Name = "{{PROP}}"; mesh.Parent = biomeFolder
print("RUNNER_RESULT " .. HttpService:JSONEncode({ parked = mesh:GetFullName(),
	anchored = mesh.Anchored, canCollide = mesh.CanCollide }))
