local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
local mesh = model:FindFirstChildWhichIsA("MeshPart", true)
print("RUNNER_RESULT " .. HttpService:JSONEncode({ mesh_id = mesh.MeshId, texture_id = mesh.TextureID,
	asset_id = mesh.MeshId }))
