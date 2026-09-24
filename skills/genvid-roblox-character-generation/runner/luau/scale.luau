-- Edit mode; right after the import click, BEFORE dump_rest and groundfit.
--
-- Height is measured from the WORLD-AXIS extent of the model's part corners,
-- never Model:GetBoundingBox().Y. The Roblox importer leaves a freshly imported
-- skinned Model's pivot rotated 90 degrees about X, and GetBoundingBox reports
-- the box in the PIVOT frame, so its Y is the character's DEPTH. Witnessed
-- 2026-09-04 on all three bake-off imports: scaling on that number produced
-- 197/160/180-stud rigs where 50 was asked for.
local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
local target = tonumber("{{HEIGHT}}")

local CORNERS = { -0.5, 0.5 }

local function worldHeight(m)
	local minY, maxY = math.huge, -math.huge
	for _, d in m:GetDescendants() do
		if d:IsA("BasePart") then
			local cf, s = d.CFrame, d.Size
			for _, fx in CORNERS do
				for _, fy in CORNERS do
					for _, fz in CORNERS do
						local p = cf:PointToWorldSpace(Vector3.new(s.X * fx, s.Y * fy, s.Z * fz))
						if p.Y < minY then minY = p.Y end
						if p.Y > maxY then maxY = p.Y end
					end
				end
			end
		end
	end
	if minY == math.huge then return 0 end
	return maxY - minY
end

local before = worldHeight(model)
assert(before > 0, "no BasePart under the model to measure")
if target then model:ScaleTo(model:GetScale() * target / before) end
task.wait()
local after = worldHeight(model)
-- pivotHeight is reported alongside so a reviewer can SEE the pivot-frame trap
-- rather than take it on trust: on a fresh import the two disagree.
local _, pivotSize = model:GetBoundingBox()
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ heightBefore = before, heightAfter = after,
	scale = model:GetScale(), pivotHeight = pivotSize.Y })
print(runnerResult)
return runnerResult
