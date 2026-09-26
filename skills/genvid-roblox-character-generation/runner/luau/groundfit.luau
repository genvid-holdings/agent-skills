-- Ground-fit (spec §2.1 stage 4): HipHeight from bone geometry, spawn attributes,
-- foot-plant + head look-at IKControls emitted on the template. Replaces the
-- August posture/roll/drop dials.
local HttpService = game:GetService("HttpService")
local AssetService = game:GetService("AssetService")
local model = {{MODEL_PATH}}
local scale = tonumber("{{SCALE}}") or 1
local height = tonumber("{{HEIGHT}}")
assert(height and height > 0, "groundfit needs the character's height in studs ({{HEIGHT}})")
local meshes = {}
for _, d in model:GetDescendants() do if d:IsA("MeshPart") then table.insert(meshes, d) end end
assert(#meshes > 0, "no MeshPart")
local bones = {}
for _, d in model:GetDescendants() do if d:IsA("Bone") then bones[d.Name] = d end end
local lower, upper = bones.LowerTorso, bones.UpperTorso
assert(lower and upper, "LowerTorso/UpperTorso missing")
-- feet plane = lowest vertex in world space (bones sit at ankles, not soles),
-- over EVERY MeshPart: a multi-mesh import can list a small accessory mesh
-- first, and whatever geometry is lowest is what meets the ground.
local minY, feetMesh = math.huge, nil
for _, mesh in meshes do
	local id = tonumber(mesh.MeshId:match("%d+"))
	assert(id, "MeshPart " .. mesh:GetFullName() .. " has no MeshId; the feet plane cannot be measured without it")
	local em = AssetService:CreateEditableMeshAsync(Content.fromAssetId(id))
	for _, vid in em:GetVertices() do
		local p = mesh.CFrame:PointToWorldSpace(em:GetPosition(vid) * mesh.Size / mesh.MeshSize)
		if p.Y < minY then minY, feetMesh = p.Y, mesh.Name end
	end
	em:Destroy()
end
local lt, ut = lower.WorldPosition, upper.WorldPosition
-- HumanoidRootPart size from BODY HEIGHT, not from spine spacing. The bone gap
-- 2 * (UpperTorso.Y - LowerTorso.Y) is a property of the skeleton: a Mixamo-
-- convention rig maps Spine2 (high on the chest) to UpperTorso and gives h = 22
-- studs on a 50-stud character where the other bake-off legs read 7.7-8.3. The
-- oversized box then ate half the hip height and E12 failed a rig whose feet
-- were fine (0.234, witnessed 2026-09-04). wire.luau builds the real part from
-- the same rule -- change one and the other must follow, or HipHeight and the
-- box it is measured against disagree.
local h = 0.15 * height
local rootSize = Vector3.new(0.9 * h, h, 0.5 * h)
-- soleOffset: HRP bottom to the lowest vertex, at rest. The ground-fit settle
-- loop reads this back and corrects it by the rig's measured hover constant.
local sole = (lt.Y - minY) - rootSize.Y / 2
model:SetAttribute("SkinnedRig", true)
-- TWO numbers, two consumers, and using one for the other floats or sinks the
-- rig by the hover constant e (0.45 / 0.89 / 1.03 studs on the bake-off legs):
--   {{SOLE_ATTR}}  -- the geometric HRP-bottom-to-lowest-vertex distance
--                       measured above. ANCHORED placement reads it (the
--                       placement rule: pivot = pedestal + {{SOLE_ATTR}} + HRP.Size.Y/2).
--                       Written once, here, and never corrected: geometry does
--                       not move when the engine's hover is measured.
--   {{HIP_ATTR}}     -- what a LIVE Humanoid.HipHeight needs for the soles to
--                       touch. Seeded with the sole offset so `settle` has a
--                       hip to measure against, then overwritten by `sethip`
--                       with soleOffset - e once the settle has run.
model:SetAttribute("{{SOLE_ATTR}}", sole)
local hip = sole
model:SetAttribute("{{HIP_ATTR}}", hip)
model:SetAttribute("IKLook", true)
model:SetAttribute("GroundFitScale", scale)
local hum = model:FindFirstChildOfClass("Humanoid") or Instance.new("Humanoid", model)
-- The importer creates NO Humanoid for a skinned R15 FBX, so the one above is
-- almost always this script's own -- and a fresh Humanoid defaults to RigType
-- R6. An R6 Humanoid never advances an R15 bone KeyframeSequence: the track
-- loads and reports the right Length while TimePosition stays 0 (witnessed
-- 2026-09-04; the same published clip advanced on the R15 July template). Set
-- unconditionally, so a Humanoid that arrived some other way is corrected too.
hum.RigType = Enum.HumanoidRigType.R15
local function ik(name, kind, chainRoot, endEff)
	local c = hum:FindFirstChild(name) or Instance.new("IKControl")
	c.Name = name; c.Type = kind; c.ChainRoot = chainRoot; c.EndEffector = endEff
	c.Enabled = false; c.Weight = 1; c.SmoothTime = 0.1; c.Parent = hum
	return c
end
ik("LeftFootIK", Enum.IKControlType.Position, bones.LeftUpperLeg, bones.LeftFoot)
ik("RightFootIK", Enum.IKControlType.Position, bones.RightUpperLeg, bones.RightFoot)
local look = ik("HeadLookIK", Enum.IKControlType.LookAt, bones.UpperTorso, bones.Head)
look.Weight = 0.6
-- soleOffsetAttribute is read back off the model, not echoed: the anchored-
-- placement consumer reads the ATTRIBUTE, so the attribute is what has to be
-- shown to have landed.
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ hipHeight = hip, feetPlane = minY,
	feetMesh = feetMesh, meshCount = #meshes,
	rootSize = { rootSize.X, rootSize.Y, rootSize.Z }, lowerTorsoY = lt.Y, upperTorsoY = ut.Y,
	soleOffset = sole, soleOffsetAttribute = model:GetAttribute("{{SOLE_ATTR}}"),
	targetHeight = height,
	rigTypeR15 = hum.RigType == Enum.HumanoidRigType.R15 })
print(runnerResult)
return runnerResult
