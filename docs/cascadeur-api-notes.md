# Cascadeur `csc` API notes

Facts gathered by live introspection against **Cascadeur 2026** (the running instance,
via `execute_cascadeur_code`). Cascadeur ships no `.pyi` stubs; the only on-disk
reference is `…/resources/scripts/python_api_doc/source/csc.rst` (just `automodule`
directives) and `…/resources/scripts/python/samples/api_document.py` (partial, often
out of date — e.g. it lists `AutoPhysicTool` but only the `turn_off` methods). **Trust
live introspection over the sample doc.** Reuse the test recipe in `CLAUDE.md` to probe.

## Plugin / command model

- A module under `resources/scripts/python/commands/**` becomes a command if it defines
  `command_name()` and `run(scene)` (optionally `command_description()`).
- `cascadeur.exe --run-script <dotted.module.path>` runs that command's `run()` on the
  main thread of the already-running instance (single-instance dispatch).
- Event hooks live under `resources/scripts/python/events/<event>/*.py` with `run(scene)`
  (e.g. `scene_opened`, `scene_activated`). Candidate place to look for a main-thread
  tick if pursuing a persistent listener.

## Core handles

```python
import csc
A   = csc.app.get_application()
sm  = A.get_scene_manager()
vs  = A.current_scene()          # csc.view.Scene  (has .name() via sm.current_scene())
ds  = vs.domain_scene()          # csc.domain.Scene == the `scene` arg to run()
tm  = A.get_tools_manager()      # .get_tool(name) -> tool ; .tools() -> list
```

`csc` submodules: `app, view (+camera_utils), tools (+selection/mirror/attractor),
parts, external(+fbx), fbx, rig, layers, model, domain, math, physics, update`.

## Reading vs mutating the scene

- Read via viewers: `ds.model_viewer()` → `get_objects()`, `get_object_name(id)`, …;
  `model.behaviour_editor()`, `behaviour_viewer()`.
- Mutate via session: `ds.modify_with_session(name, mod_func)` where
  `mod_func(model, update, sc, session)`. Variants seen: `modify`, `modify_with_session`,
  `modify_update`, `modify_update_with_session`. Example: `commands/add/add_locator.py`.

## Tools manager — registered tool names (Cascadeur 2026)

`tm.tools()` returns objects; `tm.get_tool("Name")` fetches by name. Registered names
include:

```
DefaultFbxSynchronizationTool, Gui, Hotkeys, GlbSceneLoader, DockingSystem,
ControlPicker, Timeline, ManipulatorsTool, AnimationUnbakingTool,
DomainStateController, Sf3Loader, CameraOrientationTool, GhostTool, ViewportsTool,
OutlinerTool, TopologyController, ViewportModesManager, ViewportSelector,
ShowFulcrumPointsTool, ObjectWatchingTool, Audio, MocapTool, Textures, EventSystem,
LiveLinkTool, CopierTool, LayersCopier, BallisticTrajectoryTool, AnimationDataCopier,
SceneAutosaver, AnimationWithLayersCopier, Retargeting, LayerHierarchyCopier,
FbxSceneLoader, Scene, LogDeleter, ViewGridTool, UsdSceneLoader, LinkedScenes,
AttractorTool, TrajectoryTool, PythonConsole, MirrorTool, AutoPhysicsTool,
NodeEditorTool, FixFootTool, RiggingToolWindowTool, AutoPosingTool, CompositionTool,
ViewActionCreatorTool, RiggingModeTool, SelectionGroupsTool, FixCollisionsTool,
InbetweeningTool
```

Note: `RenderToFile` and a `DataSourceManager` appear in `tools()` but have no `name()`.
Get `RenderToFile` by `get_tool("RenderToFile")` or by `isinstance(t, csc.tools.RenderToFile)`.

Many tools follow `get_tool("X").editor(view_scene)` → an editor object, e.g.
`get_tool("MirrorTool").editor(vs).core()`, `get_tool("InbetweeningTool").editor(vs)`.

## FBX (`FbxSceneLoader`) — verified working

```python
loader = tm.get_tool("FbxSceneLoader").get_fbx_loader(scene)   # scene = domain scene
s = csc.fbx.FbxSettings(); s.mode = csc.fbx.FbxSettingsMode.Binary
s.up_axis = csc.fbx.FbxSettingsAxis.Y   # or .Z ; also s.apply_euler_filter, s.bake_animation
loader.set_settings(s)
loader.export_all_objects(path)   # see method list below
```

Export methods: `export_all_objects, export_joints, export_joints_selected,
export_joints_selected_frames, export_joints_selected_objects, export_model,
export_scene_selected, export_scene_selected_frames, export_scene_selected_objects`.
Import methods: `add_model, add_model_to_selected, import_animation,
import_animation_to_selected_frames, import_animation_to_selected_objects,
import_model, import_scene`.

## Rendering / screenshot — verified working

```python
rtf = tm.get_tool("RenderToFile")                 # or isinstance scan of tm.tools()
rp = csc.tools.RenderParameters()                 # attrs: width, height, samples
rp.width, rp.height, rp.samples = 960, 540, 1
rtf.take_image(view_scene, rp, file_path)         # view_scene = A.current_scene()
```

`RenderToFile`: `take_image(scene_view, RenderParameters, file_name)`,
`play_to_images_sequence(scene_view, RenderParameters, folder_name)`,
`play_to_video_file(...)`. **`take_image` is deferred** — the PNG is written once
Cascadeur's main loop runs after `run()` returns. Poll for the file.

## AutoPhysics / AutoPosing — NOT trivially exposed (why deferred)

- `tm.get_tool("AutoPhysicsTool").editor(vs)` → `csc.tools.AutoPhysicTool` with only
  `turn_off()` and `turn_off_all_fulcrum_points()`. **No apply/turn-on.** There is an
  `'AutoPhysics'` *behaviour* (see `commands/restore_values.py`:
  `behaviour_viewer.get_behaviour_by_name(cm_obj_id, 'AutoPhysics')`), so application is
  behaviour/ML-driven, not a one-call tool method.
- `tm.get_tool("AutoPosingTool").editor(vs)` (an `ActivateDeactivate`) →
  `activate(session, dict[ObjectId,ObjectId]) -> bool`, `add(session)`,
  `update(session)`, `deactivate(session, set[ObjectId])`. All need a
  `csc.domain.Session` (from `modify_with_session`) and a configured posing setup.
- Real apply logic lives in `resources/scripts/python/ml/editable_animation.py`,
  `rig_gen*/autoposing*`, `prototypes/**`. To build these tools, study those — it's R&D,
  not a thin wrapper.

## Useful built-in scripts to mine

`samples/api_document.py` (partial API doc), `ml/editable_animation.py` (physics/posing,
inbetweening, auto-interpolation usage), `commands/add/*.py` (modify_with_session
patterns), `commands/externals/*` (the original Blender bridge), `commands/quick_export`
and `commands/custom_export` (FbxSceneLoader usage).
