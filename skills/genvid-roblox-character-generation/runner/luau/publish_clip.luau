-- EDIT mode. Publish the KeyframeSequence `build_kfs` parked in
-- ServerStorage/Assets/Anims and write the resulting asset id onto the character
-- template, closing the last manual click in the clip chain.
--
-- Witnessed 2026-09-04: AssetService:CreateAssetAsync on a KeyframeSequence
-- built in Studio returns Enum.CreateAssetResult.Success and a real asset id
-- from the bridge's Edit context. The August record that CreateAssetAsync
-- rejects a MeshPart/Model never covered KeyframeSequence.
--
-- Publishing is what makes the clip PLAYABLE at all: an unpublished sequence
-- registered through KeyframeSequenceProvider loads with the right Length and
-- never advances, so the treadmill and zoo steps depend on this step running.
local HttpService = game:GetService("HttpService")
local ServerStorage = game:GetService("ServerStorage")
local AssetService = game:GetService("AssetService")

local kfs = ServerStorage.Assets.Anims["{{CLIP_NAME}}"]
assert(kfs:IsA("KeyframeSequence"), "{{CLIP_NAME}} is not a KeyframeSequence; run build_kfs first")

local result, assetId = AssetService:CreateAssetAsync(kfs, Enum.AssetType.Animation, {
	Name = "{{CLIP_NAME}}",
	Description = "{{DESCRIPTION}}",
})
assert(result == Enum.CreateAssetResult.Success,
	"CreateAssetAsync returned " .. tostring(result) .. " for {{CLIP_NAME}}")

local template = ({{PARK_FOLDER}})["{{TEMPLATE}}"]
local attribute = "{{CLIP}}AnimId"
template:SetAttribute(attribute, "rbxassetid://" .. tostring(assetId))

print("RUNNER_RESULT " .. HttpService:JSONEncode({ assetId = assetId, name = "{{CLIP_NAME}}",
	clip = "{{CLIP}}", attribute = attribute, animId = template:GetAttribute(attribute),
	result = tostring(result) }))
