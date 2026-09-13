-- EditableMesh -> OBJ text dump: the orchestrator runs this in
-- Studio, in the same live session, against a Cube-generated prop already parked by
-- park_prop.luau, to capture full geometry the way groundfit.luau/probe_feet.luau
-- already read vertex positions off an EditableMesh (genvid-roblox-studio-ops:
-- in-Studio MCP is the one access path that reveals full geometry -- there is no
-- after-the-fact query for it once the session ends, so this has to run now).
--
-- Large payloads stream via chunked console lines rather than the localhost-JSON
-- pattern the studio-ops skill recommends for cross-session streaming: the receiving
-- end here is the orchestrator's own console capture of THIS call, not a second live
-- Studio session, so a chunk count in one final RUNNER_RESULT line is enough for it
-- to reassemble the OBJ text in order.
local HttpService = game:GetService("HttpService")
local AssetService = game:GetService("AssetService")
local model = {{MODEL_PATH}}
local mesh = model:IsA("MeshPart") and model or model:FindFirstChildWhichIsA("MeshPart", true)
assert(mesh, "mesh_dump: no MeshPart under " .. model:GetFullName())
-- A file-imported mesh carries a real rbxassetid in MeshId (groundfit.luau's own,
-- witnessed, CreateEditableMeshAsync(Content.fromAssetId(...)) pattern), but Cube's
-- GenerateModelAsync returns "editable content with empty asset refs" (studio-ops
-- skill) -- MeshId is "" on that path, and Content.fromAssetId(nil) throws. Fall
-- back to the MeshPart's own MeshContent, the Content object Cube already attached
-- to it, in that case. (assumption: CreateEditableMeshAsync accepting that
-- Object-source Content the same way it accepts an id-source one was not witnessed
-- against a live Cube result -- the fromAssetId branch above is the
-- witnessed one, via groundfit.luau/probe_feet.luau.)
local idStr = mesh.MeshId ~= "" and mesh.MeshId:match("%d+") or nil
local content = idStr and Content.fromAssetId(tonumber(idStr)) or mesh.MeshContent
local em = AssetService:CreateEditableMeshAsync(content)

local lines = {}
local vidIndex = {}
local vertexCount = 0
for _, vid in em:GetVertices() do
	vertexCount = vertexCount + 1
	vidIndex[vid] = vertexCount
	local p = em:GetPosition(vid)
	table.insert(lines, string.format("v %.6f %.6f %.6f", p.X, p.Y, p.Z))
end

local faceCount = 0
for _, fid in em:GetFaces() do
	local verts = em:GetFaceVertices(fid)
	local idx = {}
	for _, v in verts do table.insert(idx, vidIndex[v]) end
	if #idx == 3 then
		table.insert(lines, string.format("f %d %d %d", idx[1], idx[2], idx[3]))
		faceCount = faceCount + 1
	elseif #idx == 4 then
		table.insert(lines, string.format("f %d %d %d %d", idx[1], idx[2], idx[3], idx[4]))
		faceCount = faceCount + 1
	end
	-- any other vertex count (fan/ngon) is skipped rather than mis-triangulated blind
end

-- 700KB was accepted whole in a single execute_luau call (studio-ops skill), but the
-- OBJ text is going the other direction (console OUT, not code IN) -- chunked here so
-- the orchestrator's console capture never has to trust one unbounded print.
local CHUNK = 1800
local obj = table.concat(lines, "\n")
local chunkCount = 0
for i = 1, #obj, CHUNK do
	chunkCount = chunkCount + 1
	print("RUNNER_CHUNK " .. chunkCount .. " " .. string.sub(obj, i, i + CHUNK - 1))
end
print("RUNNER_RESULT " .. HttpService:JSONEncode({ chunks = chunkCount, vertices = vertexCount, faces = faceCount }))
