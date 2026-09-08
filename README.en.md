# mmd-mcp

[日本語](README.md) | English

A Windows stdio MCP server for creating scenes in MikuMikuDance: character poses, motion, cameras, lighting, physics, timeline editing, MME assignments, and native image/AVI export. It does not require MMDPlugin or replace MMD, MME, or MMAccel DLLs. Operations use native controls and a narrowly scoped bone-selection bridge, without mouse coordinates.

## Supported environment

MMD 9.32 x64, Windows, and Python 3.10 x64. The verified Japanese distribution's built-in **English Mode** is supported alongside Japanese mode. Windows common dialogs follow the OS language independently; live validation currently uses Japanese Windows. English Windows dialog labels are accepted, but that OS configuration has not been tested end to end.

Bone memory inspection and selection require this exact executable SHA-256:

```text
07516fd3bf1e6b1339836b6773a156f61bdd6f848eeb621fdda012375df313a1
```

Other executables, including modified language editions, are not verified. The native bridge temporarily loads a small DLL on MMD's UI thread and invokes MMD's own selection routine, then removes its hook. This relies on private internals, not a supported MMD API; unknown builds are rejected.

## Installation

For a source checkout, install 64-bit Python and Visual Studio 2022 / Build Tools with the Desktop development with C++ workload:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
cmd /c scripts\build_native.cmd
```

`requirements-lock.txt` records the validated dependencies. The current distribution is source-only. Build the DLL locally using the steps above; it stays inside the mmd-mcp package and does not need to be copied into the MMD folder.

Publishing a prebuilt wheel is on hold pending the [Microsoft runtime redistribution review](THIRD_PARTY_NOTICES.md). For a wheel you have built yourself, installation does not require the C++ build tools:

```powershell
.\.venv\Scripts\python.exe -m pip install .\dist\mmd_mcp-0.3.0-py3-none-win_amd64.whl
```

Register the server in your MCP client, replacing the installation path:

```json
{
  "mcpServers": {
    "mmd": {
      "command": "C:/Tools/mmd-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "mmd_mcp.server"]
    }
  }
}
```

Start MMD yourself before use. The server does not start MMD or listen on a network port. When multiple MMD instances are running, obtain their handles with `mmd_list_windows` and pass the intended `hwnd` to each call. Reconnect the MCP client after updating the server.

## Language and names

MMD's menu language and a model's original names are separate. Changing English Mode can also change the displayed model, bone, morph, and timeline labels.

- Read model names from `mmd_list_models` and UI labels from `mmd_get_ui_state` / `mmd_get_timeline_context`.
- `mmd_list_bones` returns the original runtime `name` and the current `display_name`. `mmd_select_bone` accepts either when unambiguous, or `bone_index`.
- Bone batches and semantic pose authoring use original bone names, regardless of UI language. For example, the bundled Miku's `arm_L` display corresponds to the original `左腕`.
- Morph names, IK names, parent-bone choices, and timeline track names must match their current UI lists. Do not assume every model supplies the same English translations.
- VMD names remain the original names. Switching the UI language does not translate motion files.
- Do not switch languages, selection, frame, or fields while a call is running. Unknown dialog translations remain open for inspection.

## Tools and workflow

Version 0.3.0 exposes 50 tools. Use batch writes even for one item.

| Task | Tools |
| --- | --- |
| Find and inspect MMD | `mmd_list_windows`, `mmd_capture_window`, `mmd_get_ui_state`, `mmd_get_dialogs` |
| Select models and bones | `mmd_list_models`, `mmd_select_model`, `mmd_list_bones`, `mmd_select_bone`, `mmd_get_selected_bone_transform` |
| Load/save scenes and assets | `mmd_load_file`, `mmd_save_project` |
| Author poses | `mmd_get_model_profile`, `mmd_compile_pose`, `mmd_batch_bone_keys` |
| Camera, light, shadow, gravity | `mmd_get_camera`, `mmd_get_light`, `mmd_get_gravity`, `mmd_batch_camera_keys` |
| Model visibility, IK, outside parents | `mmd_batch_model_flags` |
| Accessories | `mmd_list_accessories`, `mmd_select_accessory`, `mmd_get_accessory`, `mmd_batch_accessories`, `mmd_delete_accessories` |
| Scene rendering | `mmd_get_scene_settings`, `mmd_set_scene_settings`, `mmd_set_render_style`, `mmd_output_size`, `mmd_model_order` |
| Frame, playback, selection | `mmd_set_frame`, `mmd_get_playback`, `mmd_set_playback`, `mmd_get_timeline_context`, `mmd_select_key_range` |
| Native editing and transformations | `mmd_edit_actions`, `mmd_transform_timeline` |
| Native file/video export | `mmd_export_file`, `mmd_export_video`, `mmd_get_video_export_status` |
| Inspect/edit VMD files | `mmd_inspect_vmd`, `mmd_edit_vmd` |
| Motion documents and previews | `mmd_read_motion_document`, `mmd_edit_motion_document`, `mmd_write_motion_document`, `mmd_preview_motion` |
| MME assignments | `mmd_read_effect_assignments`, `mmd_write_effect_assignments`, `mmd_transfer_effect_assignments` |
| Explicit scene/model removal | `mmd_delete_models`, `mmd_new_project` |

Example using the bundled Miku in English Mode (add `hwnd` when needed):

```text
mmd_select_model       {"name":"Miku Hatsune"}
mmd_select_bone        {"name":"arm_L"}
mmd_batch_bone_keys    {"items":[{"frame":10,"bones":[{"name":"左腕","rotation_degrees":{"z":-20}}],"morphs":[{"category":"eyes","name":"blink","weight":0.5}]}]}
```

Inspect tool schemas for full arguments. The [native editing guide](docs/native-editing.md), [coverage table](docs/coverage.md), [authoring guide](docs/authoring.md), and [MME guide](docs/effects.md) contain detailed procedures in Japanese.

## Behavior and limitations

Calls reject unsuitable states such as playback, minimized windows, and unexpected modal dialogs. Multiple fields are applied sequentially; a failure can leave partial changes. Read the returned status and capture the result. There is no automatic rollback.

Displayed transforms are rounded UI values. Bone indices are transient, names can be duplicated or truncated in MMD's 20-byte CP932 runtime fields, and internal/end bones not exposed by MMD cannot be selected. Model-specific IK and physics remain governed by MMD.

Select model index 0 for camera, lighting, and accessories. Accessory parent indices come from the accessory parent list, not the main model selector. Changing a parent preserves local transforms and may change world position.

Use `overwrite=true` explicitly to replace supported output files. Loading a PMM replaces the scene. VMD imports merge keys and offset their times by the current frame: move to frame 0 for file-absolute timing. Importing a VMD with deleted or shifted keys does not remove old scene keys; delete the intended range first.

Motion documents retain keyframes and per-axis/rotation interpolation. Editing a document is a pure operation; writing creates a new file. Curves belong to the destination key. This is not a complete PMM reader or an arbitrary VMD-to-document converter.

Previewing evaluates frames and requires `allow_frame_evaluation=true`. It restores the original frame on success, but cannot restore unregistered edits. PNG sequences, contact sheets, and MJPG previews are not physics bakes. For native AVI output, poll the returned job until complete. `uncompressed`, `未圧縮`, and `AVI Raw` select the language-appropriate raw codec.

EMM read/write tools edit files; `mmd_transfer_effect_assignments` exports/imports live MME assignments without reloading the PMM. Export again to verify the result. Assets such as MMD, models, MME, and Ray-MMD are not included in this repository.

The optional [MMD authoring skill](skills/mmd-pose-motion/SKILL.md) is written in Japanese. Its pose compiler targets supported model bone conventions; arbitrary translated rigs are not automatically retargeted.

## Validation and publication

Run `python scripts/smoke_mcp.py` from the installed environment to check the MCP connection and tool discovery. Live smoke scripts create and terminate their own MMD process and keep artifacts under `local/`. Use `--english` with `scripts/smoke_scene.py`, `scripts/smoke_release.py`, and `scripts/smoke_editing.py` to exercise English Mode.

Source is distributed at [BeamManP/mmd-mcp](https://github.com/BeamManP/mmd-mcp). No MMD or third-party model distribution rights are implied.

## License

Project-authored code, documentation, scripts, and the authoring skill use [MIT No Attribution (MIT-0)](LICENSE). Commercial use, modification, and redistribution are permitted without requiring attribution, retention of the copyright notice, or disclosure of source code. The software is provided without warranty.

Dependencies and Microsoft runtime portions incorporated into the native DLL retain their own terms. The package containing that DLL declares `MIT-0 AND LicenseRef-Microsoft-Runtime`; the project's own source remains MIT-0. See [third-party notices](THIRD_PARTY_NOTICES.md) for the terms and distribution status.

`mmd_get_model_profile` also provides read-only PMD/PMX skeleton investigation. Optional `bone_name` or `bone_index` returns ancestors, declared axes, inheritance and IK; derived rest-hand geometry is separate from runtime state. See [authoring](docs/authoring.md).

For an MMD instance that should survive Codex shutdown, run `python -m mmd_mcp.launcher "C:/MMD/MikuMikuDance.exe"` using the Python environment where mmd-mcp is installed. The local Windows WMI broker creates a suspended process; the launcher verifies that it belongs to no Windows job before resuming it. There is no ordinary child-process fallback on failure. Match the returned PID with `mmd_list_windows`. This isolates process lifetime; it does not prevent MMD crashes or Windows shutdown.
