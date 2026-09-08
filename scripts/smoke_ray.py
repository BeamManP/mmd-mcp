"""Opt-in real RayMMD Main/subset/offscreen EMM roundtrip in an isolated MMD."""

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mmd_mcp.windows import list_windows


async def check(executable, model, ray):
    output = Path(__file__).resolve().parents[1] / "local" / f"ray-smoke-{datetime.now():%Y%m%d-%H%M%S}"
    output.mkdir(parents=True)
    report = {"steps": []}
    process = subprocess.Popen([str(executable)], cwd=executable.parent)
    report["test_pid"] = process.pid
    try:
        for _ in range(150):
            target = next((w for w in list_windows() if w.pid == process.pid), None)
            if target:
                break
            await asyncio.sleep(.1)
        assert target
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "mmd_mcp.server"])) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                async def call(tool, live=True, **arguments):
                    response = await session.call_tool(tool, {**({"hwnd": target.hwnd} if live else {}), **arguments})
                    assert not response.isError, (tool, response)
                    result = response.structuredContent
                    report["steps"].append({"tool": tool, "result": result})
                    assert result.get("status", "completed") == "completed", (tool, result)
                    print(f"OK {tool}", flush=True)
                    return result
                await call("mmd_set_scene_settings", settings={"antialiasing": False, "ground_shadow": False})
                await call("mmd_load_file", kind="model", path=str(model))
                await call("mmd_select_model", selector_index=0)
                await call("mmd_load_file", kind="accessory", path=str(ray / "ray.x"))
                await call("mmd_load_file", kind="model", path=str(ray / "Skybox/Sky Hemisphere/Sky with box.pmx"))
                exported = await call("mmd_transfer_effect_assignments", operation="export", path=str(output / "before.emm"))
                assignments = exported["assignments"]
                model_id = next(key for key, value in assignments["objects"].items() if value.replace("\\", "/").endswith(model.name))
                sky_id = next(key for key, value in assignments["objects"].items() if value.replace("\\", "/").endswith("Sky with box.pmx"))
                patches = [
                    {"section": "Effect", "assignments": {model_id: str(ray / "Main/main.fx"), model_id + "[0]": str(ray / "Main/main_ex_alpha.fx")}},
                    {"section": "Effect@EnvLightMap", "assignments": {sky_id: str(ray / "Skybox/Sky Hemisphere/Sky with lighting.fx")}},
                    {"section": "Effect@MaterialMap", "assignments": {model_id: str(ray / "Materials/Transparent/material_glass.fx")}},
                    {"section": "Effect@PSSM1", "visibility": {sky_id: False}},
                ]
                await call("mmd_write_effect_assignments", False, emm_path=str(output / "before.emm"),
                           output_path=str(output / "edited.emm"), sections=patches)
                await call("mmd_transfer_effect_assignments", operation="import", path=str(output / "edited.emm"))
                after = await call("mmd_transfer_effect_assignments", operation="export", path=str(output / "after.emm"))
                for patch in patches:
                    section = after["assignments"]["effect_sections"][patch["section"]]
                    for key, value in patch.get("assignments", {}).items():
                        actual = section["assignments"][key]
                        resolved = (executable.parent / actual).resolve() if not Path(actual).is_absolute() else Path(actual).resolve()
                        assert resolved == Path(value).resolve(), (key, actual, value)
                    for key, value in patch.get("visibility", {}).items():
                        assert section["visibility"].get(key) == value
                report["verified_sections"] = [patch["section"] for patch in patches]
                report["status"] = "passed"
                print(f"PASS RayMMD roundtrip: {output}", flush=True)
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--mmd-exe", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--ray-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.mmd_exe.resolve(), args.model.resolve(), args.ray_dir.resolve()))
