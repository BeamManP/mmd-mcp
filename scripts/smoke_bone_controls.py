"""Opt-in live bone-edit exercise; use --apply with one bone selected in MMD.

Changes all six axes, captures the result, then restores the displayed starting
values. Restoring UI-rounded values is not a lossless scene rollback. Do not
change MMD's selection or edit fields while this check runs.
"""

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check():
    root = Path(__file__).resolve().parents[1]
    output = root / "captures"
    output.mkdir(exist_ok=True)
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "mmd_mcp.server"])
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()

            async def call(name, arguments=None):
                result = await session.call_tool(name, arguments or {})
                if result.isError:
                    raise RuntimeError(str(result.content))
                return result.structuredContent

            async def capture(name):
                result = await session.call_tool("mmd_capture_window", {})
                if result.isError:
                    raise RuntimeError(str(result.content))
                image = next(item for item in result.content if item.type == "image")
                (output / name).write_bytes(base64.b64decode(image.data, validate=True))

            before = await call("mmd_get_selected_bone_transform")
            ui_before = await call("mmd_get_ui_state")
            await capture("bone-smoke-before.png")
            requested = {
                "expected_bone_name": before["selected_bone_name"],
                "expected_bone_index": before["selected_bone_index"],
                "position": {axis: before["position"][axis] + delta
                             for axis, delta in {"x": 1, "y": 0.5, "z": -1}.items()},
                "rotation_degrees": {axis: before["rotation_degrees"][axis] + delta
                                     for axis, delta in {"x": 10, "y": 5, "z": -5}.items()},
            }
            applied = await call("mmd_batch_bone_keys", {"items": [{"frame": before["displayed_frame"], "register_key": False,
                                 "bones": [{"name": requested["expected_bone_name"], "position": requested["position"],
                                            "rotation_degrees": requested["rotation_degrees"]}]}]})
            try:
                assert applied["status"] == "completed" and applied["bone_keys"] == 1, applied
                assert not applied["saved_to_disk"]
                await call("mmd_select_bone", {"name": requested["expected_bone_name"]})
                after = await call("mmd_get_selected_bone_transform")
                applied["after"] = after
                for kind in ("position", "rotation_degrees"):
                    for axis, value in requested[kind].items():
                        assert abs(after[kind][axis] - value) <= 0.06, (kind, axis, after, requested)
                await capture("bone-smoke-applied.png")
                print("MCP: all six position/rotation fields applied and read back: OK")
            finally:
                current = await call("mmd_get_selected_bone_transform")
                if any(current[key] != before[key] for key in ("model_selector_index", "model_name", "displayed_frame", "selected_bone_name", "selected_bone_index", "selection_count")):
                    raise RuntimeError("MMD context changed; refusing automatic restoration.")
                if any(current[key] != applied["after"][key] for key in ("position", "rotation_degrees")):
                    raise RuntimeError("MMD fields changed after the test edit; refusing automatic restoration.")
                await call("mmd_batch_bone_keys", {"items": [{"frame": before["displayed_frame"], "register_key": False,
                           "bones": [{"name": before["selected_bone_name"], "position": before["position"],
                                      "rotation_degrees": before["rotation_degrees"]}]}]})
                await call("mmd_select_bone", {"name": before["selected_bone_name"]})
                restored = {"after": await call("mmd_get_selected_bone_transform")}
            for kind in ("position", "rotation_degrees"):
                assert restored["after"][kind] == before[kind], restored
            ui_after = await call("mmd_get_ui_state")
            for key in ("displayed_frame", "model_selector", "morph_panels", "ik_selector"):
                assert ui_after[key] == ui_before[key], key
            await capture("bone-smoke-restored.png")
            local = root / "local"
            local.mkdir(exist_ok=True)
            (local / "bone-smoke-report.json").write_text(
                json.dumps({"before": before, "applied": applied, "restored": restored}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("Displayed transforms restored; frame/model/morph/IK UI preserved: OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually exercise the selected bone and restore its displayed values")
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required because this check changes MMD's selected bone")
    asyncio.run(check())
