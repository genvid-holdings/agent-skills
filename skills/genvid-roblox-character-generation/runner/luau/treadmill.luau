-- Treadmill: play the walk at speed {{SPEED}} on a stationary clone, track the LeftFoot bone's
-- forward sweep while it is the planted foot, report studs/s. Offline estimates are
-- untrustworthy (skill §3 treadmill rule); this is the measurement.
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local m = template:Clone(); m.Parent = workspace; m:PivotTo(CFrame.new(0, 200, 0))
-- An AnimationController beside the Humanoid stops every AnimationTrack
-- advancing, on both Animators (witnessed 2026-09-04 -- the dead treadmill).
-- wire.luau destroys it on the template; this clone destroys any that survived,
-- so a stride of 0 is a real stride of 0 and not this defect wearing its face.
for _, d in m:GetDescendants() do if d:IsA("AnimationController") then d:Destroy() end end
for _, d in m:GetDescendants() do if d:IsA("BasePart") then d.Anchored = true end end
local hum = m:FindFirstChildOfClass("Humanoid")
local animator = hum:FindFirstChildOfClass("Animator") or Instance.new("Animator", hum)
local anim = Instance.new("Animation"); anim.AnimationId = "{{WALK_ID}}"
-- {{SPEED}} is 1 for the raw measurement and animSpeedScale for the post-scale one
-- (E19 compares the post-scale stride against walkSpeed; a stride measured at speed 1
-- can only ever agree with the number it was used to derive).
local track = animator:LoadAnimation(anim); track.Looped = true; track:Play(0.1, 1, {{SPEED}})
local foot = nil
for _, d in m:GetDescendants() do if d:IsA("Bone") and d.Name == "LeftFoot" then foot = d end end
local samples = {}
local t0 = os.clock()
while os.clock() - t0 < 4 do
	RunService.Heartbeat:Wait()
	local p = foot.TransformedWorldCFrame.Position
	table.insert(samples, { t = os.clock() - t0, y = p.Y, z = p.Z })
end
-- planted phases: foot near its lowest height; sweep = |dz/dt| averaged over planted samples
local minY = math.huge
for _, s in samples do minY = math.min(minY, s.y) end
local sum, n = 0, 0
for i = 2, #samples do
	local a, b = samples[i - 1], samples[i]
	if b.y < minY + 0.5 and a.y < minY + 0.5 then
		local v = math.abs(b.z - a.z) / (b.t - a.t)
		if v < 200 then sum += v; n += 1 end
	end
end
m:Destroy()
print("RUNNER_RESULT " .. HttpService:JSONEncode({ strideStudsPerSec = n > 0 and sum / n or 0, samples = #samples, clipLength = track.Length }))
