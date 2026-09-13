-- EDIT mode. Read what the clip chain needs from a template that is ALREADY
-- parked under the park folder (adopt.py): Model:GetScale (what
-- `clips build` divides root motion by and what build_kfs reads live), the hip
-- and sole attributes the bench uses for its sole plane, the bone list, and
-- whether the rig carries a HumanoidRootNode (build_kfs inserts the node pose
-- only when it does; a 15-bone old-pipeline rig has none and still takes the
-- LowerTorso translation, witnessed 2026-09-10).
local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
assert(model ~= nil and model:IsA("Model"), "adopt_inspect: MODEL_PATH did not resolve to a Model")
local hum = model:FindFirstChildOfClass("Humanoid")
local hrp = model:FindFirstChild("HumanoidRootPart")
local bones, hasNode = {}, false
for _, d in model:GetDescendants() do
	if d:IsA("Bone") then
		table.insert(bones, d.Name)
		if d.Name == "HumanoidRootNode" then hasNode = true end
	end
end
table.sort(bones)
print("RUNNER_RESULT " .. HttpService:JSONEncode({
	template = model.Name,
	scale = model:GetScale(),
	hip = model:GetAttribute("{{HIP_ATTR}}"),
	sole = model:GetAttribute("{{SOLE_ATTR}}"),
	hrpHeight = hrp and hrp.Size.Y or nil,
	rigTypeR15 = hum ~= nil and hum.RigType == Enum.HumanoidRigType.R15,
	hasRootNode = hasNode,
	boneCount = #bones,
	bones = bones,
}))
