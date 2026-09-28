-- Dump the imported rig's bone rest frames (parent, rot 3x3 row-major, pos), the
-- shape stage_h_poses.py reads: every Bone under the model except the root node,
-- so a rig's extra bones (wings, a jaw, cloth) reach the pose transfer beside
-- whatever bones the rig's own skeleton carries. No step requires any fixed
-- bone name: a rig is dumped bone-for-bone, whatever it's
-- named, and this step asserts nothing about which names are present.
--
-- A bone literally named "HumanoidRootNode" (the importer/Animator's own
-- convention, still how an R15-shaped rig's synthesized root reads) is
-- excluded from the dump and its direct children are promoted to
-- HumanoidRootPart, exactly as before. A rig with no such bone (a prepped
-- rig keeps its own skeleton end to end; nothing inserts one) keeps its own
-- root bone IN the dump: that bone's
-- parent is not a Bone at all, so it is itself promoted to HumanoidRootPart --
-- the one root-level entry poses.py's `root_name` (the sole bone whose parent
-- is "HumanoidRootPart") then finds. A bone whose parent is the root node (or
-- not a Bone) is written with HumanoidRootPart as its parent, and its frame is
-- expressed in the root node's frame when one exists: a bone skinned under a
-- second MeshPart has a CFrame relative to THAT part, so it is carried
-- through the part's CFrame. With no root node, a root-level bone's own local
-- CFrame is kept as-is -- there is no synthetic frame to re-express it in.
local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
local bones = {}
local rootNode = nil
for _, d in model:GetDescendants() do
	if d:IsA("Bone") then
		if d.Name == "HumanoidRootNode" then
			rootNode = d
		else
			-- rest.json is keyed by name, and a KeyframeSequence Pose matches a
			-- bone by name: two bones with one name cannot both be represented
			assert(bones[d.Name] == nil, "duplicate bone name " .. d.Name)
			bones[d.Name] = d
		end
	end
end
-- rest-pose world frame of a bone or part, composed from the CFrames alone
local function worldOf(inst)
	if inst:IsA("Bone") then return worldOf(inst.Parent) * inst.CFrame end
	return inst.CFrame
end
local out = {}
for n, b in bones do
	local parent = b.Parent
	local isRoot = not (parent and parent:IsA("Bone") and parent ~= rootNode)
	local pname = isRoot and "HumanoidRootPart" or parent.Name
	local cf = b.CFrame
	if isRoot and rootNode and parent ~= rootNode then
		cf = worldOf(rootNode):Inverse() * worldOf(parent) * cf
	end
	local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = cf:GetComponents()
	out[n] = { parent = pname, rot = { r00, r01, r02, r10, r11, r12, r20, r21, r22 }, pos = { x, y, z } }
end
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode(out)
print(runnerResult)
return runnerResult
