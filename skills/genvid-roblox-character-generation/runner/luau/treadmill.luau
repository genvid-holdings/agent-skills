-- Treadmill: play the walk at speed {{SPEED}} on a stationary clone, track the LeftFoot bone's
-- forward sweep while it is the planted foot, report studs/s. Offline estimates are
-- untrustworthy (skill §3 treadmill rule); this is the measurement.
-- Run it in Play: a track's TimePosition advances only while the world runs, so in
-- Edit the foot never moves and the stride would read 0.
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
assert(RunService:IsRunning(), "treadmill runs in Play, not Edit: a track's time does not advance in Edit")
local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local height = tonumber("{{HEIGHT}}")
assert(height and height > 0, "treadmill needs the character's height in studs ({{HEIGHT}})")
-- MEASURE_STRIDE_BEGIN -- pure function, no Roblox API: kept isolable (by
-- these markers) so a test can run this exact source under a bare Luau
-- interpreter on a synthetic samples table, feeding both the OLD arguments
-- (fadeTime = 0, window = 0.5) and the new ones below to prove what changed
-- and what did not.
local function measureStride(samples, fadeTime, window)
	-- planted phases: foot near its lowest height (fade-in samples excluded
	-- from the floor itself, not just from counting as planted -- a floor
	-- pulled down by a fade-in dip would still let fade-in samples back into
	-- the window). Each unbroken planted run is one stance: the stride is the
	-- foot's net travel over every stance divided by their time, so a held-pose
	-- walk (the foot holds, then snaps) reads the same as a smooth one. A
	-- per-sample-pair average cannot: it has to drop a snap as a glitch.
	-- Returns the stride and the number of stances it was read over.
	local minY = math.huge
	for _, s in samples do if s.t >= fadeTime then minY = math.min(minY, s.y) end end
	local travel, time, stances = 0, 0, 0
	local first, last = nil, nil
	local function close()
		if first and last.t > first.t then
			travel += math.abs(last.z - first.z); time += last.t - first.t; stances += 1
		end
		first, last = nil, nil
	end
	for _, s in samples do
		if s.t >= fadeTime and s.y < minY + window then
			first = first or s; last = s
		else
			close()
		end
	end
	close()
	return (time > 0 and travel / time or 0), stances
end
-- MEASURE_STRIDE_END
local m = template:Clone(); m.Parent = workspace; m:PivotTo(CFrame.new(0, 200, 0))
-- Everything that uses the clone runs under pcall, so a failure (a walk id that
-- will not load, a missing bone) still destroys it before the error is raised.
local ok, result = pcall(function()
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
	-- A track's Length reads 0 until its animation has loaded, and the sampling
	-- window below is sized from it: load it first, and refuse a Length still 0.
	game:GetService("ContentProvider"):PreloadAsync({ anim })
	local track = animator:LoadAnimation(anim); track.Looped = true; track:Play(fadeTime, 1, {{SPEED}})
	-- FOOT_BONE defaults to "LeftFoot" (studio.emit's RENDER_DEFAULTS); a rig kept
	-- on its own skeleton with no bone by that name cannot be
	-- treadmilled at all, so the run is reported rather than indexing a nil foot.
	local foot = nil
	for _, d in m:GetDescendants() do if d:IsA("Bone") and d.Name == "{{FOOT_BONE}}" then foot = d end end
	if not foot then
		return { strideStudsPerSec = nil, samples = 0, clipLength = track.Length,
			missingBones = { "{{FOOT_BONE}}" } }
	end
	-- Sample 1.25 played loops past the fade-in, and never less than 4 s: a slow
	-- walk played below speed 1 can take longer than 4 s a loop, and a window
	-- shorter than one loop may hold no whole stance at all.
	if not (track.Length > 0) then
		error("the walk's track.Length is still 0 after loading it, so the sampling window cannot be sized "
			.. "to its loop: check {{WALK_ID}} is an animation this place can load", 0)
	end
	local sampleSecs = math.max(4, 1.25 * track.Length / math.max({{SPEED}}, 1e-3) + fadeTime)
	local samples = {}
	local t0 = os.clock()
	local timeFirst = nil
	while os.clock() - t0 < sampleSecs do
		RunService.Heartbeat:Wait()
		timeFirst = timeFirst or track.TimePosition
		local p = foot.TransformedWorldCFrame.Position
		table.insert(samples, { t = os.clock() - t0, y = p.Y, z = p.Z })
	end
	-- A track that never advanced is a clip that did not play (Edit mode, or an
	-- AnimationController left beside the Humanoid): refuse it, never read a 0.
	if track.TimePosition == timeFirst then
		error("the walk's TimePosition never advanced over the sample window: the track did not play "
			.. "(run the treadmill in Play)", 0)
	end
	-- The planted window is 0.5 studs at the height-20 baseline; scaling it by
	-- height/20 keeps that BOUND unchanged there (0.75 at height 30, which read
	-- 22.80/22.88/22.68 studs/s in the verification run this fix is based on).
	-- The bound is unchanged at height 20 -- the READING is not: excluding
	-- fade-in samples from the floor and from counting as planted changes every
	-- rig's samples toward a truer reading, including a height-20 rig's.
	local window = 0.5 * height / 20
	local stride, stances = measureStride(samples, fadeTime, window)
	return { strideStudsPerSec = stride, stances = stances, samples = #samples, sampleSecs = sampleSecs,
		clipLength = track.Length }
end)
m:Destroy()
if not ok then
	error(result, 0)
end
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode(result)
print(runnerResult)
return runnerResult
