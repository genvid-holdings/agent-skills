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
local CORNERS = { -0.5, 0.5 }
-- Height and centre come from the WORLD-AXIS extent of the mesh's own part
-- corners, never Model:GetBoundingBox(): that box is reported in the PIVOT
-- frame, and the importer leaves a freshly imported skinned Model's pivot
-- rotated 90 degrees about X, so its Y is the character's depth (witnessed
-- 2026-09-04 on all three bake-off imports, scale.luau/zoo_capture.luau's own
-- note). Restricted to MeshParts, not every BasePart: the 3D Importer's
-- bone-holder part (the root bone's parent) is not the body and would skew
-- the centre if it sat away from it.
local function meshBoxCenter(parts)
	local lo = Vector3.new(math.huge, math.huge, math.huge)
	local hi = Vector3.new(-math.huge, -math.huge, -math.huge)
	for _, mesh in parts do
		local cf, s = mesh.CFrame, mesh.Size
		for _, fx in CORNERS do
			for _, fy in CORNERS do
				for _, fz in CORNERS do
					local p = cf:PointToWorldSpace(Vector3.new(s.X * fx, s.Y * fy, s.Z * fz))
					lo = Vector3.new(math.min(lo.X, p.X), math.min(lo.Y, p.Y), math.min(lo.Z, p.Z))
					hi = Vector3.new(math.max(hi.X, p.X), math.max(hi.Y, p.Y), math.max(hi.Z, p.Z))
				end
			end
		end
	end
	return (lo + hi) / 2
end
-- Hip/root reference point for the sole-offset measurement below. LowerTorso
-- when the rig has one (an R15-shaped rig -- byte-identical to before this
-- change); no step requires it, so a rig with no such bone (a
-- spider rooted at GroundRoot, a vendor rig rooted at Hips) falls back to the
-- mesh's own geometric centre, no bone name needed at all. wire.luau places
-- HumanoidRootPart at the same point by the same rule -- HipHeight is
-- measured against the box wire builds, so the two must agree or the rig
-- floats or sinks by half the difference (see the box-height note below).
-- `hipBone` records which: the literal bone name a rest-frame reader (eval_cmd's
-- feet_y) can look up rest.json by, or false when there is none to look up.
local upper = bones.UpperTorso
local hipBone = bones.LowerTorso and "LowerTorso" or false
local lt
if bones.LowerTorso then
	lt = bones.LowerTorso.WorldPosition
else
	lt = meshBoxCenter(meshes)
end
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
local ut = upper and upper.WorldPosition or nil
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
-- Foot IK chains are built only for feet the rig has (the classic R15 names,
-- as today, when present); a rig without them (a spider's own leg bones) gets
-- no foot IK at all rather than indexing a nil chain root/end effector.
if bones.LeftUpperLeg and bones.LeftFoot then
	ik("LeftFootIK", Enum.IKControlType.Position, bones.LeftUpperLeg, bones.LeftFoot)
end
if bones.RightUpperLeg and bones.RightFoot then
	ik("RightFootIK", Enum.IKControlType.Position, bones.RightUpperLeg, bones.RightFoot)
end
-- Head is required on every rig (rig ingest refuses one with none); the
-- head-look chain runs from ITS OWN
-- parent rather than a fixed UpperTorso, so an own-skeleton rig's neck/head
-- hierarchy is followed whatever it's named. Byte-identical on an R15-shaped
-- rig, where Head's parent is UpperTorso.
local look = ik("HeadLookIK", Enum.IKControlType.LookAt, bones.Head.Parent, bones.Head)
look.Weight = 0.6
-- soleOffsetAttribute is read back off the model, not echoed: the anchored-
-- placement consumer reads the ATTRIBUTE, so the attribute is what has to be
-- shown to have landed.
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local resultTable = { hipHeight = hip, feetPlane = minY,
	feetMesh = feetMesh, meshCount = #meshes,
	-- lowerTorsoY keeps its name (eval_cmd.py reads this key regardless of
	-- which bone or point it names): the hip/root reference's Y, whichever
	-- of the two branches above set `lt`. hipBone names WHICH: a rest.json key
	-- (eval_cmd's feet_y reads it) or false when the reference is the mesh's
	-- own centre, not a bone -- there is no rest-frame entry to carry that
	-- plane across, and feet_y must read that as "cannot place the plane,"
	-- not silently subtract a different bone's height.
	rootSize = { rootSize.X, rootSize.Y, rootSize.Z }, lowerTorsoY = lt.Y, hipBone = hipBone,
	soleOffset = sole, soleOffsetAttribute = model:GetAttribute("{{SOLE_ATTR}}"),
	targetHeight = height,
	rigTypeR15 = hum.RigType == Enum.HumanoidRigType.R15 }
-- upperTorsoY is diagnostic only (eval_cmd's E12 readings, report-only); an
-- own-skeleton rig with no UpperTorso simply omits it, which that row already
-- tolerates (None when either side of the spine-spacing reading is missing).
if ut then resultTable.upperTorsoY = ut.Y end
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode(resultTable)
print(runnerResult)
return runnerResult
