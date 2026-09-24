local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
local mesh = model:FindFirstChildWhichIsA("MeshPart", true)
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ mesh_id = mesh.MeshId, texture_id = mesh.TextureID,
	asset_id = mesh.MeshId })
print(runnerResult)
return runnerResult
