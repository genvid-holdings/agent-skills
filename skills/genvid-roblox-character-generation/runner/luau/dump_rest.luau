-- Dump the imported rig's bone rest frames (parent, rot 3x3 row-major, pos), the
-- shape stage_h_poses.py reads: every Bone under the model except the root node,
-- so a rig's extra bones (wings, a jaw, cloth) reach the pose transfer beside
-- the fifteen R15 ones. A bone whose parent is the root node (or not a Bone) is
-- written with HumanoidRootPart as its parent, and its frame is expressed in
-- the root frame LowerTorso's is: a bone skinned under a second MeshPart has a
-- CFrame relative to THAT part, so it is carried through the part's CFrame.
local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
local bones = {}
for _, d in model:GetDescendants() do
	if d:IsA("Bone") and d.Name ~= "HumanoidRootNode" then
		-- rest.json is keyed by name, and a KeyframeSequence Pose matches a bone
		-- by name: two bones with one name cannot both be represented
		assert(bones[d.Name] == nil, "duplicate bone name " .. d.Name)
		bones[d.Name] = d
	end
end
local R15 = { "LowerTorso","UpperTorso","Head","LeftUpperArm","LeftLowerArm","LeftHand","RightUpperArm",
	"RightLowerArm","RightHand","LeftUpperLeg","LeftLowerLeg","LeftFoot","RightUpperLeg","RightLowerLeg","RightFoot" }
for _, n in R15 do
	assert(bones[n], "missing bone " .. n)
end
-- rest-pose world frame of a bone or part, composed from the CFrames alone
local function worldOf(inst)
	if inst:IsA("Bone") then return worldOf(inst.Parent) * inst.CFrame end
	return inst.CFrame
end
local rootParent = bones.LowerTorso.Parent
local out = {}
for n, b in bones do
	local parent = b.Parent
	local isRoot = not (parent and parent:IsA("Bone") and parent.Name ~= "HumanoidRootNode")
	local pname = isRoot and "HumanoidRootPart" or parent.Name
	local cf = b.CFrame
	if isRoot and parent ~= rootParent then
		cf = worldOf(rootParent):Inverse() * worldOf(parent) * cf
	end
	local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = cf:GetComponents()
	out[n] = { parent = pname, rot = { r00, r01, r02, r10, r11, r12, r20, r21, r22 }, pos = { x, y, z } }
end
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode(out)
print(runnerResult)
return runnerResult
