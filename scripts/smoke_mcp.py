"""Opt-in live check: python scripts/smoke_mcp.py [--capture]."""

import argparse
import asyncio
import base64
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(capture: bool, state: bool = False, bones: bool = False, hwnd: int | None = None):
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "mmd_mcp.server"])
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "mmd_list_windows", "mmd_capture_window", "mmd_list_models", "mmd_get_ui_state",
                "mmd_get_selected_bone_transform", "mmd_list_bones",
                "mmd_select_model", "mmd_select_bone", "mmd_get_camera",
                "mmd_get_light", "mmd_set_frame",
                "mmd_get_dialogs", "mmd_load_file", "mmd_save_project",
                "mmd_get_model_profile", "mmd_compile_pose", "mmd_batch_bone_keys", "mmd_batch_model_flags", "mmd_batch_camera_keys", "mmd_read_effect_assignments", "mmd_write_effect_assignments",
                "mmd_read_motion_document", "mmd_edit_motion_document", "mmd_write_motion_document",
                "mmd_preview_motion", "mmd_list_accessories", "mmd_select_accessory",
                "mmd_get_accessory", "mmd_batch_accessories", "mmd_delete_accessories",
                "mmd_get_scene_settings", "mmd_set_scene_settings", "mmd_transfer_effect_assignments",
                "mmd_edit_actions", "mmd_export_file", "mmd_output_size", "mmd_model_order", "mmd_get_gravity",
                "mmd_export_video", "mmd_get_video_export_status", "mmd_inspect_vmd", "mmd_edit_vmd",
                "mmd_get_playback", "mmd_set_playback", "mmd_get_timeline_context", "mmd_select_key_range",
                "mmd_new_project", "mmd_delete_models", "mmd_transform_timeline", "mmd_set_render_style",
            }
            target = {"hwnd": hwnd} if hwnd is not None else {}
            windows = await session.call_tool("mmd_list_windows", {})
            assert not windows.isError, windows
            print("MCP initialization, tool discovery, window listing: OK")
            invalid = await session.call_tool("mmd_capture_window", {"hwnd": -1})
            assert invalid.isError, "An invalid HWND should fail without capturing another window"
            print("Invalid HWND error: OK")
            document = {"model_name": "fixture", "model_sha256": "a"*64, "bones": []}
            result = await session.call_tool("mmd_edit_motion_document", {"document": document,
                "edits": [{"action": "upsert_bone", "name": "bone", "frame": 30,
                           "bone": {"name": "bone", "frame": 30, "rotation_degrees": {"z": 25}}}]})
            assert not result.isError and result.structuredContent['bones'][0]['frame'] == 30, result
            invalid = await session.call_tool('mmd_edit_motion_document', {'document': document,
                'edits': [{'action': 'delete_bone', 'name': 'missing', 'frame': 0}]})
            assert invalid.isError, invalid
            print('Authoring schema, key edit and missing-key refusal: OK')
            # Exercise nested EMM patches through the actual MCP schema, without touching MMD.
            with tempfile.TemporaryDirectory() as directory:
                emm = Path(directory) / 'scene.emm'
                emm.write_bytes(b'[Info]\r\nVersion = 3\r\n[Object]\r\nAcs1 = ray.x\r\n'
                                b'Pmd2 = sky.pmx\r\n[Effect]\r\nPmd2 = sky.fx\r\n'
                                b'[Effect@EnvLightMap]\r\nOwner = Acs1\r\nPmd2 = none\r\n')
                edited = Path(directory) / 'edited.emm'
                result = await session.call_tool('mmd_write_effect_assignments', {
                    'emm_path': str(emm), 'output_path': str(edited),
                    'sections': [{'section': 'Effect@EnvLightMap',
                                  'assignments': {'Pmd2[0]': 'sky_lighting.fx'},
                                  'visibility': {'Pmd2[0]': True}}],
                })
                assert not result.isError, result
                assert result.structuredContent['applied_to_mmd'] is False
                result = await session.call_tool('mmd_read_effect_assignments', {'emm_path': str(edited)})
                assert not result.isError, result
                env = result.structuredContent['effect_sections']['Effect@EnvLightMap']
                assert env['owner'] == 'Acs1' and env['visibility']['Pmd2[0]'] is True
                assert env['assignments']['Pmd2[0]'] == 'sky_lighting.fx'
                assert b'Pmd2[0]' not in emm.read_bytes()
                invalid = await session.call_tool('mmd_write_effect_assignments', {
                    'emm_path': str(edited),
                    'sections': [{'section': 'Effect@EnvLightMap', 'visibility': {'Pmd2': 'false'}}],
                })
                assert invalid.isError, invalid
            print('EMM offscreen section/subset edit, visibility, source protection and schema: OK')
            if state:
                for name in ("mmd_list_models", "mmd_get_ui_state"):
                    result = await session.call_tool(name, target)
                    assert not result.isError, result
                    assert result.structuredContent and result.structuredContent["source"] == "win32_ui"
                    print(f"{name}: OK")
            if bones:
                result = await session.call_tool("mmd_list_bones", target)
                assert not result.isError, result
                data = result.structuredContent
                assert data and data["bone_count"] == len(data["bones"])
                if data["selected_bone_index"] is not None:
                    assert data["bones"][data["selected_bone_index"]]["name"] == data["selected_bone_name"]
                print(f"mmd_list_bones: OK ({data['bone_count']} bones, selected index {data['selected_bone_index']})")
            if capture:
                # Repeat after a failed request to check that the service remains usable.
                result = await session.call_tool("mmd_capture_window", target)
                assert not result.isError, result
                images = [item for item in result.content if item.type == "image"]
                assert len(images) == 1 and images[0].mimeType == "image/png"
                data = base64.b64decode(images[0].data, validate=True)
                assert data.startswith(b"\x89PNG\r\n\x1a\n")
                output = Path(__file__).resolve().parents[1] / "captures"
                output.mkdir(exist_ok=True)
                (output / "mcp-smoke.png").write_bytes(data)
                print(f"MCP PNG response: OK ({len(data)} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Capture the single open MMD window")
    parser.add_argument("--state", action="store_true", help="Read the single open MMD's UI state")
    parser.add_argument("--bones", action="store_true", help="Read bones from the verified MMD executable")
    parser.add_argument("--hwnd", type=int, help="Explicit MMD window when multiple instances exist")
    args = parser.parse_args()
    asyncio.run(check(args.capture, args.state, args.bones, args.hwnd))
