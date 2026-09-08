# 開発者向け：検証・配布ビルド

mmd-mcpのコードを変更する人向けの手順です。通常利用の導入手順は [日本語README](../README.md#導入) / [English README](../README.en.md#installation) を参照してください。以下の検証やパッケージ作成は、通常利用には必要ありません。

ソースからの導入とDLLビルドを済ませ、リポジトリのルートで実行します。実機検証にはMMDとモデルを別途用意し、例のパスを実際の配置先に変更してください。

## 検証とパッケージ作成

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/smoke_mcp.py
.\.venv\Scripts\python.exe scripts/build_package.py
```

総合実機検証はスクリプト自身が別MMDを起動して編集・終了します。既存のMMDは操作しません。

```powershell
.\.venv\Scripts\python.exe scripts/smoke_scene.py --apply --mmd-exe "C:/MMD/MikuMikuDance.exe" --model "C:/MMD/UserFile/Model/初音ミク.pmd"
```

テストには「左腕」と「まばたき」を持つ初音ミクを利用します。モデルは同梱しません。検証用PMM・PNG・JSONは `local/scene-smoke-*` に保存されます。

追加の総合テストは `scripts/smoke_release.py --apply --mmd-exe ... --model ... --second-model ...`、RayMMDの割当往復は `scripts/smoke_ray.py --apply --mmd-exe ... --model ... --ray-dir ...` です。

English Modeを検証する場合は、`scripts/smoke_scene.py`、`scripts/smoke_release.py`、`scripts/smoke_editing.py` に `--english` を付けます。

`build_package.py` は配布用パッケージを作るためのコマンドです。ビルド済みwheelの公開はMicrosoft製部分の配布条件確認が終わるまで保留です。[第三者ライセンスの説明](../THIRD_PARTY_NOTICES.md) を参照してください。MMD本体や第三者モデルを配布する権利は含みません。

## English notes

These commands are for contributors changing mmd-mcp, not required steps for ordinary use. Complete the source installation and native DLL build first, then run commands from the repository root.

- `unittest discover` runs automated tests; `scripts/smoke_mcp.py` checks MCP connectivity and tool discovery.
- `scripts/build_package.py` creates distribution packages. Publishing prebuilt wheels remains on hold pending the Microsoft runtime redistribution review linked above.
- Live smoke scripts launch, edit, and terminate their own MMD process, leaving existing MMD instances alone. Supply your own MMD and model files and replace the example paths. The Miku test model needs the original bone `左腕` and morph `まばたき`.
- Live artifacts are saved under `local/`; the scene smoke uses `local/scene-smoke-*`.
- Use `--english` with `scripts/smoke_scene.py`, `scripts/smoke_release.py`, and `scripts/smoke_editing.py` to exercise English Mode. The additional release and Ray-MMD checks use the arguments listed above.

No MMD or third-party model distribution rights are implied.
