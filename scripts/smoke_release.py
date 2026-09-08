"""Release gates against a NEW MMD process through the installed stdio MCP server.

Requires --apply --mmd-exe ABS_EXE --model ABS_PMD --second-model ABS_PMD.
Never selects or terminates pre-existing MMD processes. Artifacts stay in local/.
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mmd_mcp.windows import list_windows
from mmd_mcp.ui_state import UIReader
from mmd_mcp.scene_controls import context


async def check(executable, model, second_model, english=False):
    output = Path(__file__).resolve().parents[1] / "local" / f"release-smoke-{datetime.now():%Y%m%d-%H%M%S}"
    output.mkdir(parents=True)
    report = {"output": str(output), "steps": [], "ui_language": "en" if english else "ja"}
    process = subprocess.Popen([str(executable)], cwd=executable.parent)
    report["test_pid"] = process.pid
    try:
        target = None
        for _ in range(150):
            target = next((w for w in list_windows() if w.pid == process.pid), None)
            if target:
                try:
                    context(UIReader(target.hwnd))
                except (RuntimeError, ValueError):
                    pass
                else:
                    break
            await asyncio.sleep(.1)
        assert target
        if english:
            from mmd_mcp.native_dialogs import menu_command
            menu_command(target.hwnd, 260)
            await asyncio.sleep(.2)
        label = lambda ja, en: en if english else ja
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "mmd_mcp.server"])
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                async def call(tool, *, live=True, **args):
                    response = await session.call_tool(tool, {**({"hwnd": target.hwnd} if live else {}), **args})
                    assert not response.isError, (tool, response)
                    data = response.structuredContent
                    assert data is not None, (tool, response)
                    report["steps"].append({"tool": tool, "arguments": args, "result": data})
                    assert data.get("status", "completed") in {"completed", "rendering"}, (tool, data)
                    print(f"OK {tool}", flush=True)
                    return data

                async def motion(filename, actions):
                    await call("mmd_edit_actions", actions=actions)
                    path = output / filename
                    await call("mmd_export_file", kind="motion", path=str(path))
                    return await call("mmd_inspect_vmd", live=False, path=str(path), limit=1000)

                before = (await call("mmd_get_scene_settings"))["settings"]
                from mmd_mcp.scene_settings import TOGGLES, GROUPS
                for name in TOGGLES:
                    if name in {"background_image", "background_video"} or before[name] is None:
                        continue
                    await call("mmd_set_scene_settings", settings={name: not before[name]})
                    await call("mmd_set_scene_settings", settings={name: before[name]})
                for name, choices in GROUPS.items():
                    for choice in choices:
                        await call("mmd_set_scene_settings", settings={name: choice})
                    await call("mmd_set_scene_settings", settings={name: before[name]})
                size = await call("mmd_output_size", size={"width": 320, "height": 180})
                assert size["size"] == {"width": 320, "height": 180}
                background = output / "background.png"
                pixels = np.zeros((180, 320, 3), dtype=np.uint8)
                pixels[:, :, 1] = 96
                assert cv2.imwrite(str(background), pixels)
                await call("mmd_load_file", kind="background_image", path=str(background))
                await call("mmd_set_scene_settings", settings={"background_image": True})
                await call("mmd_set_scene_settings", settings={"background_image": False})
                audio = output / "silence.wav"
                with wave.open(str(audio), "wb") as stream:
                    stream.setparams((1, 2, 44100, 44100, "NONE", "not compressed"))
                    stream.writeframes(bytes(88200))
                await call("mmd_load_file", kind="audio", path=str(audio))
                await call("mmd_batch_camera_keys", items=[
                    {"frame": 10, "camera": {"distance": 35}, "shadow": {"mode": 2, "distance": 8000},
                     "gravity": {"acceleration": 4.9, "x": .1, "noise": True, "noise_amount": 3}},
                    {"frame": 20, "camera": {"distance": 40}}])
                await call("mmd_set_frame", frame=10)
                assert (await call("mmd_get_gravity"))["gravity"]["acceleration"] == 4.9
                await call("mmd_set_playback", playing=True, options={"start_frame": 10, "end_frame": 20, "repeat": True})
                assert (await call("mmd_get_playback"))["playing"]
                await call("mmd_set_playback", playing=False)
                await call("mmd_select_key_range", start_frame=10, end_frame=10, track_name=label("カメラ", "camera"))
                await call("mmd_edit_actions", actions=["copy_keys"])
                await call("mmd_set_frame", frame=30)
                await call("mmd_edit_actions", actions=["paste_keys"])
                exported = await motion("camera-pasted.vmd", ["select_camera_keys"])
                assert {r["frame"]: r["distance"] for r in exported["records"]} == {0: -45., 10: -35., 20: -40., 30: -35.}
                await call("mmd_select_key_range", start_frame=30, end_frame=30, track_name=label("カメラ", "camera"))
                await call("mmd_edit_actions", actions=["delete_keys"])
                await call("mmd_select_key_range", start_frame=10, end_frame=20, track_name=label("カメラ", "camera"))
                await call("mmd_transform_timeline", spec={"operation": "camera_correction", "position_offset": {"x": 2}})
                corrected = await motion("camera-corrected.vmd", ["select_camera_keys"])
                assert all(r["position"]["x"] == 2 for r in corrected["records"] if r["frame"] in {10, 20})
                curve = {"x1": 10, "y1": 5, "x2": 90, "y2": 120}
                await call("mmd_edit_vmd", live=False, source_path=str(output / "camera-corrected.vmd"),
                           output_path=str(output / "camera-curve.vmd"),
                           edits=[{"action": "interpolation", "track": "camera", "start_frame": 10,
                                   "end_frame": 10, "curves": {"distance": curve}}])
                await call("mmd_set_frame", frame=0)
                await call("mmd_load_file", kind="motion", path=str(output / "camera-curve.vmd"))
                curve_back = await motion("camera-curve-readback.vmd", ["select_camera_keys"])
                assert next(r for r in curve_back["records"] if r["frame"] == 10)["interpolation_bytes"][16:20] == [10, 90, 5, 120]
                image_path = output / "native.png"
                await call("mmd_export_file", kind="image", path=str(image_path))
                image_data = cv2.imread(str(image_path))
                assert image_data.shape[:2] == (180, 320)
                video_path = output / "native.avi"
                job = await call("mmd_export_video", path=str(video_path),
                                 options={"start_frame": 0, "end_frame": 2, "include_audio": True})
                for _ in range(150):
                    if job["status"] == "completed":
                        break
                    await asyncio.sleep(.1)
                    job = await call("mmd_get_video_export_status", live=False, job_id=job["job_id"])
                assert job["status"] == "completed" and job["avi"]["frames"] == 3 and job["avi"]["streams"] == 2
                await call("mmd_load_file", kind="background_video", path=str(video_path))
                await call("mmd_set_scene_settings", settings={"background_video": True})
                await call("mmd_set_scene_settings", settings={"background_video": False})
                first = await call("mmd_load_file", kind="model", path=str(model))
                first_name = first["after"]["model_selector"]["selected_name"]
                await call("mmd_load_file", kind="model", path=str(second_model))
                for kind in ("draw", "compute"):
                    order = await call("mmd_model_order", kind=kind)
                    await call("mmd_model_order", kind=kind, order=[1, 0], expected_names=order["names"])
                await call("mmd_select_model", name=first_name)
                await call("mmd_set_render_style", style={"edge_width": 1.2, "ground_shadow_brightness": .5, "edge_color": {"r": 12, "g": 34, "b": 56}})
                await call("mmd_batch_bone_keys", items=[{"frame": 10, "bones": [{"name": "左腕", "rotation_degrees": {"z": -15}}],
                                                            "morphs": [{"category": "eyes", "name": label("まばたき", "blink"), "weight": .5}]}])
                await call("mmd_set_frame", frame=10)
                await call("mmd_export_file", kind="pose", path=str(output / "native.vpd"))
                await call("mmd_select_key_range", start_frame=10, end_frame=10, track_name=label("左腕", "arm_L"))
                bone_source = await motion("bone-source.vmd", ["select_bone_keys", "select_morph_keys", "select_model_flag_keys"])
                await call("mmd_edit_vmd", live=False, source_path=str(output / "bone-source.vmd"), output_path=str(output / "bone-curve.vmd"),
                           edits=[{"action": "interpolation", "track": "bones", "names": ["左腕"], "start_frame": 10, "end_frame": 10, "curves": {"rotation": curve}}])
                await call("mmd_set_frame", frame=0)
                await call("mmd_load_file", kind="motion", path=str(output / "bone-curve.vmd"))
                bone_back = await motion("bone-curve-readback.vmd", ["select_bone_keys"])
                assert next(r for r in bone_back["records"] if r["name"] == "左腕" and r["frame"] == 10)["interpolation"]["rotation"] == curve
                emm = output / "before.emm"
                assignments = await call("mmd_transfer_effect_assignments", operation="export", path=str(emm))
                identity = next(iter(assignments["assignments"]["objects"]))
                await call("mmd_write_effect_assignments", live=False, emm_path=str(emm), output_path=str(output / "hidden.emm"),
                           sections=[{"visibility": {identity: False}}])
                await call("mmd_transfer_effect_assignments", operation="import", path=str(output / "hidden.emm"))
                back = await call("mmd_transfer_effect_assignments", operation="export", path=str(output / "readback.emm"))
                assert back["assignments"]["effect_sections"]["Effect"]["visibility"][identity] is False
                await call("mmd_transfer_effect_assignments", operation="import", path=str(emm))
                await call("mmd_save_project", path=str(output / "roundtrip.pmm"))
                await call("mmd_load_file", kind="project", path=str(output / "roundtrip.pmm"))
                models = await call("mmd_list_models")
                entries = models["models"]
                await call("mmd_delete_models", targets=[{"selector_index": item["selector_index"], "expected_name": item["name"]} for item in entries])
                await call("mmd_new_project", discard_current=True)
        report["status"] = "passed"
        print(f"PASS {len(report['steps'])} release checks: {output}", flush=True)
    except BaseException as error:
        report["status"], report["error"] = "failed", str(error)
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--mmd-exe", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--second-model", type=Path, required=True)
    parser.add_argument("--english", action="store_true")
    args = parser.parse_args()
    asyncio.run(check(args.mmd_exe.resolve(), args.model.resolve(), args.second_model.resolve(), args.english))
