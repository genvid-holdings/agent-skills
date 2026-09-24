local HttpService = game:GetService("HttpService")
local model = {{MODEL_PATH}}
-- The park folder is a parameter ({{PARK_FOLDER}}); this step is the one that has
-- to CREATE it when it is missing, so it walks {{PARK_PATH}} -- the same path as
-- a segment list, derived from PARK_FOLDER by studio.park_path_segments -- and
-- makes a Folder for every segment that is not there yet.
local path = {{PARK_PATH}}
local folder = game:GetService(path[1])
for i = 2, #path do
	local nxt = folder:FindFirstChild(path[i])
	if not nxt then nxt = Instance.new("Folder"); nxt.Name = path[i]; nxt.Parent = folder end
	folder = nxt
end
local prev = folder:FindFirstChild("{{TEMPLATE}}")
if prev then prev.Name = "{{TEMPLATE}}_prev_" .. os.time() end -- never delete; the orchestrator asks before removing
model.Name = "{{TEMPLATE}}"; model.Parent = folder
-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = "RUNNER_RESULT " .. HttpService:JSONEncode({ parked = model:GetFullName() })
print(runnerResult)
return runnerResult
