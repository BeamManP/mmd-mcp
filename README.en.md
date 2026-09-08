# mmd-mcp

[日本語](README.md) | English

A Windows stdio MCP server for creating scenes in MikuMikuDance: character poses, motion, cameras, lighting, physics, timeline editing, MME assignments, and native image/AVI export. It does not replace MMD, MME, or MMAccel DLLs. Operations use native controls and a narrowly scoped bone-selection bridge, without mouse coordinates.

![MMD timeline and controls alongside Hatsune Miku posing on a mint-colored stage](assets/mmd-screenshot.jpg)

A scene created with mmd-mcp, shown in MMD. Model: Tda Hatsune Miku V4X / Tda. Hatsune Miku © Crypton Future Media, INC. [Image credits](assets/CREDITS.md).

## Supported environment

MMD 9.32 x64, Windows, and Python 3.10 x64. The verified Japanese distribution's built-in **English Mode** is supported alongside Japanese mode. Windows common dialogs follow the OS language independently; live validation currently uses Japanese Windows. English Windows dialog labels are accepted, but that OS configuration has not been tested end to end.

## Bone-selection DLL

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

For an MMD instance that should survive shutdown of its MCP client (such as Codex or Claude Code), run `python -m mmd_mcp.launcher "C:/MMD/MikuMikuDance.exe"` using the Python environment where mmd-mcp is installed. The local Windows WMI broker creates a suspended process; the launcher verifies that it belongs to no Windows job before resuming it. There is no ordinary child-process fallback on failure. Match the returned PID with `mmd_list_windows`. This isolates process lifetime; it does not prevent MMD crashes or Windows shutdown.

Start MMD yourself before use. The server does not start MMD or listen on a network port. When multiple MMD instances are running, obtain their handles with `mmd_list_windows` and pass the intended `hwnd` to each call. Reconnect the MCP client after updating the server.

## Tools and workflow

Version 0.3.0 exposes 50 tools. Use batch writes even for one item.

