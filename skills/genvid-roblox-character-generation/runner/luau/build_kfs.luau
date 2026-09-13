-- EDIT mode. Build the KeyframeSequence IN STUDIO from the poses JSON the runner
-- serves over local HTTP, instead of syncing a .rbxmx through Rojo. HttpService
-- reaches 127.0.0.1 from Studio (witnessed 2026-09-04), so the clip chain needs
-- no file sync at all; the .rbxmx path stays as the fallback.
--
-- The built sequence is parked under ServerStorage/Assets/Anims/<CLIP_NAME> for
-- `publish_clip` to hand to AssetService:CreateAssetAsync. It cannot be PLAYED
-- from here: an unpublished KeyframeSequence registered through
-- KeyframeSequenceProvider:RegisterKeyframeSequence returns an id whose track
-- loads with the right Length and never advances (TimePosition stays 0, in Edit
-- and in Play/Server), and RegisterActiveKeyframeSequence errors "can only be
-- used in Solo mode". A published id advances normally in the same harness.
local HttpService = game:GetService("HttpService")
local ServerStorage = game:GetService("ServerStorage")

local doc = HttpService:JSONDecode(HttpService:GetAsync("{{POSES_URL}}"))
-- Time scale: the runner's sqrt-cadence multiplier for this character's height, the
-- same number kfs.write applies when it writes the .rbxmx (timing.scale_time).
local timeScale = tonumber("{{SCALE}}") or 1

-- Child lists, keyed by parent. A ROOT bone's parent is JSON `false` in the poses
-- doc (blender/poses.py writes False for a bone parented to HumanoidRootPart),
-- and `false` is a perfectly good table key in Lua -- so test the TYPE rather
-- than the truthiness the .rbxmx writer can get away with in Python. Keying on
-- `false` would hide every root bone in a bucket nothing reads, and the built
-- clip would come out empty of exactly the bones that drive the rig.
local kids = {}
for bone, parent in doc.hier do
	local key = (type(parent) == "string" and parent ~= "") and parent or "HumanoidRootPart"
	kids[key] = kids[key] or {}
	table.insert(kids[key], bone)
end
for _, list in kids do table.sort(list) end

local rootScale = 1 -- the template's Model:GetScale(), set below before any frame is built
local function buildPose(bone, poses, roots)
	local pose = Instance.new("Pose")
	pose.Name = bone
	local q = poses[bone]
	-- CFrame.new(x, y, z, qX, qY, qZ, qW). Position is the root motion the
	-- transfer emits under "r" for the root bone (hips delta in the bone's rest
	-- frame, studs); every other bone stays at the origin, exactly as kfs.write
	-- does. Rotation-only docs (no "r") build exactly as before.
	local r = roots and roots[bone]
	local x, y, z = 0, 0, 0
	-- divided by the model scale: the Animator multiplies a pose translation by
	-- Model:GetScale() (0.53 and 0.28 on two rigs after their scale steps;
	-- witnessed 2026-09-08: a 20-stud pose moved the 0.53 rig's hips 10.6, the
	-- same 20 set on Bone.Transform directly moved 19.4)
	if r then x, y, z = r[1] / rootScale, r[2] / rootScale, r[3] / rootScale end
	pose.CFrame = q and CFrame.new(x, y, z, q[1], q[2], q[3], q[4]) or CFrame.identity
	pose.Weight = 1
	pose.EasingStyle = Enum.PoseEasingStyle.Linear
	-- EasingDirection is left at the engine default rather than pinned to a name
	-- whose numeric value is not witnessed here.
	for _, child in (kids[bone] or {}) do
		local sub = buildPose(child, poses, roots)
		sub.Parent = pose
	end
	return pose
end

local kfs = Instance.new("KeyframeSequence")
kfs.Name = "{{CLIP_NAME}}"
kfs.Loop = ("{{LOOP}}" == "true")
kfs.Priority = Enum.AnimationPriority["{{PRIORITY}}"]
-- The pose tree must mirror the rig's real bone chain for a TRANSLATION to
-- apply: the R15-converted rigs carry HumanoidRootNode between the
-- HumanoidRootPart and LowerTorso. Rotations match by name whatever the
-- tree, but the Animator drops the root translation unless the node pose is
-- there (witnessed 2026-09-08, four variants). Identity pose, inserted when
-- the template has that bone.
local template = ({{PARK_FOLDER}}):FindFirstChild("{{TEMPLATE}}")
local hasNode = template ~= nil and template:FindFirstChild("HumanoidRootNode", true) ~= nil
rootScale = (template ~= nil and template:GetScale()) or 1
for _, fr in doc.frames do
	local frame = Instance.new("Keyframe")
	frame.Name = "Keyframe"
	frame.Time = fr.t * timeScale
	local root = buildPose("HumanoidRootPart", fr.p, fr.r)
	if hasNode then
		local node = Instance.new("Pose")
		node.Name = "HumanoidRootNode"
		node.CFrame = CFrame.identity
		node.Weight = 1
		node.EasingStyle = Enum.PoseEasingStyle.Linear
		for _, child in root:GetChildren() do
			child.Parent = node
		end
		node.Parent = root
	end
	root.Parent = frame
	frame.Parent = kfs
end

local assets = ServerStorage:FindFirstChild("Assets") or Instance.new("Folder", ServerStorage); assets.Name = "Assets"
local anims = assets:FindFirstChild("Anims") or Instance.new("Folder", assets); anims.Name = "Anims"
local prev = anims:FindFirstChild("{{CLIP_NAME}}")
if prev then prev.Name = "{{CLIP_NAME}}_prev_" .. os.time() end -- never delete; the orchestrator asks first
kfs.Parent = anims

print("RUNNER_RESULT " .. HttpService:JSONEncode({ name = kfs.Name, keyframes = #kfs:GetChildren(),
	lastTime = #doc.frames > 0 and doc.frames[#doc.frames].t * timeScale or 0,
	loop = kfs.Loop, priority = tostring(kfs.Priority), parked = kfs:GetFullName(), rootNode = hasNode, rootScale = rootScale }))
