"""MMD observation and explicit bone-editing tools over stdio."""

from typing import Any, Annotated, Literal

from pydantic import Field

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from .capture import capture_png
from .windows import list_windows
from .ui_state import get_ui_state, list_models
from .bone_controls import AxisValues, get_selected_bone_transform, set_selected_bone_transform
from .bone_state import list_bones
from .bone_selection import select_bone
from . import scene_controls as scene
from . import file_operations as files
from . import pose_authoring as poses, motion_document as motions, authoring_live as authoring
from . import accessory_controls as accessories
from . import accessory_batch as batch
from . import bone_batch
from . import model_flags
from . import camera_batch
from . import effects
from . import scene_settings
from . import effects_live
from . import edit_actions
from . import render_controls
from . import video_export
from . import vmd_reader
from . import timeline, playback
from . import scene_lifecycle
from . import timeline_transforms
from . import vmd_edit

mcp = FastMCP("mmd-mcp")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
SELECT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


@mcp.tool(annotations=EDIT)
def mmd_set_render_style(style: render_controls.RenderStyle,
                           hwnd: int | None = None) -> dict[str, Any]:
    """Set selected model edge width/color or ground-shadow brightness; reopen native dialogs to verify."""
    return render_controls.set_style(style, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_edit_vmd(source_path: str, output_path: str, edits: list[vmd_edit.VmdEdit]) -> dict[str, Any]:
    """Write a new VMD with timing shifts/scaling, deletion or bone/camera interpolation edits.

    Keeps unrelated native payloads and source file intact. Rejects unmatched edits and
    key collisions before writing. This is file-only: VMD import merges keys, so clear
    the intended live range before importing timing/deletion edits; import at frame 0.
    """
    return vmd_edit.edit(source_path, output_path, edits)


@mcp.tool(annotations=EDIT)
def mmd_transform_timeline(spec: timeline_transforms.TransformSpec,
                             hwnd: int | None = None) -> dict[str, Any]:
    """Apply native time scaling, selected-key corrections, center bias, blink or lip timing.

    Corrections use current selected keys. Time scaling uses explicit range/tracks.
    Morph changes may not support undo. Export VMD afterwards to verify results.
    """
    return timeline_transforms.transform(spec, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_new_project(discard_current: Annotated[bool, Field(strict=True)],
                       hwnd: int | None = None) -> dict[str, Any]:
    """Create a new empty scene, discarding current unsaved scene data. Requires discard_current=true."""
    return scene_lifecycle.new_project(discard_current, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_delete_models(targets: list[dict[str, Any]], hwnd: int | None = None) -> dict[str, Any]:
    """Delete models and all their keys, not undoable. Targets: [{selector_index, expected_name}].

    Validates all names/indices before editing, deletes highest indices first and verifies
    the remaining list. Uses exact model-name confirmations. Attached accessories follow ground.
    """
    return scene_lifecycle.delete_models(targets, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_playback(hwnd: int | None = None) -> dict[str, Any]:
    """Read playback state, loop and range; callable during playback."""
    return playback.get(hwnd)


@mcp.tool(annotations=SELECT)
def mmd_set_playback(playing: Annotated[bool, Field(strict=True)] | None = None,
                       options: playback.PlaybackOptions | None = None,
                       hwnd: int | None = None) -> dict[str, Any]:
    """Start/stop playback idempotently or configure start/end frame and loop while stopped."""
    return playback.set_playback(playing, options, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_timeline_context(hwnd: int | None = None) -> dict[str, Any]:
    """Read range-selection track names, interpolation channels and range text; not a live key dump."""
    return timeline.get_context(hwnd)


@mcp.tool(annotations=SELECT)
def mmd_select_key_range(start_frame: Annotated[int, Field(strict=True, ge=0, le=999999)],
                           end_frame: Annotated[int, Field(strict=True, ge=0, le=999999)],
                           track_name: str, hwnd: int | None = None) -> dict[str, Any]:
    """Select an inclusive timeline range using an exact track name from mmd_get_timeline_context."""
    return timeline.select_range(start_frame, end_frame, track_name, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_inspect_vmd(path: str,
                      track: Literal["bones", "morphs", "camera", "light", "shadow", "model_flags"] | None = None,
                      start_frame: Annotated[int, Field(strict=True, ge=0)] = 0,
                      end_frame: Annotated[int, Field(strict=True, ge=0)] = 999999,
                      offset: Annotated[int, Field(strict=True, ge=0)] = 0,
                      limit: Annotated[int, Field(strict=True, ge=1, le=1000)] = 200) -> dict[str, Any]:
    """Inspect saved native VMD key records with bounded pagination; useful for verifying timeline edits."""
    return vmd_reader.inspect(path, track, start_frame, end_frame, offset, limit)


@mcp.tool(annotations=EDIT)
def mmd_export_video(path: str, options: video_export.VideoOptions,
                       overwrite: Annotated[bool, Field(strict=True)] = False,
                       hwnd: int | None = None) -> dict[str, Any]:
    """Start native AVI export with explicit range, fps, installed codec and optional audio.

    Set output dimensions first with mmd_output_size. Codec uncompressed (or 未圧縮 / AVI Raw) selects raw output in either UI language.
    Returns a job_id; poll mmd_get_video_export_status if rendering. Keep this MCP server
    running and leave MMD idle until completion. Unknown codec names return available names.
    """
    return video_export.export(path, options, overwrite, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_video_export_status(job_id: str) -> dict[str, Any]:
    """Check a native AVI job. Completion requires an unlocked file with nonempty AVI frame metadata."""
    return video_export.status(job_id)


@mcp.tool(annotations=EDIT)
def mmd_output_size(size: render_controls.OutputSize | None = None,
                      hwnd: int | None = None) -> dict[str, Any]:
    """Read output width/height, or set both via MMD's dialog and reopen to verify (16–8192 pixels)."""
    return render_controls.output_size(size, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_model_order(kind: Literal["draw", "compute"],
                      order: list[Annotated[int, Field(strict=True, ge=0)]] | None = None,
                      expected_names: list[str] | None = None,
                      hwnd: int | None = None) -> dict[str, Any]:
    """Read model draw/compute order; optionally reorder using a complete zero-based permutation.

    To change order, supply expected_names exactly as returned by the prior read.
    Rereads the dialog to verify persistence. Model selector indices can change.
    """
    return render_controls.model_order(kind, order, expected_names, hwnd)


@mcp.tool(annotations=SELECT)
def mmd_get_gravity(hwnd: int | None = None) -> dict[str, Any]:
    """Read current gravity by opening and closing the native dialog without registering a key."""
    return render_controls.get_gravity(hwnd)


@mcp.tool(annotations=EDIT)
def mmd_edit_actions(actions: Annotated[list[edit_actions.Action], Field(min_length=1, max_length=64)],
                       hwnd: int | None = None) -> dict[str, Any]:
    """Run ordered named editing commands: selection, clipboard, timeline, reset, undo/redo.

    Operates on the current model/frame/selected bones/selected keys. Commands can
    delete keys or reset unsaved values; no automatic save or rollback. Native undo
    covers only what MMD supports. Stops on unavailable controls or unknown dialogs.
    Select *_keys before exporting a native motion. Paste uses MMD's current clipboard.
    """
    return edit_actions.perform(actions, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_transfer_effect_assignments(operation: Literal["export", "import"], path: str,
                                      overwrite: Annotated[bool, Field(strict=True)] = False,
                                      hwnd: int | None = None) -> dict[str, Any]:
    """Export live MME assignments to EMM, or import EMM into the current scene.

    Opens/closes MME's assignment dialog without reloading PMM. Use export ->
    mmd_write_effect_assignments -> import -> export to verify edited assignments.
    Requires MME installed. Unknown dialogs remain open and are returned for inspection.
    Output must be new unless overwrite=true. Import may replace effect assignments.
    """
    return effects_live.transfer(operation, path, overwrite, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_scene_settings(hwnd: int | None = None) -> dict[str, Any]:
    """Read named display, physics, sound and MME menu settings; null means unavailable."""
    return scene_settings.get_settings(hwnd)


@mcp.tool(annotations=EDIT)
def mmd_set_scene_settings(settings: scene_settings.SceneSettings,
                           hwnd: int | None = None) -> dict[str, Any]:
    """Set explicit scene settings idempotently and verify menu check states.

    Omitted/null values stay unchanged. All requested settings are preflighted before
    editing. Changes are not keyframes or saved to disk. Stops on failure and reports
    applied settings; no automatic rollback. Requires stopped playback.
    """
    return scene_settings.set_settings(settings, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_list_accessories(hwnd: int | None = None) -> dict[str, Any]:
    """List accessories in camera/light/accessory mode (model selector 0); indices are transient."""
    return accessories.list_accessories(hwnd)


@mcp.tool(annotations=SELECT)
def mmd_select_accessory(selector_index: Annotated[int, Field(strict=True, ge=0)] | None = None,
                           name: str | None = None, hwnd: int | None = None) -> dict[str, Any]:
    """Select one accessory by unique filename or current index, without changing values or registering keys."""
    return accessories.select_accessory(selector_index, name, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_batch_accessories(items: list[batch.AccessoryItem], return_to_frame: bool = True,
                          hwnd: int | None = None) -> dict[str, Any]:
    """Load, place and key several accessories in one call (camera/light/accessory mode).

    Each item is either a new X file (path) or an existing selector_index, with keys per
    frame: position, rotation_degrees, scale, opacity, visible, shadow, parent_model_index +
    parent_bone_name (0 = ground, no bone), register_key (default true). One item = the
    single-accessory case. Loads run first, then frames in ascending order, entering each frame once.
    Context is verified once per batch and per frame; per item only selector drift is
    checked. Stops at the first failure and reports what was applied; nothing is undone,
    no unknown dialog is accepted, nothing is saved. Item-level additive sets blending
    for the entire accessory (not keyframeable). MMD has no accessory duplication,
    so N files still mean N native file dialogs.
    """
    return batch.batch_accessories(items, return_to_frame, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_delete_accessories(targets: list[dict[str, Any]], hwnd: int | None = None) -> dict[str, Any]:
    """Delete several accessories in one call. Not undoable.

    targets: [{"selector_index": int, "expected_name": str}, ...] from the current
    mmd_list_accessories. All entries are verified against the list first; then they are
    deleted highest index first, each through MMD's own confirmation dialog matched exactly
    (title, message for that name, OK). Stops at the first mismatch and reports what was
    deleted and what remains untouched.
    """
    return accessories.delete_accessories(targets, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_accessory(hwnd: int | None = None) -> dict[str, Any]:
    """Read selected accessory position, rotation, scale, opacity, visibility, shadow and parent selectors."""
    return accessories.get_accessory(hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_model_profile(model_path: str, bone_name: str | None = None,
                          bone_index: int | None = None) -> dict[str, Any]:
    """Read-only PMD/PMX file investigation: bones, axes, inheritance, IK and common-name presence.

    Optional exact Japanese/PMX English bone_name OR zero-based bone_index adds the
    target-to-root chain and related dependencies. Declared data, derived rest-hand
    geometry and unknown runtime state are separated. No MMD interaction; does not
    prove the loaded model path or predict VMD rotation from operation axes.
    """
    return poses.read_profile(model_path, bone_name, bone_index)


@mcp.tool(annotations=READ_ONLY)
def mmd_compile_pose(model_path: str, pose: poses.SemanticPose,
                     frame: Annotated[int, Field(strict=True, ge=0, le=999999)] = 0) -> dict[str, Any]:
    """Compile calibrated semantic body/arm/hand controls into absolute named bone keys, without changing MMD."""
    return poses.compile_pose(model_path, pose, frame)


@mcp.tool(annotations=EDIT)
def mmd_batch_bone_keys(items: list[bone_batch.FrameItem], model_path: str | None = None,
                        return_to_frame: bool = True, hwnd: int | None = None) -> dict[str, Any]:
    """Key bones and morphs of the active model across frames in one call (bone editing mode).

    Each item is one frame with any of: a semantic `pose` (needs model_path of the
    calibrated model; compiled to absolute bone values), explicit `bones`
    [{name, position?, rotation_degrees?}] (listed axes override the pose), `morphs`
    [{category, name, weight}], and register_key (default true). Frames are entered
    once each in ascending order; per bone: native selection, write, one readback,
    register. Digest, bone table and exposed names are verified once per batch.
    Stops at the first failure and reports applied frames; nothing is undone or saved.
    One frame with one bone is the single-edit case.
    """
    return bone_batch.batch_bone_keys(items, model_path, return_to_frame, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_batch_model_flags(items: list[model_flags.FlagFrame], return_to_frame: bool = True,
                          hwnd: int | None = None) -> dict[str, Any]:
    """Key the active model's 表示・IK・外親 panel per frame: visibility flags, IK on/off, outer parents.

    Each item: frame, optional visible/self_shadow/additive, ik [{name, enabled}] (names
    from mmd_get_ui_state ik_selector), outer_parents [{bone, parent_model_index (0 = none),
    parent_bone_name}] applied through MMD's own 外部親設定 dialog (closed afterwards),
    and register_key (default true, presses the panel's 登録). Frames ascend, one entry each.
    Stops at the first failure and reports applied frames; nothing is undone or saved.
    """
    return model_flags.batch_model_flags(items, return_to_frame, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_batch_camera_keys(items: list[camera_batch.CameraFrame], return_to_frame: bool = True,
                          hwnd: int | None = None) -> dict[str, Any]:
    """Key camera and light values across frames in one call (camera/light/accessory mode).

    Each item: frame, camera {position, rotation_degrees, distance, fov_degrees, perspective},
    light {color, direction}, register_key (default true: presses camera 登録 / light 登録).
    Frames ascend, one entry each; omitted fields keep the displayed values. Stops at the
    first failure and reports applied frames; nothing is undone or saved.
    """
    return camera_batch.batch_camera_keys(items, return_to_frame, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_read_effect_assignments(emm_path: str) -> dict[str, Any]:
    """Read a saved MMEffect assignment file (.emm), including all offscreen render targets.

    objects maps file IDs (not UI indices) to paths. effect_sections maps exact section
    names (Effect = Main, Effect@EnvLightMap, Effect@MaterialMap, etc.) to owner, default,
    assignments and explicit visibility overrides. Subsets use Pmd3[173]. effects retains
    the legacy Main-only view; sections contains raw entries. Does not inspect live MMD.
    Export current assignments from MME or save the PMM with assignment auto-save on first.
    """
    return effects.read_emm(emm_path)


@mcp.tool(annotations=EDIT)
def mmd_write_effect_assignments(emm_path: str, assignments: dict[str, str | None] | None = None,
                                 create_from_pmm: str | None = None,
                                 sections: list[effects.EffectSectionPatch] | None = None,
                                 output_path: str | None = None) -> dict[str, Any]:
    """Patch Main and/or multiple offscreen sections of an existing .emm in one call.

    sections: [{section: "Effect@MaterialMap", assignments: {"Pmd3[2]": "material.fx"},
                visibility: {"Pmd3[2]": true}}]. Use exact section names and object IDs from
    mmd_read_effect_assignments. Offscreen sections must already exist with a known Owner.
    Optional assignments is the legacy shorthand for Main (Effect); do not repeat a section.
    Null removes an effect (none); visibility false hides it in that render target. Paths are
    absolute or relative to MMD, not the EMM. Legacy dotted subset input is normalized to brackets.
    Owner, Default, comments and unedited entries are preserved. All changes validate before
    writing. Omit output_path to replace the source; specify a NEW absolute .emm path to keep it.
    File edit only: import via MME's File > Load settings or reload the adjacent PMM to apply.
    create_from_pmm remains reserved and refused. No live MMD, model, frame or PMM changes.
    """
    return effects.write_emm(emm_path, assignments, create_from_pmm,
                             sections=sections, output_path=output_path)


@mcp.tool(annotations=READ_ONLY)
def mmd_read_motion_document(path: str) -> dict[str, Any]:
    """Read and validate authoring JSON. This does not extract keys from an existing PMM or VMD."""
    return motions.read_document(path).model_dump()


@mcp.tool(annotations=READ_ONLY)
def mmd_edit_motion_document(document: motions.MotionDocument,
                              edits: Annotated[list[motions.KeyEdit], Field(min_length=1, max_length=10000)]) -> dict[str, Any]:
    """Return sparse authoring data with keys upserted/deleted; edit complete incoming interpolation per key.

    No files or MMD state change. To move a key, delete its old frame and upsert its new frame.
    Rotations use MMD bone-panel degrees; incoming curves govern the segment ending at that key.
    """
    return motions.edit_document(document, edits).model_dump()


@mcp.tool(annotations=SELECT)
def mmd_write_motion_document(document: motions.MotionDocument, path: str,
                               kind: Literal['json', 'vmd'] = 'json') -> dict[str, Any]:
    """Save validated authoring JSON or export VMD at a NEW absolute path; existing files are refused.

    Never loads the result into MMD. VMD export preserves sparse keys and per-channel Bezier curves.
    Use mmd_load_file separately, at frame 0, to import file-absolute timing into a chosen model.
    """
    return motions.save_document(document, path, kind)


@mcp.tool(annotations=EDIT)
def mmd_preview_motion(output_directory: str,
                         start_frame: Annotated[int, Field(strict=True, ge=0, le=999999)],
                         end_frame: Annotated[int, Field(strict=True, ge=0, le=999999)],
                         step: Annotated[int, Field(strict=True, ge=1, le=30)],
                         allow_frame_evaluation: Annotated[bool, Field(strict=True)], hwnd: int) -> dict[str, Any]:
    """Sample up to 180 frames into a new directory with PNGs, contact sheet and timed MJPG AVI.

    Requires explicit allow_frame_evaluation=true because frame changes discard unregistered poses.
    Restores the original frame on success. No keys/save/import. Sequential evaluation is not
    a deterministic physics bake or real-time playback check. Do not interact with MMD while sampling.
    """
    return authoring.preview_motion(output_directory, start_frame, end_frame, step, allow_frame_evaluation, hwnd)


@mcp.tool(annotations=SELECT)
def mmd_select_bone(name: str | None = None,
                    bone_index: Annotated[int, Field(strict=True, ge=0)] | None = None,
                    hwnd: int | None = None) -> dict[str, Any]:
    """Select exactly one bone by unique name or transient index on the active model.

    Select a model first. Uses a single-purpose temporary DLL hook on MMD's UI
    thread to run its native bone-selection routine. Requires the exact verified
    MMD 9.32 x64 executable and the built native bridge. No mouse/key simulation,
    MMDPlugin, transform edit, or key registration. Internal/end bones are refused.
    """
    return select_bone(name, bone_index, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_dialogs(hwnd: int | None = None) -> dict[str, Any]:
    """Read visible dialogs owned by MMD, including text and available buttons.

    Available while MMD has a modal dialog open. Does not accept any dialog.
    """
    return files.get_dialogs(hwnd)


@mcp.tool(annotations=EDIT)
def mmd_load_file(kind: Literal["model", "project", "pose", "motion", "accessory", "audio", "background_image", "background_video"], path: str,
                  hwnd: int | None = None) -> dict[str, Any]:
    """Load a PMD/PMX model, PMM project, VPD pose, VMD motion or X accessory using MMD dialogs.

    Requires an existing absolute path. Pose/motion apply to the current target;
    accessory requires camera/light/accessory mode (model selector 0).
    select the correct model or camera first. Imports can replace existing values
    and keys. Project loading replaces the scene. Model information is returned.
    VMD times are offset by the current frame; move to frame 0 for file-absolute
    timing. After a VPD, the current single bone's numeric panel is refreshed.
    Unknown dialogs are left open and reported, never blindly acknowledged.
    """
    return files.load_file(kind, path, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_save_project(path: str, overwrite: Annotated[bool, Field(strict=True)] = False,
                     hwnd: int | None = None) -> dict[str, Any]:
    """Save the current MMD project as a PMM at an absolute path.

    Parent directory must exist. Existing files are refused unless overwrite=true.
    Uses MMD's Save As dialog; unknown dialogs are reported and left open.
    """
    return files.save_project(path, overwrite, hwnd)


@mcp.tool(annotations=EDIT)
def mmd_export_file(kind: Literal["pose", "motion", "image"], path: str,
                     overwrite: Annotated[bool, Field(strict=True)] = False,
                     hwnd: int | None = None) -> dict[str, Any]:
    """Export a native VPD, VMD or image to an absolute path through MMD's save dialog.

    Uses the current model/selection and MMD's native export semantics. Pose requires
    a selected model. Existing output requires overwrite=true. Unknown dialogs are
    returned for inspection and never accepted. Checks that output was actually written.
    """
    return files.export_file(kind, path, overwrite, hwnd)


@mcp.tool(annotations=SELECT)
def mmd_select_model(selector_index: Annotated[int, Field(strict=True, ge=0)] | None = None,
                     name: str | None = None, hwnd: int | None = None) -> dict[str, Any]:
    """Select a loaded model by exact unique name or current UI selector index.

    Specify exactly one selector_index or name. Index 0 selects the camera/light/
    accessory editing panels. Selection changes are explicit; no key is registered.
    """
    return scene.select_model(selector_index, name, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_camera(hwnd: int | None = None) -> dict[str, Any]:
    """Read camera center position, rotation degrees, distance, FOV and perspective.

    Select camera/light/accessory (mmd_select_model selector_index=0) first.
    Values are UI-rounded and follow MMD's camera-center/distance convention.
    """
    return scene.get_camera(hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_light(hwnd: int | None = None) -> dict[str, Any]:
    """Read MMD's directional light color (RGB 0..255) and direction components.

    Select camera/light/accessory first. Values are those displayed by MMD.
    """
    return scene.get_light(hwnd)


@mcp.tool(annotations=EDIT)
def mmd_set_frame(frame: Annotated[int, Field(strict=True, ge=0, le=999999)],
                  hwnd: int | None = None) -> dict[str, Any]:
    """Move to an animation frame through MMD's native frame input handler.

    This evaluates the animation, so unregistered edits can be replaced by keyed
    values. Register desired edits first. Does not add keys or save to disk.
    """
    return scene.set_frame(frame, hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_list_bones(hwnd: int | None = None) -> dict[str, Any]:
    """List active model bone names/indices and the selected bone identity.

    Uses read-only process memory after checking the exact verified Japanese MMD
    9.32 x64 executable digest. Unsupported builds fail without reading offsets.
    Includes internal bones; names can duplicate or be truncated. Does not select
    a bone or change the scene. Indices are not persistent IDs.
    """
    return list_bones(hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_selected_bone_transform(hwnd: int | None = None) -> dict[str, Any]:
    """Read the active bone transform panel in MMD (position and rotation degrees).

    Select a bone first. Includes its name/index and selection count from the exact
    verified Japanese MMD 9.32 x64 layout. Requires bone editing mode. Do not change
    selection during the call. Transform values are UI-rounded.
    """
    return get_selected_bone_transform(hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_list_windows() -> list[dict]:
    """List running MMD windows, including HWND, PID, title and minimized state."""
    return [window.public_info() for window in list_windows()]


@mcp.tool(annotations=READ_ONLY)
def mmd_list_models(hwnd: int | None = None) -> dict[str, Any]:
    """Read model names and current selection from MMD's model selector.

    Selector indices are transient, not stable model IDs. No paths or model file
    contents are read. Requires the verified MMD 9.x control layout and idle UI.
    """
    return list_models(hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_get_ui_state(hwnd: int | None = None) -> dict[str, Any]:
    """Read displayed frame, models, morph panel names/weights and IK selector.

    Does not change frame or selection. This is a sequential UI observation, not
    full internal scene state. Missing values are unknown, not zero. Requires
    restored MMD with no modal dialog and the verified MMD 9.x control layout.
    """
    return get_ui_state(hwnd)


@mcp.tool(annotations=READ_ONLY)
def mmd_capture_window(hwnd: int | None = None) -> Image:
    """Return a PNG of the MMD window including UI and any visible guides.

    If multiple MMD windows exist, specify hwnd from mmd_list_windows.
    The window must be restored and modal dialogs closed. No scene edits are made.
    This captures the current display; it does not guarantee a render after an edit.
    """
    return Image(data=capture_png(hwnd), format="png")


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
