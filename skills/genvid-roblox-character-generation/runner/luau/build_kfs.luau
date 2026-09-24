-- EDIT mode. VERIFY the KeyframeSequence `clips build` wrote and Rojo synced
-- into ServerStorage/Assets/Anims/<CLIP_NAME>; build nothing, fetch nothing.
--
-- This step used to build the sequence here from poses fetched off a local
-- server. Since Studio 0.739 the MCP's execute_luau runs sandboxed without the
-- Network capability, so that fetch fails (witnessed 2026-09-23). The sequence
-- is now built on the host by `clips build` (the .rbxmx the title's Rojo
-- project maps into this folder), and this step only reads it back so
-- `studio ingest build_kfs` can compare it with what `clips build` recorded.
--
-- Read-only, and the result line is formatted by hand: the step uses no
-- service beyond ServerStorage, so it asks the sandbox for nothing.
--
-- The sequence cannot be PLAYED from here: an unpublished KeyframeSequence
-- registered through KeyframeSequenceProvider loads with the right Length and
-- never advances. `publish_clip` is the next step.
local ServerStorage = game:GetService("ServerStorage")

local function child(parent, name)
	return parent and parent:FindFirstChild(name) or nil
end

local kfs = child(child(child(ServerStorage, "Assets"), "Anims"), "{{CLIP_NAME}}")
local exists = kfs ~= nil
local isKfs = exists and kfs:IsA("KeyframeSequence")

local keyframes, lastTime, loop, priority, rootPose, rootNode = 0, 0, false, "", "", false
if isKfs then
	local frames = kfs:GetKeyframes()
	keyframes = #frames
	for _, fr in frames do
		if fr.Time > lastTime then lastTime = fr.Time end
	end
	loop = kfs.Loop
	priority = kfs.Priority.Name
	-- The pose tree's root, from the first keyframe: HumanoidRootPart, with or
	-- without a HumanoidRootNode pose under it (SKILL.md, clip transfer law 3).
	local root = frames[1] and frames[1]:FindFirstChildOfClass("Pose")
	if root then
		rootPose = root.Name
		rootNode = root:FindFirstChild("HumanoidRootNode") ~= nil
	end
end

-- The template the clip will play on: whether it carries the root-node bone,
-- and the model scale the Animator multiplies a pose translation by.
-- pcall: indexing a missing folder raises, and this step reports rather than errors.
local okFolder, folder = pcall(function() return {{PARK_FOLDER}} end)
local template = okFolder and folder and folder:FindFirstChild("{{TEMPLATE}}") or nil
local templateFound = template ~= nil and template:IsA("Model")
local templateHasNode = templateFound and template:FindFirstChild("HumanoidRootNode", true) ~= nil
local templateScale = templateFound and template:GetScale() or 0

-- Returned as well as printed: execute_luau hands back the chunk's return
-- value, not its console output.
local runnerResult = string.format(
	'RUNNER_RESULT {"name":"%s","found":%s,"isKfs":%s,"keyframes":%d,"lastTime":%.6f,"loop":%s,'
		.. '"priority":"%s","rootPose":"%s","rootNode":%s,"templateFound":%s,"templateHasNode":%s,'
		.. '"templateScale":%.6f,"parked":"%s"}',
	"{{CLIP_NAME}}", tostring(exists), tostring(isKfs), keyframes, lastTime, tostring(loop), priority, rootPose,
	tostring(rootNode), tostring(templateFound), tostring(templateHasNode), templateScale,
	isKfs and kfs:GetFullName() or "")
print(runnerResult)
return runnerResult
