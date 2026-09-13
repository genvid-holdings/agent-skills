-- Surface pass: swap the parked character template's MeshPart
-- mesh + texture for a re-baked one, without touching wiring or clips
-- (validated 2026-08-27: wiring and clips survive an ApplyMesh swap).
-- {{TEMPLATE}} names the ALREADY-PARKED template: it lives under the park
-- folder ONLY, never a workspace lookup -- unlike
-- zoo_capture.luau (which captures a live clone that legitimately might be in
-- workspace), the whole point here is to mutate the one parked copy every
-- future spawn/park re-reads from. The freshly-imported surfaced model sits in
-- workspace under the same name the 3D Importer gives it, which is often the
-- template's own name -- a workspace-first lookup would resolve `template` to
-- that import instead of the parked copy, ApplyMesh the import onto itself,
-- and print a false "applied" while the parked template stayed untouched.
-- {{SOURCE}} is that imported model, passed with
-- --param SOURCE=<Luau expression for the imported instance>.
local HttpService = game:GetService("HttpService")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local imported = {{SOURCE}}
assert(template ~= imported, "applymesh: SOURCE resolved to the parked template itself, not the import")
local dst = template:FindFirstChildWhichIsA("MeshPart", true)
local src = imported:IsA("MeshPart") and imported or imported:FindFirstChildWhichIsA("MeshPart", true)
assert(dst, "applymesh: no MeshPart on the parked template " .. template:GetFullName())
assert(src, "applymesh: no MeshPart on the imported source " .. imported:GetFullName())
assert(dst ~= src, "applymesh: destination and source MeshPart are the same instance")
local meshIdBefore = dst.MeshId
dst:ApplyMesh(src)
print("RUNNER_RESULT " .. HttpService:JSONEncode({ applied = true, template = template:GetFullName(),
	meshIdBefore = meshIdBefore, meshId = dst.MeshId, textureId = dst.TextureID,
	changed = dst.MeshId ~= meshIdBefore }))
