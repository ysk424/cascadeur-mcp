# Cascadeur MCP

Control a running [Cascadeur](https://cascadeur.com/) instance from an MCP client
(e.g. Claude) via the Model Context Protocol.

It exposes the Cascadeur Python API (`csc`) as MCP tools: run arbitrary code, inspect
the scene, and import/export FBX. This makes the standalone *cascadeur_bridge* addon
unnecessary — the model can drive an FBX round-trip and then delete the temp files
itself.

## How it works

```
Claude (MCP client)
   │  execute_cascadeur_code / get_scene_info / import_fbx / export_fbx
   ▼
cascadeur-mcp server (this repo, FastMCP)
   │  1. binds localhost TCP server, writes port file
   │  2. launches: cascadeur.exe --run-script commands.externals.csc_mcp_exec
   │  3. accepts the call-back connection, sends request, reads JSON result
   ▼
csc_mcp_exec.run(scene)   ← runs on Cascadeur's MAIN thread
   │  connects back to the server, exec()s the code with `csc`/`scene`/`app`
   ▼
csc API (the live Cascadeur scene)
```

This "per-call `--run-script`" design mirrors the proven `cascadeur_bridge` addon, so
all scene access happens on Cascadeur's main thread and the UI never freezes between
calls. The cost is a small launch latency per call. See *Roadmap* for the persistent
optimisation.

## Install

### 1. Cascadeur side (one time, needs admin)

Copy the command into Cascadeur's scripts folder, then **restart Cascadeur**:

```bash
python install_cascadeur_side.py
# or specify a custom path:
python install_cascadeur_side.py --csc "C:\Program Files\Cascadeur\cascadeur.exe"
```

This installs `csc_mcp_exec.py` to
`…\Cascadeur\resources\scripts\python\commands\externals\`.

### 2. MCP server

```bash
cd cascadeur-mcp
uv venv && uv pip install -e .      # or: pip install -e .
```

### 3. Register with Claude

Claude Code:

```bash
claude mcp add cascadeur -- cascadeur-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cascadeur": {
      "command": "cascadeur-mcp"
    }
  }
}
```

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CASCADEUR_EXE_PATH` | `C:\Program Files\Cascadeur\cascadeur.exe` | Cascadeur executable |
| `CASCADEUR_MCP_PORT` | `53151` | localhost port for the bridge |
| `CASCADEUR_MCP_TIMEOUT` | `60` | seconds to wait for Cascadeur to connect |

## Tools

- **`execute_cascadeur_code(code)`** — run Python in Cascadeur. `csc`, `scene`, `app`
  in scope. Assign to `result` to return a (JSON-serialisable) value; stdout is
  captured. Mutations go through `scene.modify_with_session(name, mod_func)`.
- **`get_scene_info()`** — scene name + object names.
- **`capture_viewport(width=960, height=540, samples=1)`** — render the current
  viewport with `RenderToFile.take_image` and return the image, so the model can
  visually verify the scene.
- **`export_fbx(file_path, method="export_all_objects")`** — export to FBX.
- **`import_fbx(file_path, method="import_model")`** — import an FBX.

`FbxSceneLoader` method names (verified on Cascadeur 2026): `export_all_objects`,
`export_joints`, `export_joints_selected`, `export_model`, `export_scene_selected`,
`add_model`, `import_animation`, `import_model`, `import_scene`.

## Requirements

- Cascadeur must be **running with a GUI** (the command executes on its main thread).
- Windows (paths assume a Windows install; adjust `CASCADEUR_EXE_PATH` elsewhere).

## Roadmap

- **AutoPhysics / AutoPosing tools.** These are Cascadeur's signature AI features, but
  there is no clean "apply" entry point in the public tool API: `AutoPhysicsTool`'s
  editor only exposes `turn_off`/`turn_off_all_fulcrum_points`, and `AutoPosingTool`
  needs a `csc.domain.Session` plus an already-active posing setup. The real apply
  logic lives in rig-structure-dependent ML code (`ml/editable_animation.py`, etc.).
  Wrapping it reliably is an R&D task rather than a thin wrapper — deferred until it
  can be made to work robustly.
- **Persistent listener** to remove the per-call launch latency. Needs a safe way to
  marshal `csc` calls onto Cascadeur's main thread from a background socket thread
  (Cascadeur has no `bpy.app.timers` equivalent; `csc.update` is the data-graph model,
  not a timer). Candidate: a `csc` event/tool tick hook — to be investigated.
- Convenience tools for animation transfer that send only FK channels + frame numbers
  instead of full FBX.
