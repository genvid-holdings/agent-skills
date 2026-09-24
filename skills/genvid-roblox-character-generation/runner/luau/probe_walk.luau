-- E24: spawn-and-walk probe. Play mode; clone the parked template at a marker
-- above a flat plane, MoveTo 40 studs, and measure travel plus fall-state
-- entries and root tilt over 6 s -- the wire recipe is only proven once a real
-- Humanoid can walk on it without tripping into FallingDown/Ragdoll.
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]

local plane = workspace:FindFirstChild("_ProbeWalkPlane")
if not plane then
	plane = Instance.new("Part"); plane.Name = "_ProbeWalkPlane"
	plane.Size = Vector3.new(200, 1, 200); plane.Anchored = true; plane.CanCollide = true
	plane.CFrame = CFrame.new(0, -0.5, 0); plane.Parent = workspace
end

local model = template:Clone(); model.Parent = workspace
local hum = model:FindFirstChildOfClass("Humanoid")
local hrp = model.PrimaryPart or model:FindFirstChild("HumanoidRootPart")
local hip = model:GetAttribute("{{HIP_ATTR}}") or (hum and hum.HipHeight) or 0
model:PivotTo(CFrame.new(0, hip + 1, 0))

local falls = 0
local maxTilt = 0
local conn
if hum then
	conn = hum.StateChanged:Connect(function(_old, new)
		if new == Enum.HumanoidStateType.FallingDown or new == Enum.HumanoidStateType.Ragdoll then
			falls += 1
		end
	end)
	hum:MoveTo(Vector3.new(0, 0, -40))
end

local start = hrp.Position
local t0 = os.clock()
while os.clock() - t0 < 6 do
	RunService.Heartbeat:Wait()
	local _, _, roll = hrp.CFrame:ToEulerAnglesXYZ()
	local upDot = hrp.CFrame.UpVector:Dot(Vector3.yAxis)
	local tiltDeg = math.deg(math.acos(math.clamp(upDot, -1, 1)))
	if tiltDeg > maxTilt then maxTilt = tiltDeg end
end
if conn then conn:Disconnect() end

local travel = (hrp.Position - start).Magnitude
model:Destroy()
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ travel = travel, falls = falls, maxTilt = maxTilt })
print(runnerResult)
return runnerResult
