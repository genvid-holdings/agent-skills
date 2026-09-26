-- E13/E14: feet-grounded probe. EDIT mode. Clone the parked template onto a flat
-- 0-Y plane, hold its HumanoidRootPart bottom at the height the rig settles to
-- standing (measured once by the `settle` step in Play), then measure the lowest
-- skinned vertex Y against the plane.
--
-- Edit, not Play, because the measurement needs EditableMesh: in Play the call
-- fails with "EditableMesh is not accessible. Go to the Security Tab in
-- Experience Settings to enable this API" until the experience's
-- Mesh & Image API setting is turned on (witnessed 2026-09-04; that setting
-- is the operator's, not this runner's). The same call works in Edit, which is where
-- groundfit already reads the mesh.
--
-- `{{LOD}}` ("close"|"far") forces RenderFidelity so the far-LOD skinning path is
-- named in the record. RenderFidelity does not change vertex data, and this run
-- holds the pose rather than letting physics drive it, so an Edit-mode far read
-- is the close read again -- E14 reports PEND off `inPlay` below rather than
-- passing a number it did not independently measure.
local HttpService = game:GetService("HttpService")
local AssetService = game:GetService("AssetService")
local RunService = game:GetService("RunService")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]

local plane = workspace:FindFirstChild("_ProbeFeetPlane")
if not plane then
	plane = Instance.new("Part"); plane.Name = "_ProbeFeetPlane"
	plane.Size = Vector3.new(200, 1, 200); plane.Anchored = true; plane.CanCollide = true
	plane.CFrame = CFrame.new(0, -0.5, 0); plane.Parent = workspace
end

local planeTop = plane.Position.Y + plane.Size.Y / 2

local model = template:Clone(); model.Parent = workspace
local meshes = {}
for _, d in model:GetDescendants() do
	if d:IsA("MeshPart") then
		table.insert(meshes, d)
		if "{{LOD}}" == "far" then d.RenderFidelity = Enum.RenderFidelity.Performance end
	end
end
assert(#meshes > 0, "no MeshPart")
local hum = model:FindFirstChildOfClass("Humanoid")
local hrp = model.PrimaryPart or model:FindFirstChild("HumanoidRootPart")
local hip = model:GetAttribute("{{HIP_ATTR}}") or (hum and hum.HipHeight) or 0
-- The MEASURED height the rig settles to standing, not the hip: the Humanoid
-- holds its root bottom at HipHeight + e, so measuring at the hip reads a gap
-- the live character never has. The number comes from a verification `settle` run in
-- Play with the corrected hip already on the template -- never from
-- correctedHip + e, which is the sole offset again and would put the rest-pose
-- lowest vertex exactly on the plane whatever the rig does. Falls back to the
-- hip when no such settle has run, and says so in the result; the eval rows read
-- `settledMeasure` and report PEND rather than scoring that fallback.
local settled = tonumber("{{SETTLED_BOTTOM}}")
local bottom = settled or hip
model:PivotTo(CFrame.new(0, planeTop + bottom + (hrp and hrp.Size.Y / 2 or 0), 0))
-- Anchored: this is a static measurement in Edit, and an unanchored clone would
-- drift on the first physics step.
for _, d in model:GetDescendants() do if d:IsA("BasePart") then d.Anchored = true end end
task.wait()

-- Rest-pose lowest 200 vertices and their dominant bone, from each mesh's bind
-- data, over EVERY MeshPart (the same plane groundfit measured the sole offset
-- from): a multi-mesh import can list a small accessory mesh first.
local bones = {}
for _, d in model:GetDescendants() do
	if d:IsA("Bone") then bones[d.Name] = d end
end
local verts, ems = {}, {}
for _, mesh in meshes do
	local id = tonumber(mesh.MeshId:match("%d+"))
	assert(id, "MeshPart " .. mesh:GetFullName() .. " has no MeshId; its vertices cannot be read")
	local em = AssetService:CreateEditableMeshAsync(Content.fromAssetId(id))
	table.insert(ems, em)
	for _, vid in em:GetVertices() do
		local p = mesh.CFrame:PointToWorldSpace(em:GetPosition(vid) * mesh.Size / mesh.MeshSize)
		table.insert(verts, { mesh = mesh, em = em, vid = vid, y = p.Y })
	end
end
table.sort(verts, function(a, b) return a.y < b.y end)
local lowest = {}
for i = 1, math.min(200, #verts) do lowest[i] = verts[i] end

local function dominantBone(em, vid)
	local ok, ids, weights = pcall(function() return em:GetVertexBoneWeights(vid) end)
	if not ok or not ids or #ids == 0 then return nil end
	local best, bestW = ids[1], weights[1]
	for i = 2, #ids do
		if weights[i] > bestW then best, bestW = ids[i], weights[i] end
	end
	local ok2, name = pcall(function() return em:GetBoneName(best) end)
	return ok2 and bones[name] or nil
end

local minY, feetMesh = math.huge, nil
for _, v in lowest do
	local bone = dominantBone(v.em, v.vid)
	if bone then
		local mesh = v.mesh
		local localOffset = v.em:GetPosition(v.vid) * mesh.Size / mesh.MeshSize
		local worldP = bone.TransformedWorldCFrame:PointToWorldSpace(bone.CFrame:PointToObjectSpace(mesh.CFrame:PointToWorldSpace(localOffset)))
		if worldP.Y < minY then minY, feetMesh = worldP.Y, mesh.Name end
	end
end
if minY == math.huge then minY, feetMesh = lowest[1].y, lowest[1].mesh.Name end -- no skin data: fall back to the rest read
for _, em in ems do em:Destroy() end

local gap = minY - planeTop
model:Destroy()
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ gap = gap, lod = "{{LOD}}",
	measuredAt = bottom, settledMeasure = settled ~= nil, feetMesh = feetMesh,
	-- Which context this ran in, reported rather than assumed: the far-LOD row
	-- is only a measurement of its own when the vertex read happens in Play,
	-- which needs the experience's Mesh & Image API setting.
	inPlay = RunService:IsRunning() })
print(runnerResult)
return runnerResult
