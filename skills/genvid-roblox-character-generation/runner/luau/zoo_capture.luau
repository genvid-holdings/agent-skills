-- Height and centre come from the WORLD-AXIS extent of the model's part corners,
-- never Model:GetBoundingBox(): that box is reported in the PIVOT frame, and the
-- importer leaves a freshly imported skinned Model's pivot rotated 90 degrees
-- about X, so its Y is the character's depth (witnessed 2026-09-04 on all three
-- bake-off imports). A camera framed on that number frames the wrong body.
local HttpService = game:GetService("HttpService")
local model = workspace:FindFirstChild("{{TEMPLATE}}", true) or ({{PARK_FOLDER}})["{{TEMPLATE}}"]

local CORNERS = { -0.5, 0.5 }

local function worldBox(m)
	local lo = Vector3.new(math.huge, math.huge, math.huge)
	local hi = Vector3.new(-math.huge, -math.huge, -math.huge)
	local found = false
	for _, d in m:GetDescendants() do
		if d:IsA("BasePart") then
			local cf, s = d.CFrame, d.Size
			for _, fx in CORNERS do
				for _, fy in CORNERS do
					for _, fz in CORNERS do
						local p = cf:PointToWorldSpace(Vector3.new(s.X * fx, s.Y * fy, s.Z * fz))
						lo = Vector3.new(math.min(lo.X, p.X), math.min(lo.Y, p.Y), math.min(lo.Z, p.Z))
						hi = Vector3.new(math.max(hi.X, p.X), math.max(hi.Y, p.Y), math.max(hi.Z, p.Z))
						found = true
					end
				end
			end
		end
	end
	assert(found, "no BasePart under the model to frame")
	return (lo + hi) / 2, hi - lo
end

local center, size = worldBox(model)
local dist = ("{{CAMERA}}" == "far") and 260 or 40
local cam = workspace.CurrentCamera
cam.CameraType = Enum.CameraType.Scriptable
cam.CFrame = CFrame.lookAt(center + Vector3.new(dist * 0.6, size.Y * 0.35, dist * 0.8), center)
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ camera_position = { cam.CFrame.Position.X, cam.CFrame.Position.Y, cam.CFrame.Position.Z },
	look_at = { center.X, center.Y, center.Z }, height = size.Y })
print(runnerResult)
return runnerResult
