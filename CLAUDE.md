# CLAUDE.md — cascadeur-mcp

Context for continuing this project. Read `docs/cascadeur-api-notes.md` for the
hard-won `csc` API facts before changing Cascadeur-side behaviour.

## What this is

An MCP server that drives a **running** Cascadeur instance through its `csc` Python
API. Modeled on `blender-mcp` (cloned at `../blender-mcp` for reference) but adapted to
Cascadeur's plugin model. Goal: let an MCP client (Claude) inspect the scene, run code,
capture the viewport, and move FBX in/out — making the separate `cascadeur_bridge`
Blender addon (`../cascadeur_bridge`) unnecessary.

## Architecture (and why)

Per-call `--run-script` bridge, **not** a persistent socket server:

1. `server.py` binds a localhost TCP server, writes the port to `<tmp>/cascadeur_mcp.json`.
2. Launches `cascadeur.exe --run-script commands.externals.csc_mcp_exec`. The running
   Cascadeur dispatches it on its **main thread**.
3. `csc_mcp_exec.run(scene)` connects back, receives `{code}`, `exec()`s it with
   `csc`/`scene`/`app` in scope, returns `{status, result, stdout}` as JSON.

Why per-call instead of a persistent listener: Cascadeur has **no `bpy.app.timers`
equivalent** to marshal calls onto the main thread (`csc.update` is the data-graph
model, not a timer). A persistent socket thread can't safely touch `csc`, and a
blocking main-thread loop would freeze the UI between calls. Per-call `--run-script`
runs on the main thread, keeps the UI responsive, and reuses the exact pattern the
proven `cascadeur_bridge` addon uses. The cost is per-call launch latency. Revisit if a
main-thread tick/event hook is found (see roadmap in README).

## Layout

- `src/cascadeur_mcp/server.py` — FastMCP server + tools. All tools are built on
  `_execute(code)` → `_call_cascadeur({"code": ...})`.
- `cascadeur_side/externals/csc_mcp_exec.py` — the Cascadeur command. Generic: it just
  execs code, so **new tools usually need only a code snippet in `server.py`**, no
  changes here.
- `install_cascadeur_side.py` — copies the command into the Cascadeur scripts folder.

## How to test (no MCP client needed)

Cascadeur must be running with a GUI. Drive the server internals directly:

```bash
cd /c/Users/azoo/git/cascadeur-mcp
CASCADEUR_MCP_TIMEOUT=40 .venv/Scripts/python.exe -c "
from cascadeur_mcp import server
import json
print(server.execute_cascadeur_code('result = 1+1'))
"
```

This launches `--run-script` and does a real round-trip. Use this same trick to probe
the live `csc` API (introspect `dir()`, method `__doc__` pybind signatures, etc.) —
it's how the API notes were gathered.

## Gotchas (cost real time to discover)

- **`print()` inside Cascadeur is swallowed** in the GUI Python console. To see output,
  return it via `result`/`stdout`, or write to a file and read it.
- **`capture_viewport`'s render is deferred.** `RenderToFile.take_image` queues the
  render onto Cascadeur's main loop, which only runs *after* `run(scene)` returns. So
  the file appears ~1–2 s after the call; the server polls the filesystem for it.
- **Cascadeur-side install needs admin** (Program Files) and a **Cascadeur restart** to
  register a *new* command — though `--run-script` of an already-present command works
  across restarts without re-installing.
- `scene` passed to `run()` is a `csc.domain.Scene` (no `.name()`); for the named scene
  use `app.get_scene_manager().current_scene()` / `app.current_scene()` (a
  `csc.view.Scene`).
- Scene **mutations** must go through `scene.modify_with_session(name, mod_func)` where
  `mod_func(model, update, sc, session)`.

## Next steps / open work

- AutoPhysics / AutoPosing tools: no clean "apply" in the public tool API
  (`AutoPhysicsTool` editor only has `turn_off*`; `AutoPosingTool` needs a `Session` +
  active setup). Real logic is in `ml/editable_animation.py` etc. Start there. R&D.
- Persistent listener to cut launch latency (needs a main-thread tick hook).
- FK-channel + frame transfer to avoid full FBX for animation-only round-trips.
