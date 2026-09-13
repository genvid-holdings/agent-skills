-- Sky: six cubemap faces + Realistic lighting style. {{FT}} {{BK}}
-- {{LF}} {{RT}} {{UP}} {{DN}} are rbxassetid:// ids from mcp__Roblox_Studio__upload_image
-- (one per face).
local Lighting = game:GetService("Lighting")
local HttpService = game:GetService("HttpService")

local sky = Lighting:FindFirstChildOfClass("Sky")
if not sky then
	sky = Instance.new("Sky")
	sky.Parent = Lighting
end
sky.SkyboxFt = "{{FT}}"
sky.SkyboxBk = "{{BK}}"
sky.SkyboxLf = "{{LF}}"
sky.SkyboxRt = "{{RT}}"
sky.SkyboxUp = "{{UP}}"
sky.SkyboxDn = "{{DN}}"
sky.SunAngularSize = 14
sky.StarCount = 0

-- Classic fog only: never add or remove an
-- Atmosphere instance. Standing rule: nothing is deleted without asking, so an
-- existing one is warned about, not touched.
if Lighting:FindFirstChildOfClass("Atmosphere") then
	warn("sky.luau: an Atmosphere instance exists under Lighting (classic fog only) -- leaving it in place, not deleting it")
end

-- Some Studio builds may not carry Enum.LightingStyle.Realistic yet; pcall so
-- the Sky above still lands even where this half fails, and record which.
local style = "unavailable"
local ok = pcall(function()
	Lighting.LightingStyle = Enum.LightingStyle.Realistic
	Lighting.PrioritizeLightingQuality = true
end)
if ok then
	style = "realistic"
end

print("RUNNER_RESULT " .. HttpService:JSONEncode({ style = style }))
