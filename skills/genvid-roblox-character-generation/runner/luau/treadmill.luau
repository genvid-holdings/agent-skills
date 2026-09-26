-- Treadmill: play the walk at speed {{SPEED}} on a stationary clone, track the LeftFoot bone's
-- forward sweep while it is the planted foot, report studs/s. Offline estimates are
-- untrustworthy (skill §3 treadmill rule); this is the measurement.
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local height = tonumber("{{HEIGHT}}")
assert(height and height > 0, "treadmill needs the character's height in studs ({{HEIGHT}})")
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
-- fadeTime matches Play's fade-in argument below: a sample taken while the
-- track is still blending in from the bind pose can hold the foot above OR
-- below its true planted low, so both the low-point scan and the
-- planted-window scan in measureStride skip every sample still inside the
-- fade. Witnessed on a 30-stud rig: the fade-in blend dipped the foot below
-- its true planted low, so the planted foot sat 0.52 studs above THAT
-- (wrong) floor -- outside the fixed 0.5-stud window -- and only the fade-in
-- samples themselves read as planted, giving the fast blend's own speed,
-- 46.78 studs/s, twice.
local fadeTime = 0.1
local track = animator:LoadAnimation(anim); track.Looped = true; track:Play(fadeTime, 1, {{SPEED}})
local foot = nil
for _, d in m:GetDescendants() do if d:IsA("Bone") and d.Name == "LeftFoot" then foot = d end end
-- MEASURE_STRIDE_BEGIN -- pure function, no Roblox API: kept isolable (by
-- these markers) so a test can run this exact source under a bare Luau
-- interpreter on a synthetic samples table, feeding both the OLD arguments
-- (fadeTime = 0, window = 0.5) and the new ones below to prove what changed
-- and what did not.
local function measureStride(samples, fadeTime, window)
	-- planted phases: foot near its lowest height (fade-in samples excluded
	-- from the floor itself, not just from counting as planted -- a floor
	-- pulled down by a fade-in dip would still let fade-in samples back into
	-- the window); sweep = |dz/dt| averaged over planted samples
	local minY = math.huge
	for _, s in samples do if s.t >= fadeTime then minY = math.min(minY, s.y) end end
	local sum, n = 0, 0
	for i = 2, #samples do
		local a, b = samples[i - 1], samples[i]
		if a.t >= fadeTime and b.y < minY + window and a.y < minY + window then
			local v = math.abs(b.z - a.z) / (b.t - a.t)
			if v < 200 then sum += v; n += 1 end
		end
	end
	return (n > 0 and sum / n or 0), n
end
-- MEASURE_STRIDE_END
local samples = {}
local t0 = os.clock()
while os.clock() - t0 < 4 do
	RunService.Heartbeat:Wait()
	local p = foot.TransformedWorldCFrame.Position
	table.insert(samples, { t = os.clock() - t0, y = p.Y, z = p.Z })
end
-- The planted window is 0.5 studs at the height-20 baseline; scaling it by
-- height/20 keeps that BOUND unchanged there (0.75 at height 30, which read
-- 22.80/22.88/22.68 studs/s in the verification run this fix is based on).
-- The bound is unchanged at height 20 -- the READING is not: excluding
-- fade-in samples from the floor and from counting as planted changes every
-- rig's samples toward a truer reading, including a height-20 rig's.
local window = 0.5 * height / 20
local stride = measureStride(samples, fadeTime, window)
m:Destroy()
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ strideStudsPerSec = stride, samples = #samples, clipLength = track.Length })
print(runnerResult)
return runnerResult