| Tool | Description |
| --- | --- |
| `mmd_list_windows` | MMD window handles, process IDs, and titles. |
| `mmd_capture_window` | PNG capture of the entire window, including the UI. |
| `mmd_list_models` / `mmd_select_model` | List models and select by name or index; index 0 selects camera, light, and accessories. |
| `mmd_get_ui_state` | Displayed frame, model selection, morph lists and displayed weights, and IK selector. |
| `mmd_list_bones` / `mmd_select_bone` | List bones and select one by name or index. |
| `mmd_get_selected_bone_transform` | Selected bone name/count and displayed position and rotation. |
| `mmd_get_camera` | Read camera target, rotation, distance, field of view, and perspective. |
| `mmd_get_light` | Read light RGB and direction. |
| `mmd_set_frame` | Move to a frame and evaluate the animation. |
| `mmd_load_file` | Load PMD/PMX models, PMM projects, VPD poses, VMD motion, X accessories, WAV audio, background images, or AVI backgrounds. |
| `mmd_save_project` | Save a PMM; replacing a file requires `overwrite=true`. |
| `mmd_get_dialogs` | Inspect text and buttons in owned modal dialogs. |
| `mmd_get_model_profile` | Read PMD/PMX rest bones and supported profiles; investigate ancestors, axes, inheritance, and IK by bone name or index. |
| `mmd_compile_pose` | Compile model-specific semantic poses; solve `hand_at` / `palm_facing` targets with forward kinematics and return wrist/palm checks in `fk`. |
| `mmd_read_motion_document` / `mmd_edit_motion_document` | Read editable motion JSON and add, update, or remove keys. |
| `mmd_write_motion_document` | Save a new motion JSON or VMD with interpolation. |
| `mmd_preview_motion` | Sample frames into PNGs, a contact sheet, and a timed AVI preview. |
| `mmd_list_accessories` / `mmd_select_accessory` | List accessories and select an explicit target. |
| `mmd_get_accessory` | Read accessory position, rotation, scale, opacity, visibility, shadow, and parent. |
| `mmd_batch_bone_keys` | Batch bone and morph values and key registration by frame; mix semantic poses, explicit bones, and morphs, including a single item. |
| `mmd_batch_camera_keys` | Batch camera, light, self-shadow, and gravity values and keys by frame. |
| `mmd_read_effect_assignments` / `mmd_write_effect_assignments` | Read and edit EMM assignments by Main, ambient, material, and shadow sections, including per-material visibility. |
| `mmd_batch_model_flags` | Batch model visibility, self-shadow, additive drawing, IK enablement, outside parents, and key registration. |
| `mmd_batch_accessories` | Load accessories and batch values, parents, and key registration by frame; use the same interface for one or many. |
| `mmd_delete_accessories` | Delete explicitly matched accessories in descending index order; accept only the exact expected confirmation dialog. |
| `mmd_get_scene_settings` / `mmd_set_scene_settings` | Read rendering, physics, audio, and MME settings; set explicit states and verify readback. |
| `mmd_set_render_style` | Set model edge width/color and ground-shadow brightness. |
| `mmd_output_size` | Read, change, and verify output dimensions. |
| `mmd_model_order` | Read and reorder model drawing and calculation order. |
| `mmd_get_gravity` | Read gravity and noise settings. |
| `mmd_get_playback` / `mmd_set_playback` | Read playback state; set start/end range, looping, and playback or stop. |
| `mmd_get_timeline_context` / `mmd_select_key_range` | Read timeline tracks/range and select a key range. |
| `mmd_edit_actions` | Copy, paste, or delete bones/keys; insert columns, select, initialize, undo, and perform other supported native edits. |
| `mmd_transform_timeline` | Apply native time scaling, position/rotation or morph correction, blinking, lip timing, and physics-flag transformations. |
| `mmd_export_file` | Export VPD, VMD, or images with MMD. |
| `mmd_export_video` / `mmd_get_video_export_status` | Export AVI with an explicit range, frame rate, and codec; poll completion. |
| `mmd_inspect_vmd` / `mmd_edit_vmd` | Inspect VMD keys and write a new file with timing, deletion, or bone/camera interpolation edits. |
| `mmd_transfer_effect_assignments` | Export live MME assignments to EMM or import EMM without reloading the PMM. |
| `mmd_delete_models` / `mmd_new_project` | Delete explicitly identified models or discard the current scene and create a new project. |

Common behavior: operations that select bones switch BOX or other operation modes back to Select automatically. `operation_mode_switched_from` reports the previous mode.

Example using the bundled Miku in English Mode (add `hwnd` when needed):

```text
mmd_select_model       {"name":"Miku Hatsune"}
mmd_select_bone        {"name":"arm_L"}
mmd_batch_bone_keys    {"items":[{"frame":10,"bones":[{"name":"左腕","rotation_degrees":{"z":-20}}],"morphs":[{"category":"eyes","name":"blink","weight":0.5}]}]}
```

Inspect tool schemas for full arguments. The [native editing guide](docs/native-editing.md), [coverage table](docs/coverage.md), [authoring guide](docs/authoring.md), and [MME guide](docs/effects.md) contain detailed procedures in Japanese.

## Behavior and limitations

