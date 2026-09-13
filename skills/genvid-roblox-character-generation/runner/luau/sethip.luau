-- EDIT mode. Writes the ground-fit settle loop's corrected HipHeight onto the
-- PARKED template: the {{HIP_ATTR}} attribute the consuming game reads, and the live
-- Humanoid.HipHeight it is pinned from. hip = soleOffset - e, computed by
-- groundfit.corrected_hip from the standing settle -- one settle, one
-- correction (pass 4 landed at gaps of +0.006 / -0.0003 / +0.003 studs).
local HttpService = game:GetService("HttpService")
local model = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local hip = tonumber("{{HIP}}")
assert(hip, "sethip needs the corrected hip in studs ({{HIP}})")
local hum = model:FindFirstChildOfClass("Humanoid")
assert(hum, "sethip needs the wired template's Humanoid; run wire first")
-- ONLY {{HIP_ATTR}}. {{SOLE_ATTR}} is the GEOMETRIC distance groundfit
-- measured, and anchored placement (the placement rule: pivot = pedestal + {{SOLE_ATTR}}
-- + HRP.Size.Y/2) reads it; correcting it by the engine's hover constant would
-- sink a static rig into its pedestal by e.
model:SetAttribute("{{HIP_ATTR}}", hip)
-- AutomaticScalingEnabled must stay off or the engine recomputes HipHeight from
-- the avatar-scaling values and this write is silently discarded (wire.luau sets
-- it; re-asserted here because this step can run long after that one).
hum.AutomaticScalingEnabled = false
hum.HipHeight = hip
-- Read back off the live instances, never echoed: E23's hip check is a readback
-- check for exactly this reason.
print("RUNNER_RESULT " .. HttpService:JSONEncode({ hip = hip, expected_hip = hum.HipHeight,
	attribute = model:GetAttribute("{{HIP_ATTR}}"),
	soleOffsetAttribute = model:GetAttribute("{{SOLE_ATTR}}"),
	automaticScalingDisabled = not hum.AutomaticScalingEnabled }))
