"""Create an isolated MMD test instance and exercise real stdio MCP editing.

Usage: python scripts/smoke_scene.py --apply --mmd-exe ABS_EXE --model ABS_MIKU_PMD
Only the newly launched process is edited/terminated. Existing MMDs are untouched.
"""

import argparse
import asyncio
import base64
import json
import math
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mmd_mcp.windows import list_windows


def fixtures(directory, model_name):
    angle = math.radians(-10) / 2
    pose = ("Vocaloid Pose Data file\n\nfixture.osm;\n1;\n\nBone0{左腕\n"
            f"  0.000000,0.000000,0.000000;\n  0.000000,0.000000,{math.sin(angle):.8f},{math.cos(angle):.8f};\n}}\n")
    (directory / "fixture.vpd").write_bytes(pose.replace("\n", "\r\n").encode("cp932"))
    header = b"Vocaloid Motion Data 0002".ljust(30, b"\0")
    name = model_name.encode("cp932")[:20].ljust(20, b"\0")
    angle = math.radians(-35) / 2
    bone = "左腕".encode("cp932").ljust(15, b"\0") + struct.pack("<I7f", 24, 0, 0, 0, 0, 0, math.sin(angle), math.cos(angle)) + bytes(64)
    morph = "まばたき".encode("cp932").ljust(15, b"\0") + struct.pack("<If", 24, .2)
    (directory / "fixture-model.vmd").write_bytes(header + name + struct.pack("<I", 1) + bone + struct.pack("<I", 1) + morph + bytes(16))
    camera = struct.pack("<If6f", 24, -36, 1, 12, 0, 0, 0, 0) + bytes(24) + struct.pack("<IB", 42, 0)
    light = struct.pack("<I6f", 24, .8, .6, .4, -.3, -.7, .2)
    (directory / "fixture-camera-light.vmd").write_bytes(header + "カメラ・照明".encode("cp932").ljust(20, b"\0") + bytes(8)
                                                     + struct.pack("<I", 1) + camera + struct.pack("<I", 1) + light + bytes(8))


