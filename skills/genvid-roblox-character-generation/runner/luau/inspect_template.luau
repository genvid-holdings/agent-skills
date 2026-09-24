-- Witness the parked template's real structure (attribute names and
-- their holders, the Humanoid NumberValues, the AlignOrientation settings) so
-- wire.luau reproduces what is on disk rather than a reading of the skill text.
local HttpService = game:GetService("HttpService")
local model = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local hum = model:FindFirstChildOfClass("Humanoid")
-- rigType and animationControllers are gates: an R6 Humanoid loads an R15
-- bone clip and never advances it, and an
-- AnimationController left beside the Humanoid stops BOTH Animators advancing
-- (witnessed 2026-09-04). Reported here so the template can be read back
-- independently of the wire step's own self-check.
local controllers = 0
for _, d in model:GetDescendants() do
	if d:IsA("AnimationController") then controllers += 1 end
end
local out = { attributes = model:GetAttributes(), humanoidChildren = {}, humanoidAttributes = hum and hum:GetAttributes() or {}, hrp = nil, constraints = {},
	rigType = hum and tostring(hum.RigType) or nil,
	rigTypeR15 = hum ~= nil and hum.RigType == Enum.HumanoidRigType.R15,
	animationControllers = controllers, noAnimationController = controllers == 0 }
if hum then for _, c in hum:GetChildren() do table.insert(out.humanoidChildren, { class = c.ClassName, name = c.Name, value = c:IsA("ValueBase") and c.Value or nil }) end end
local hrp = model:FindFirstChild("HumanoidRootPart")
if hrp then out.hrp = { size = { hrp.Size.X, hrp.Size.Y, hrp.Size.Z }, children = {} }
	for _, c in hrp:GetChildren() do
		local rec = { class = c.ClassName, name = c.Name }
		if c:IsA("AlignOrientation") then rec.primaryAxis = { c.PrimaryAxis.X, c.PrimaryAxis.Y, c.PrimaryAxis.Z }; rec.mode = tostring(c.Mode); rec.alignType = tostring(c.AlignType); rec.primaryAxisOnly = c.PrimaryAxisOnly end
		table.insert(out.hrp.children, rec)
	end
end
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode(out)
print(runnerResult)
return runnerResult
