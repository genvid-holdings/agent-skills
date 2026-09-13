-- Dump the imported rig's bone rest frames (parent, rot 3x3 row-major, pos), the
-- shape stage_h_poses.py reads. LowerTorso's parent is written as HumanoidRootPart.
local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
local bones = {}
for _, d in model:GetDescendants() do
	if d:IsA("Bone") then bones[d.Name] = d end
end
local R15 = { "LowerTorso","UpperTorso","Head","LeftUpperArm","LeftLowerArm","LeftHand","RightUpperArm",
	"RightLowerArm","RightHand","LeftUpperLeg","LeftLowerLeg","LeftFoot","RightUpperLeg","RightLowerLeg","RightFoot" }
local out = {}
for _, n in R15 do
	local b = bones[n]
	assert(b, "missing bone " .. n)
	local parent = b.Parent
	local pname = (parent and parent:IsA("Bone") and parent.Name ~= "HumanoidRootNode") and parent.Name or "HumanoidRootPart"
	local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = b.CFrame:GetComponents()
	out[n] = { parent = pname, rot = { r00, r01, r02, r10, r11, r12, r20, r21, r22 }, pos = { x, y, z } }
end
print("RUNNER_RESULT " .. HttpService:JSONEncode(out))