async def check(executable, model_path, keep_open, english=False):
    output = Path(__file__).resolve().parents[1] / "local" / f"scene-smoke-{datetime.now():%Y%m%d-%H%M%S}"
    output.mkdir(parents=True)
    process = subprocess.Popen([str(executable)], cwd=executable.parent)
    report = {"test_pid": process.pid, "steps": [], "output_directory": str(output)}
    try:
        target = None
        for _ in range(150):
            target = next((window for window in list_windows() if window.pid == process.pid), None)
            if target:
                break
            await asyncio.sleep(.1)
        assert target, "New MMD test window did not appear"
        report["test_hwnd"] = target.hwnd
        report["ui_language"] = "en" if english else "ja"
        if english:
            from mmd_mcp.native_dialogs import menu_command
            menu_command(target.hwnd, 260)
            await asyncio.sleep(.2)
        label = lambda ja, en: en if english else ja
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "mmd_mcp.server"])
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def call(tool_name, **arguments):
                    response = await session.call_tool(tool_name, {"hwnd": target.hwnd, **arguments})
                    assert not response.isError, (tool_name, response)
                    data = response.structuredContent
                    assert data is not None, (tool_name, response)
                    if "status" in data:
                        assert data["status"] == "completed", (tool_name, data)
                    report["steps"].append({"tool": tool_name, "arguments": arguments, "result": data})
                    print(f"OK {tool_name}", flush=True)
                    return data

                async def rejected(tool_name, **arguments):
                    response = await session.call_tool(tool_name, {"hwnd": target.hwnd, **arguments})
                    assert response.isError, (tool_name, response)
                    report["steps"].append({"tool": tool_name, "arguments": arguments, "expected_error": True})
                    print(f"OK rejected {tool_name}", flush=True)

                loaded = await call("mmd_load_file", kind="model", path=str(model_path))
                model_name = loaded["after"]["model_selector"]["selected_name"]
                from mmd_mcp.pose_authoring import read_profile
                fixtures(output, read_profile(str(model_path))["model_name"])
                await call("mmd_list_bones")
                await call("mmd_set_frame", frame=12)
                await call("mmd_select_bone", name="左腕")
                await rejected("mmd_select_bone", name="missing-bone-should-not-exist")
                await rejected("mmd_batch_bone_keys", items=[{"frame": 12, "bones": [{"name": "missing-bone-should-not-exist", "rotation_degrees": {"z": 10}}]}])
                await call("mmd_batch_bone_keys", items=[{"frame": 12, "bones": [{"name": "左腕", "rotation_degrees": {"z": -20}}],
                                                         "morphs": [{"category": "eyes", "name": label("まばたき", "blink"), "weight": .65}]}])
                await call("mmd_select_model", selector_index=0)
                await call("mmd_batch_camera_keys", items=[{"frame": 12,
                           "camera": {"position": {"x": 2, "y": 11, "z": 0}, "rotation_degrees": {"x": 5, "y": 15, "z": 0},
                                      "distance": 38, "fov_degrees": 35, "perspective": True},
                           "light": {"color": {"r": 190, "g": 150, "b": 120}, "direction": {"x": -.4, "y": -.8, "z": .3}}}])
                await call("mmd_set_frame", frame=13)
                await call("mmd_set_frame", frame=12)
                camera = await call("mmd_get_camera")
                light = await call("mmd_get_light")
                assert camera["position"] == {"x": 2, "y": 11, "z": 0} and camera["distance"] == 38
                assert camera["rotation_degrees"] == {"x": 5, "y": 15, "z": 0} and camera["fov_degrees"] == 35
                assert light["color"] == {"r": 190, "g": 150, "b": 120} and light["direction"] == {"x": -.4, "y": -.8, "z": .3}
                await call("mmd_select_model", name=model_name)
                await call("mmd_select_bone", name="左腕")
                bone = await call("mmd_get_selected_bone_transform")
                state = await call("mmd_get_ui_state")
                assert bone["rotation_degrees"]["z"] == -20
                assert state["morph_panels"]["eyes"]["displayed_weight"] == .65
                flags = await call("mmd_batch_model_flags", items=[{"frame": 12, "ik": [{"name": label("右足ＩＫ", "leg IK_R"), "enabled": False}], "self_shadow": False}])
                assert flags["frames_completed"][0]["ik"] == [{"name": label("右足ＩＫ", "leg IK_R"), "enabled": False}], flags
                await call("mmd_batch_model_flags", items=[{"frame": 12, "ik": [{"name": label("右足ＩＫ", "leg IK_R"), "enabled": True}], "self_shadow": True}])
                for parent in (1, 0):
                    await call("mmd_batch_model_flags", items=[{"frame": 12, "outer_parents": [
                        {"bone": label("センター", "center"), "parent_model_index": parent}]}])
                await call("mmd_select_model", selector_index=0)
                accessory_x = next(executable.parent.glob("UserFile/**/*.x"), None)
                if accessory_x is not None:
                    placed = await call("mmd_batch_accessories", items=[
                        {"path": str(accessory_x), "keys": [{"frame": 0, "position": {"x": -5, "y": 0, "z": 0}}, {"frame": 30, "opacity": .5}]},
                        {"path": str(accessory_x), "keys": [{"frame": 0, "position": {"x": 5, "y": 0, "z": 0}}]}])
                    indices = [entry["selector_index"] for entry in placed["loaded"]]
                    assert len(indices) == 2, placed
                    removed = await call("mmd_delete_accessories", targets=[{"selector_index": i, "expected_name": accessory_x.name} for i in indices])
                    assert len(removed["deleted"]) == 2, removed
                capture = await session.call_tool("mmd_capture_window", {"hwnd": target.hwnd})
                assert not capture.isError, capture
                image = next(item for item in capture.content if item.type == "image")
                (output / "character-camera-light.png").write_bytes(base64.b64decode(image.data))
                scene_path = output / "character-camera-light.pmm"
                await call("mmd_save_project", path=str(scene_path))
                await rejected("mmd_save_project", path=str(scene_path))
                await call("mmd_save_project", path=str(scene_path), overwrite=True)
                await call("mmd_batch_camera_keys", items=[{"frame": 12, "camera": {"position": {"x": 9}}, "register_key": False}])
                await call("mmd_load_file", kind="project", path=str(scene_path))
                camera = await call("mmd_get_camera")
                assert camera["position"]["x"] == 2
                await call("mmd_select_model", selector_index=1)
                await call("mmd_select_bone", name="左腕")
                await call("mmd_load_file", kind="pose", path=str(output / "fixture.vpd"))
                bone = await call("mmd_get_selected_bone_transform")
                assert abs(bone["rotation_degrees"]["z"] - 10) < .11, bone
                await call("mmd_set_frame", frame=0)
                await call("mmd_load_file", kind="motion", path=str(output / "fixture-model.vmd"))
                await call("mmd_set_frame", frame=24)
                await call("mmd_select_bone", name="左腕")
                bone = await call("mmd_get_selected_bone_transform")
                state = await call("mmd_get_ui_state")
                assert abs(bone["rotation_degrees"]["z"] - 35) < .11, bone
                assert abs(state["morph_panels"]["eyes"]["displayed_weight"] - .2) < .0001, state
                await call("mmd_select_model", selector_index=0)
                await call("mmd_set_frame", frame=0)
                await call("mmd_load_file", kind="motion", path=str(output / "fixture-camera-light.vmd"))
                await call("mmd_set_frame", frame=25)
                await call("mmd_set_frame", frame=24)
                camera = await call("mmd_get_camera")
                light = await call("mmd_get_light")
                assert camera["position"] == {"x": 1, "y": 12, "z": 0} and camera["fov_degrees"] == 42, camera
                assert abs(camera["distance"]) == 36, camera
                assert all(abs(light["color"][axis] - value) <= 1 for axis, value in {"r": 204, "g": 153, "b": 102}.items()), light
                await call("mmd_load_file", kind="model", path=str(model_path))
                await rejected("mmd_select_model", name=model_name)
                await call("mmd_select_model", selector_index=2)
                await call("mmd_batch_bone_keys", items=[{"frame": 24, "bones": [{"name": "左腕", "rotation_degrees": {"z": -15}}], "register_key": False}])
                await call("mmd_select_model", selector_index=1)
                await call("mmd_select_bone", name="左腕")
                bone = await call("mmd_get_selected_bone_transform")
                assert abs(bone["rotation_degrees"]["z"] - 35) < .11, bone
                report["status"] = "passed"
                print(f"PASS {len(report['steps'])} checks. Evidence: {output}", flush=True)
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not keep_open and process.poll() is None:
            process.terminate()  # Only the disposable process this test created.
            process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--mmd-exe", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True, help="Existing Miku PMD/PMX with 左腕 and まばたき")
    parser.add_argument("--keep-open", action="store_true", help="Keep the isolated test MMD open for inspection")
    parser.add_argument("--english", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Pass --apply to authorize edits in a newly launched disposable MMD instance.")
    for path in (args.mmd_exe, args.model):
        if not path.is_absolute() or not path.is_file():
            parser.error("Use existing absolute executable/model paths.")
    asyncio.run(check(args.mmd_exe.resolve(), args.model.resolve(), args.keep_open, args.english))
