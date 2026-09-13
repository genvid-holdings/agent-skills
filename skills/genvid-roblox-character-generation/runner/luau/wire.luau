-- Skinned-rig wiring (genvid-roblox-character-generation §4), scripted.
local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
-- No rescaling here: scale.luau already set the final height before the rest dump
-- and ground-fit, so {{HIP_ATTR}} is at final scale (rescaling after ground-fit
-- reproduces the August float/sink by exactly the scale factor).
local mesh = model:FindFirstChildWhichIsA("MeshPart", true)
-- 0. destroy the importer's AnimationController. The Studio importer adds one to
-- an imported skinned Model, BESIDE the Humanoid this recipe creates, and with
-- both present no AnimationTrack advances -- not on the Humanoid's Animator and
-- not on the controller's own (TimePosition stays 0 while Length resolves
-- correctly). This was the real cause of the dead treadmill witnessed
-- 2026-09-04; destroying the controller hands the rig to the Humanoid's Animator
-- and the feet move.
for _, d in model:GetDescendants() do
	if d:IsA("AnimationController") then d:Destroy() end
end
local hum = model:FindFirstChildOfClass("Humanoid") or Instance.new("Humanoid", model)
-- A Humanoid this script creates defaults to RigType R6, and an R6 Humanoid
-- never advances an R15 bone KeyframeSequence (witnessed 2026-09-04). Set it
-- unconditionally so a Humanoid that arrived some other way is corrected too.
hum.RigType = Enum.HumanoidRigType.R15
local bones = {}
for _, d in model:GetDescendants() do if d:IsA("Bone") then bones[d.Name] = d end end
-- 1. strip the importer's avatar-scaling metadata, then rebuild it
for _, n in { "BodyDepthScale", "BodyHeightScale", "BodyWidthScale", "HeadScale", "BodyProportionScale", "BodyTypeScale" } do
	local v = hum:FindFirstChild(n); if v then v:Destroy() end
	local nv = Instance.new("NumberValue"); nv.Name = n; nv.Value = 1; nv.Parent = hum
end
for _, b in pairs(bones) do b:SetAttribute("OriginalPosition", b.Position) end
hum:SetAttribute("AvatarPartScaleType", "Classic")
-- 2. rebuild HumanoidRootPart as a torso box at the LowerTorso bone
local old = model:FindFirstChild("HumanoidRootPart"); if old then old:Destroy() end
local lt = bones.LowerTorso.WorldPosition
-- Same rule as groundfit.luau, and it has to stay the same rule: HipHeight was
-- measured against a box of THIS size, so a torso box built from spine spacing
-- (2 * (UpperTorso.Y - LowerTorso.Y)) here would float or sink the rig by half
-- the difference. Body height, not bone gap -- see groundfit.luau's note.
local height = tonumber("{{HEIGHT}}")
assert(height and height > 0, "wire needs the character's height in studs ({{HEIGHT}})")
local h = 0.15 * height
local hrp = Instance.new("Part"); hrp.Name = "HumanoidRootPart"; hrp.Size = Vector3.new(0.9 * h, h, 0.5 * h)
hrp.CFrame = CFrame.new(lt.X, lt.Y, lt.Z); hrp.Transparency = 1; hrp.CanCollide = true; hrp.Anchored = false
hrp.Parent = model; model.PrimaryPart = hrp
-- 3. weld the mesh to it
mesh.CanCollide = false; mesh.Massless = true; mesh.Anchored = false
local weld = Instance.new("WeldConstraint"); weld.Part0 = hrp; weld.Part1 = mesh; weld.Parent = hrp
-- 4. upright AlignOrientation (PrimaryAxis defaults to X — must be Y)
local att = Instance.new("Attachment"); att.Name = "RootAttachment"; att.Parent = hrp
local ao = Instance.new("AlignOrientation"); ao.Mode = Enum.OrientationAlignmentMode.OneAttachment
ao.Attachment0 = att; ao.AlignType = Enum.AlignType.PrimaryAxisPerpendicular
ao.PrimaryAxisOnly = true; ao.PrimaryAxis = Vector3.yAxis; ao.RigidityEnabled = true; ao.Parent = hrp
-- 5. neck + fall states off
hum.RequiresNeck = false
for _, s in { Enum.HumanoidStateType.FallingDown, Enum.HumanoidStateType.Ragdoll, Enum.HumanoidStateType.Climbing,
	Enum.HumanoidStateType.Swimming, Enum.HumanoidStateType.Seated, Enum.HumanoidStateType.PlatformStanding } do
	hum:SetStateEnabled(s, false)
end
-- 6. AutomaticScalingEnabled = false, THEN pin HipHeight from the ground-fit attribute
hum.AutomaticScalingEnabled = false
local hip = model:GetAttribute("{{HIP_ATTR}}")
assert(typeof(hip) == "number", "run groundfit before wire")
hum.HipHeight = hip
-- 7. release
hum:ChangeState(Enum.HumanoidStateType.GettingUp)
model:SetAttribute("SkinnedRig", true)
-- Self-checks read back off the live instances, not off the values this script
-- passed in: eval_cmd's E23 row ("recipe applied") gates on expected_hip,
-- primaryAxisCorrect, automaticScalingDisabled and fallStatesDisabled, and a
-- report that merely echoed the inputs would pass while the engine had clamped
-- HipHeight or refused a property.
print("RUNNER_RESULT " .. HttpService:JSONEncode({ hip = hip, expected_hip = hum.HipHeight,
	primaryAxisCorrect = ao.PrimaryAxis == Vector3.yAxis,
	automaticScalingDisabled = not hum.AutomaticScalingEnabled,
	fallStatesDisabled = not hum:GetStateEnabled(Enum.HumanoidStateType.FallingDown)
		and not hum:GetStateEnabled(Enum.HumanoidStateType.Ragdoll),
	rigTypeR15 = hum.RigType == Enum.HumanoidRigType.R15,
	noAnimationController = model:FindFirstChildWhichIsA("AnimationController", true) == nil,
	hrpSize = { hrp.Size.X, hrp.Size.Y, hrp.Size.Z },
	scale = model:GetScale(), meshId = mesh.MeshId, textureId = mesh.TextureID }))
