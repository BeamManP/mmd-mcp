"""Additional native editing/undo/transform gates in a NEW MMD process."""

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mmd_mcp import accessory_batch, accessory_controls, bone_batch, edit_actions
from mmd_mcp import file_operations as files, scene_controls as scene, timeline, timeline_transforms, vmd_reader
from mmd_mcp.bone_controls import get_selected_bone_transform
from mmd_mcp.windows import list_windows


def check(exe, model, english=False):
    output = Path(__file__).resolve().parents[1] / "local" / f"editing-smoke-{datetime.now():%Y%m%d-%H%M%S}"
    output.mkdir(parents=True)
    process = subprocess.Popen([str(exe)], cwd=exe.parent)
    report = {"test_pid": process.pid, "steps": [], "ui_language": "en" if english else "ja"}
    try:
        for _ in range(150):
            target = next((w for w in list_windows() if w.pid == process.pid), None)
            if target:
                break
            time.sleep(.1)
        assert target
        h = target.hwnd
        if english:
            from mmd_mcp.native_dialogs import menu_command
            menu_command(h, 260)
            time.sleep(.2)
        label = lambda ja, en: en if english else ja
        def record(name, result):
            report["steps"].append({"name": name, "result": result})
            assert result.get("status", "completed") == "completed", (name, result)
            print(f"OK {name}", flush=True)
            return result
        def actions(*names):
            return record("actions: " + ",".join(names), edit_actions.perform(list(names), h))
        def export(label):
            actions("select_bone_keys", "select_morph_keys", "select_model_flag_keys")
            path = output / (label + ".vmd")
            record(label, files.export_file("motion", str(path), hwnd=h))
            return vmd_reader.inspect(str(path), limit=1000)["records"]
        def transform(**spec):
            return record(spec["operation"], timeline_transforms.transform(spec, h))

        record("load_model", files.load_file("model", str(model), h))
        record("unregistered_pose", bone_batch.batch_bone_keys([
            bone_batch.FrameItem(frame=0, bones=[{"name": "左腕", "rotation_degrees": {"z": -20}}], register_key=False)],
            return_to_frame=False, hwnd=h))
        actions("undo")
        assert get_selected_bone_transform(h)["rotation_degrees"]["z"] == 0
        actions("redo")
        assert get_selected_bone_transform(h)["rotation_degrees"]["z"] == -20
        actions("copy_bones", "paste_bones", "mirror_paste_bones", "reset_bones", "select_all_bones", "select_unregistered_bones")
        record("keys", bone_batch.batch_bone_keys([bone_batch.FrameItem(frame=10,
            bones=[{"name": "左腕", "rotation_degrees": {"z": -15}}, {"name": "センター", "position": {"x": 2}}],
            morphs=[{"category": "eyes", "name": label("まばたき", "blink"), "weight": .5}, {"category": "mouth", "name": label("あ", "a"), "weight": .3}])], hwnd=h))
        timeline.select_range(10, 10, label("左腕", "arm_L"), h)
        actions("copy_keys")
        scene.set_frame(30, h)
        actions("paste_keys")
        copied = export("copied")
        arm = [r for r in copied if r["track"] == "bones" and r["name"] == "左腕"]
        assert next(r for r in arm if r["frame"] == 10)["quaternion_xyzw"] == next(r for r in arm if r["frame"] == 30)["quaternion_xyzw"]
        scene.set_frame(10, h)
        actions("insert_bone_camera_frame")
        inserted = export("inserted")
        assert any(r["track"] == "bones" and r["name"] == "左腕" and r["frame"] == 11 for r in inserted)
        actions("delete_bone_camera_column")
        restored = export("column_restored")
        assert any(r["track"] == "bones" and r["name"] == "左腕" and r["frame"] == 10 for r in restored)
        transform(operation="scale_time", start_frame=0, end_frame=30, factor=2, tracks=["bones"])
        scaled = export("scaled")
        assert any(r["track"] == "bones" and r["name"] == "左腕" and r["frame"] == 60 for r in scaled)
        timeline.select_range(20, 20, label("センター", "center"), h)
        transform(operation="bone_correction", position_offset={"x": 1})
        corrected = export("corrected")
        assert next(r for r in corrected if r["track"] == "bones" and r["name"] == "センター" and r["frame"] == 20)["position"]["x"] == 3
        timeline.select_range(10, 10, label("まばたき", "blink"), h)
        transform(operation="morph_correction", weight_scale=.5)
        corrected = export("morph_corrected")
        assert next(r for r in corrected if r["track"] == "morphs" and r["name"] == "まばたき" and r["frame"] == 10)["weight"] == .25
        transform(operation="center_bias", position_offset={"y": 1})
        transform(operation="random_blink", start_frame=60, end_frame=900)
        transform(operation="lip_shift", shift_frames=5)
        shifted = export("lip_shifted")
        assert any(r["track"] == "morphs" and r["name"] == "あ" and r["frame"] == 15 for r in shifted)
        record("bone_physics", bone_batch.batch_bone_keys([bone_batch.FrameItem(frame=10,
            bones=[{"name": "左腕", "physics": True}])], return_to_frame=False, hwnd=h))
        actions("select_physics_bones", "select_physics_keys")
        transform(operation="physics_state", physics_enabled=False)
        actions("delete_lip_keys", "delete_eye_keys", "delete_eyebrow_keys", "reset_morphs", "register_all_morphs", "reset_rigid_bodies")
        deleted = export("morph_deleted")
        assert not any(r["track"] == "morphs" and r["name"] in {"あ", "まばたき"} and r["frame"] > 10 for r in deleted)
        scene.select_model(0, hwnd=h)
        accessory = exe.parent / "UserFile/Accessory/negi.x"
        record("load_accessory", files.load_file("accessory", str(accessory), h))
        record("additive", accessory_batch.batch_accessories([
            accessory_batch.AccessoryItem(selector_index=0, additive=True)], hwnd=h))
        scene.set_frame(0, h)
        assert accessory_controls.get_accessory(h)["additive"] is True
        scene.set_frame(20, h)
        assert accessory_controls.get_accessory(h)["additive"] is True
        actions("reset_camera", "reset_light", "view_front", "view_back", "view_top", "view_left", "view_right", "view_camera")
        report["status"] = "passed"
        print(f"PASS {len(report['steps'])} editing checks: {output}", flush=True)
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--mmd-exe", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--english", action="store_true")
    args = parser.parse_args()
    check(args.mmd_exe.resolve(), args.model.resolve(), args.english)
