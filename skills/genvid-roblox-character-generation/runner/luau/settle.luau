-- PLAY mode, Server. Measures this rig's HOVER CONSTANT: standing still, a
-- Humanoid holds its HumanoidRootPart bottom at HipHeight + e, and e is constant
-- per rig (witnessed 2026-09-04: 0.45 / 0.89 / 1.03 studs across the three
-- bake-off legs). One settle measures it; groundfit's closed form
-- hip = soleOffset - e then converges in a single correction.
--
-- Standing, never walking: the first attempt subtracted a gap read mid-walk
-- (5.14 / 4.26 / 2.33 studs) as if it were the standing one and overshot the
-- floor by several studs.
local HttpService = game:GetService("HttpService")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]

local plane = workspace:FindFirstChild("_SettlePlane")
if not plane then
	plane = Instance.new("Part"); plane.Name = "_SettlePlane"
	plane.Size = Vector3.new(400, 1, 400); plane.Anchored = true; plane.CanCollide = true
	plane.CFrame = CFrame.new(0, -0.5, 0); plane.Parent = workspace
end
local planeTop = plane.Position.Y + plane.Size.Y / 2

local model = template:Clone(); model.Parent = workspace
local hum = model:FindFirstChildOfClass("Humanoid")
assert(hum, "settle needs the wired template's Humanoid")
local hrp = model.PrimaryPart or model:FindFirstChild("HumanoidRootPart")
assert(hrp, "settle needs a HumanoidRootPart")
local hip = model:GetAttribute("{{HIP_ATTR}}") or hum.HipHeight
assert(typeof(hip) == "number", "run groundfit and wire before settle")
-- dropped in from a body height up, so the settle is the engine's, not the
-- placement's
model:PivotTo(CFrame.new(0, planeTop + hip + hrp.Size.Y, 0))
task.wait(3)

local bottom = hrp.Position.Y - hrp.Size.Y / 2 - planeTop
local _, tiltY, _ = hrp.CFrame:ToEulerAnglesXYZ()
model:Destroy()
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ settledBottom = bottom, hip = hip,
	hoverExcess = bottom - hip, rootSizeY = hrp.Size.Y, yaw = tiltY })
print(runnerResult)
return runnerResult