- Do not change models, bones, frames, or input fields during a call. Ordinary edits reject playback, minimized windows, and modal dialogs.
- Fields are applied sequentially. A failure can leave partial changes; there is no automatic rollback. Check returned values and a capture.
- Numeric readings are rounded UI values, not a complete scene dump at internal precision.
- Ambiguous names are rejected. Model and bone indices do not persist across reloads; runtime bone names can be truncated to MMD's 20-byte CP932 fields.
- Bone lists include internal/end bones, but bones unavailable in the UI cannot be selected. MMD evaluates IK, physics, and movement restrictions.
- Select index 0 and expand panels before camera/light operations. Bone operations require bone-editing mode. Accessory parent indices come from the accessory parent list; changing parents preserves local transforms and can change world position.
- Window capture records the current display with WGC. Strict render synchronization and viewport-only cropping are not implemented.
- MME supports EMM export, editing, and import for Main, offscreen, material, and visibility settings. There is no complete PMM parser. Export selected keys to VMD for inspection; retain accessories, gravity, outside parents, and other data absent from VMD in PMM.
- VMD imports merge keys and offset timing by the current frame. Move to frame 0 for file-absolute timing. Deleted or shifted keys in an imported VMD do not remove old scene keys; delete the intended range first.
- Undo/redo is limited to operations MMD makes available. It cannot universally reverse camera edits or model deletion.
- Poll AVI export completion in the same MCP server process. Ordinary editing is rejected during export. Custom codec dialogs, a dedicated UI-language switching tool, Kinect, and VSQ lip sync are unsupported. `uncompressed`, `未圧縮`, and `AVI Raw` select the language-appropriate raw codec.
- Live model matching uses bone names and order. UI inspection cannot prove the loaded file's hash; the user must associate the supplied model file with the actual target.
- PMX profile reading stops at the bone section. It does not validate the complete model or physics configuration.

Use absolute file paths and explicit `overwrite=true` where replacement is supported. Loading a PMM replaces the scene. Editing values, registering keys, and saving are separate operations; frame evaluation can replace unregistered edits.

Motion documents retain keys and per-axis/rotation interpolation. Editing a document is a pure operation; writing creates a new file. Curves belong to the destination key. This is not an arbitrary VMD-to-document converter.

Previewing samples up to 180 frames and requires `allow_frame_evaluation=true`. On success it restores the original frame, but cannot restore unregistered edits. PNG sequences, contact sheets, and timed MJPG previews are neither real-time recordings nor physics bakes.

EMM read/write tools edit files. Use `mmd_transfer_effect_assignments` to export/import live assignments and export again to verify them. MMD, models, MME, and Ray-MMD are not included.

The optional Japanese [authoring skill](skills/mmd-pose-motion/SKILL.md) can be installed in the skill location supported by your MCP client (such as Codex or Claude Code). The pose compiler targets supported model conventions; arbitrary rigs are not automatically retargeted.

## For contributors

[Testing and package-building guide](docs/development.md#english-notes)

## Language and names

MMD's menu language and a model's original names are separate. Changing English Mode can also change the displayed model, bone, morph, and timeline labels.

- Read model names from `mmd_list_models` and UI labels from `mmd_get_ui_state` / `mmd_get_timeline_context`.
- `mmd_list_bones` returns the original runtime `name` and the current `display_name`. `mmd_select_bone` accepts either when unambiguous, or `bone_index`.
- Bone batches and semantic pose authoring use original bone names, regardless of UI language. For example, the bundled Miku's `arm_L` display corresponds to the original `左腕`.
- Morph names, IK names, parent-bone choices, and timeline track names must match their current UI lists. Do not assume every model supplies the same English translations.
- VMD names remain the original names. Switching the UI language does not translate motion files.
- Do not switch languages, selection, frame, or fields while a call is running. Unknown dialog translations remain open for inspection.

## License

Project-authored code, documentation, scripts, and the authoring skill use [MIT No Attribution (MIT-0)](LICENSE). Commercial use, modification, and redistribution are permitted without requiring attribution, retention of the copyright notice, or disclosure of source code. The software is provided without warranty.

Dependencies and Microsoft runtime portions incorporated into the native DLL retain their own terms. The package containing that DLL declares `MIT-0 AND LicenseRef-Microsoft-Runtime`; the project's own source remains MIT-0. See [third-party notices](THIRD_PARTY_NOTICES.md) for the terms and distribution status.

`mmd_get_model_profile` also provides read-only PMD/PMX skeleton investigation. Optional `bone_name` or `bone_index` returns ancestors, declared axes, inheritance and IK; derived rest-hand geometry is separate from runtime state. See [authoring](docs/authoring.md).
