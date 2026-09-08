# 編集用JSONとVMD

この経路は **新しく制作するボーン・表情のモーション** を扱う。既存PMMの全タイムラインを読み出して編集するAPIではない。読み込んだVMDもJSONへ逆変換しない。既存モーションへVMDを重ねると、ファイルにない古いキーは残るため、比較には同じ初期状態の検証シーンを使う。

`mmd_compile_pose(model_path, pose, frame)` の `bones` を `MotionDocument.bones` に組み込む。モデル名とSHA-256はプロファイルから取る。形式は次の通り。

```json
{
  "version": 1,
  "model_name": "Tda式初音ミクV4X",
  "model_sha256": "a3876a152b456d4d4e99b2b8fbb7d87c5308c0ad0c624b3163a7dc84dcbaca77",
  "fps": 30,
  "bones": [{
    "name": "左腕",
    "frame": 30,
    "position": {"x": 0, "y": 0, "z": 0},
    "rotation_degrees": {"x": 0, "y": 0, "z": -25},
    "interpolation": {
      "rotation": {"x1": 30, "y1": 0, "x2": 100, "y2": 127}
    }
  }],
  "morphs": [{"name": "にっこり", "frame": 30, "weight": 0.75}]
}
```

省略したボーンの位置・回転は0、補間チャンネルは線形相当の既定値になる。キーはそのボーンの完全な値。部分的なフィールドパッチではない。

回転角はMMDのボーン数値欄と同じ度数。VMDのQuaternionへの変換は `Ry(-y) Rx(x) Rz(-z)` で、通常のXYZ Eulerや全軸符号反転ではない。自作の変換式を別途混ぜない。カメラの角度へこの式を流用しない。

補間の `x` / `y` / `z` / `rotation` は、**そのキーに到着する区間** に適用される。制御点は0〜127、`x1 <= x2`。表情のVMDキーにはボーンと同じ補間曲線はない。

`mmd_edit_motion_document(document, edits)` は更新後のJSONを返す純粋操作。`upsert_bone` / `upsert_morph` は完全なキーを渡し、`delete_bone` / `delete_morph` は名前とフレームで削除する。移動は元キーの削除と新フレームへのupsertを一組にする。重複キーと存在しないキーの削除は拒否される。複数の編集が失敗しても元documentは変わらない。

`mmd_write_motion_document` で `kind="json"` または `kind="vmd"` を新しい絶対パスへ保存する。既存ファイルを上書きしない。VMD出力だけではMMDは変わらない。対象モデルを選び0フレームへ移動してから `mmd_load_file(kind="motion")` で独立して読み込む。

`mmd_preview_motion` は新しい出力ディレクトリ、開始／終了フレーム、step、HWND、`allow_frame_evaluation=true` を指定する。最大180サンプル、step 1〜30。step=3なら30fpsのモーションを10fpsで確認できる。成功時は元のフレームへ戻るが、未登録の編集は復元しない。異常時には勝手なフレーム復元をせず、生成済みファイルと現在状態を残す。

新しいTdaのシーンでAutoLuminousを使わない場合は「AL未使用」を1にして0フレームで登録し、保存したモーションにも必要な値を保持する。JSONのモデル名はVMDの20バイト、ボーン／表情名は15バイトのCP932制限を守る。長い名前を切り詰めて別の名前にしない。

既存ネイティブVMDのキー検査・補間変更は `mmd_inspect_vmd` / `mmd_edit_vmd` を使う。新規JSONを作る経路とは別で、元VMDと無関係なペイロードを保持できる。時間移動・削除の結果を反映するときは、VMD読込がマージである点に注意して古いライブキーを整理する。
