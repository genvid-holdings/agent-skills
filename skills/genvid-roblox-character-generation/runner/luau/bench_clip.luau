-- PLAY mode, SERVER datamodel. The bridge call BLOCKS until the clip has played
-- (capped at MAX_WAIT seconds; 20-25 s inside one execute_luau is fine,
-- witnessed 2026-09-10), then prints one RUNNER_RESULT.
--
-- Why a Play clone of the template with the PUBLISHED id: a parked, unpublished
-- KeyframeSequence loads with the right Length and never advances. Why
-- TransformedWorldCFrame: a Bone's other world-space readouts exclude the
-- bone's own animated Transform, so a sampler on them reads a root-motion hip
-- as 0 and the clip as "nothing moves" (false negative witnessed 2026-09-10).
-- Sole plane reference: {{HIP_ATTR}} + half the root height below the root
-- centre -- the same reference as every death-clip figure since 2026-09-10.
--
-- A non-looped AnimationTrack STOPS at its end and the Animator blends the
-- bones back to the bind pose -- so sampling past the end reports the
-- standing pose, not the death pose (false-standing witnessed live 2026-09-10:
-- hipsDrop 0, hipsBack 0, headEndAboveSole 17.7 on a clip whose mid-samples
-- showed hips at -7.9/+10.7). The game holds a death clip with
-- track:AdjustSpeed(0) just before it ends (the game's own death handler does this); this
-- bench does the same, so the verdict describes the HELD end pose. The freeze
-- is scheduled by TIME with task.delay(Length/speed - 0.05, ...), the same
-- way the game schedules it, measured from the current sample's elapsed
-- time so an asset whose Length becomes known late still freezes at the
-- clip's end -- a 0.25s poll loop cannot reliably land inside a 0.05s
-- window before the track ends and the Animator blends back (round 2,
-- witnessed live 2026-09-10: frozen false, samples 96, hipsDrop 0,
-- endedPlaying false).
local HttpService = game:GetService("HttpService")
-- FindFirstChild, not [], so the assert below is the one that reports a missing
-- template: indexing an Instance with an absent child name raises first. The
-- folder is named from the live object, never from the rendered expression --
-- that expression carries its own double quotes and cannot go inside a Luau
-- string literal.
local parkFolder = ({{PARK_FOLDER}})
local template = parkFolder:FindFirstChild("{{TEMPLATE}}")
assert(template, "bench_clip: no template {{TEMPLATE}} under " .. parkFolder:GetFullName())
local m = template:Clone()
m.Name = "Bench_" .. template.Name
for _, d in m:GetDescendants() do
	if d:IsA("BasePart") then d.Anchored = true; d.CanCollide = false end
end
local hum = m:FindFirstChildOfClass("Humanoid")
assert(hum, "bench_clip: template has no Humanoid")
hum.RigType = Enum.HumanoidRigType.R15 -- parked templates read R6 again after a place reload (2026-09-08)
local hrp = m:FindFirstChild("HumanoidRootPart")
assert(hrp, "bench_clip: template has no HumanoidRootPart")
m:PivotTo(CFrame.new(tonumber("{{BENCH_X}}") or 0, tonumber("{{BENCH_Y}}") or 300, tonumber("{{BENCH_Z}}") or 0))
m.Parent = workspace
local animator = hum:FindFirstChildOfClass("Animator") or Instance.new("Animator", hum)
local anim = Instance.new("Animation")
anim.AnimationId = "{{ANIM_ID}}"
local track = animator:LoadAnimation(anim)
track.Looped = false
track.Priority = Enum.AnimationPriority.Action
local function bone(name)
	local b = m:FindFirstChild(name, true)
	return (b and b:IsA("Bone")) and b or nil
end
local hips, head, lfoot, rfoot = bone("LowerTorso"), bone("Head"), bone("LeftFoot"), bone("RightFoot")
local soleY = -(hrp.Size.Y / 2) - (m:GetAttribute("{{HIP_ATTR}}") or 0)
local function rel(b)
	if not b then return nil end
	local p = b.TransformedWorldCFrame.Position - hrp.Position
	return { p.X, p.Y, p.Z }
end
local speed = tonumber("{{SPEED}}") or 1
local maxWait = math.min(tonumber("{{MAX_WAIT}}") or 25, 60)
track:Play(0, 1, speed)
local t0 = os.clock()
local samples = {}
local frozen, frozeAt = false, nil
local scheduled = false
while os.clock() - t0 < maxWait do
	local t = os.clock() - t0
	table.insert(samples, { t = t, tp = track.TimePosition, hips = rel(hips), head = rel(head), lfoot = rel(lfoot), rfoot = rel(rfoot) })
	if not scheduled and track.Length > 0 then
		scheduled = true
		task.delay(math.max(track.Length / speed - 0.05 - t, 0.02), function()
			if track.IsPlaying then
				track:AdjustSpeed(0)
				frozen = true
				frozeAt = os.clock() - t0
			end
		end)
	end
	if frozen and (os.clock() - t0) >= frozeAt + 0.6 then break end
	if scheduled and not frozen and not track.IsPlaying and (os.clock() - t0) > track.Length / speed + 0.3 then break end
	task.wait(0.25)
end
local first, last = samples[1], samples[#samples]
local heldAtEnd = frozen and #samples >= 3 and last.hips ~= nil and samples[#samples - 1].hips ~= nil
	and math.abs(last.hips[2] - samples[#samples - 1].hips[2]) < 0.05
local endedPlaying = track.IsPlaying
local length = track.Length
m:Destroy()
local function delta(a, b, i) if a and b then return b[i] - a[i] end return nil end
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({
	animId = "{{ANIM_ID}}", length = length, speed = speed, soleY = soleY, samples = #samples,
	hipsDrop = delta(first.hips, last.hips, 2),
	hipsBack = delta(first.hips, last.hips, 3),
	headEndAboveSole = last.head and (last.head[2] - soleY) or nil,
	heldAtEnd = heldAtEnd, endedPlaying = endedPlaying, frozen = frozen, frozeAt = frozeAt, scheduled = scheduled, timeline = samples,
})
print(runnerResult)
return runnerResult
