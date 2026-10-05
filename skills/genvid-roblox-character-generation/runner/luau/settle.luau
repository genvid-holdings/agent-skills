-- PLAY mode, Server. Measures this rig's HOVER CONSTANT: standing still, a
-- Humanoid holds its HumanoidRootPart bottom at HipHeight + e, and e is constant
-- per rig. One settle measures it; groundfit's closed form hip = soleOffset - e
-- then converges in a single correction.
--
-- Standing, never walking: a gap read mid-walk is not the standing one.
--
-- Four refusals, each of which would otherwise return a false hover:
--   * Edit mode: nothing simulates, so the hover reads exactly HRP.Size.Y/2 and
--     a verify settle passes on it.
--   * The plane is built far from any world: in a game place's Play the world is
--     generated around the origin, and a clone dropped there stands on world
--     geometry. The plane sits at PLANE_AT; _SettlePlane is referenced only by
--     this step.
--   * The floor under the clone must be the plane.
--   * The clone must have moved during the wait (an anchored root, or paused
--     physics, measures nothing).
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
if not RunService:IsRunning() then
	error("settle: run this in Play (Server datamodel); in Edit nothing simulates and the hover it reads is false")
end

local PLANE_AT = Vector3.new(20000, 5000, 20000)
local MOVED_MIN = 0.01
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]

local plane = workspace:FindFirstChild("_SettlePlane")
if not plane then
	plane = Instance.new("Part"); plane.Name = "_SettlePlane"
	plane.Size = Vector3.new(400, 1, 400); plane.Anchored = true; plane.CanCollide = true
	plane.Parent = workspace
end
plane.CFrame = CFrame.new(PLANE_AT)
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
model:PivotTo(CFrame.new(PLANE_AT.X, planeTop + hip + hrp.Size.Y, PLANE_AT.Z))
local droppedY = hrp.Position.Y
task.wait(3)

if math.abs(hrp.Position.Y - droppedY) < MOVED_MIN then
	model:Destroy()
	error("settle: the clone never moved during the wait (is its root anchored, or is physics paused?); no hover measured")
end
local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude
params.FilterDescendantsInstances = { model }
local hit = workspace:Raycast(hrp.Position, Vector3.new(0, -(hip + hrp.Size.Y + 10), 0), params)
if not hit or hit.Instance ~= plane then
	local under = if hit then hit.Instance:GetFullName() else "nothing"
	model:Destroy()
	error("settle: the clone stands on " .. under .. ", not _SettlePlane; no hover measured")
end

local bottom = hrp.Position.Y - hrp.Size.Y / 2 - planeTop
local _, tiltY, _ = hrp.CFrame:ToEulerAnglesXYZ()
model:Destroy()
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ settledBottom = bottom, hip = hip,
	hoverExcess = bottom - hip, rootSizeY = hrp.Size.Y, yaw = tiltY })
print(runnerResult)
return runnerResult
