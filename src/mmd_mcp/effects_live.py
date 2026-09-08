"""Native MME settings export/import without reloading the PMM."""

from . import effects, native_dialogs as dialogs
from .file_operations import file_path, run_dialog_flow
from .scene_controls import mutation, context
from .ui_state import UIReader

TITLE = "エフェクトファイル割り当て"


def transfer(kind, path, overwrite=False, hwnd=None):
    output = kind == "export"
    candidate = file_path(path, {".emm"}, write=output, overwrite=overwrite)
    if not output:
        data = effects.read_emm(str(candidate))
        if not data["objects"]:
            raise ValueError("EMM contains no objects to import.")
    stamp = candidate.stat().st_mtime_ns if output and candidate.exists() else None
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        dialogs.menu_command(reader.target.hwnd, 40005)
        dialog = dialogs.wait_dialog(reader.target, TITLE)
        dialogs.menu_command(dialog["hwnd"], 40010 if output else 40009)
        result = run_dialog_flow(reader.target, candidate, overwrite=overwrite,
                                 parent_dialog=(dialog["hwnd"], dialog["title"]),
                                 probe=lambda: {"assignment_dialog_ready": True})
        if result["status"] == "completed":
            dialogs.close(reader.target, dialog, 1)
            if output:
                if (not candidate.is_file() or candidate.stat().st_size == 0
                        or (stamp is not None and candidate.stat().st_mtime_ns == stamp)):
                    result["status"] = "verification_failed"
                    result["note"] = "MME did not write a new nonempty assignment file."
                else:
                    result["assignments"] = effects.read_emm(str(candidate))
        return {"operation": kind, "path": str(candidate), **result,
                "applied_to_mmd": not output and result["status"] == "completed",
                "saved_to_disk": output and result["status"] == "completed",
                "note_on_import": "MME matches loaded objects itself. Export again to verify assignments; unknown confirmation/error dialogs remain open."}
