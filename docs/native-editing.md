# ネイティブ編集・出力（v0.3.0）

対象は日本語版MMD 9.32 x64。各例のパスとHWNDは実際の対象へ置き換える。
バッチで登録する値、現在の選択へ作用するコマンド、ディスク上のファイル編集を区別する。
成功以外の応答では、適用済み内容とダイアログを確認してから再開する。

## 表示・物理・再生

```text
mmd_get_scene_settings {}
mmd_set_scene_settings {"settings":{"axis":false,"ground_shadow":false,"antialiasing":false,"physics_mode":"on_off","fps_limit":"60"}}
mmd_output_size {"size":{"width":1920,"height":1080}}
mmd_select_model {"selector_index":0}
mmd_batch_camera_keys {"items":[{"frame":0,"shadow":{"mode":2,"distance":8000},"gravity":{"acceleration":9.8,"x":0,"y":-1,"z":0,"noise":false}}]}
mmd_set_playback {"options":{"start_frame":0,"end_frame":120,"repeat":true},"playing":true}
mmd_set_playback {"playing":false}
```

`mmd_set_scene_settings` はトグル命令ではなく指定値への変更。変更済みなら再度反転しない。
素材未読込の背景表示ONなど、MMDが反映しない値は読み戻し不一致になる。
物理モードは `on_off` / `always` / `trace` / `off`。
セルフ影モードは0=影なし、1=モード1、2=モード2。
重力の `noise_amount` はノイズON時だけ設定できる。

再生オプションの変更は停止中に行う。短い範囲は応答までに再生が終わる場合がある。
描画の経過と数値欄の表示フレームは同時更新とは限らない。

## モデル・描画順

`mmd_model_order(kind="draw" / "compute")` が返す `names` を保存する。
変更時は `expected_names` にその全リストを渡し、`order` へ0始まりの完全な順列を指定する。
たとえば `[2,0,1]` は元の3番目を先頭にする。モデル選択インデックスとは別の番号。
並べ替え後はモデル一覧とアクセサリ親の選択欄を取得し直す。

`mmd_set_render_style` の `edge_width` / `edge_color` は選択中モデルを対象にする。
`ground_shadow_brightness` は地面影の明るさ。これらはキーではなく設定値。

モデル削除は `mmd_delete_models(targets=[{"selector_index":1,"expected_name":"初音ミク"}])`。
モデルのキーも削除され、追従アクセサリは地面へ移る。元に戻せない。
`mmd_new_project(discard_current=true)` は現在の未保存シーンを破棄する。

## キー選択と編集

```text
mmd_get_timeline_context {}
mmd_select_key_range {"start_frame":10,"end_frame":20,"track_name":"カメラ"}
mmd_edit_actions {"actions":["copy_keys"]}
mmd_set_frame {"frame":40}
mmd_edit_actions {"actions":["paste_keys"]}
```

トラック名は `range_tracks.items` の文字列をそのまま使う。
モデルモードではボーン名・表情名・全ボーン等、カメラモードではカメラ・照明・影・重力等が並ぶ。
選択されたキーの識別子を直接読み出す機能はないため、重要な編集はVMD出力で確認する。

`mmd_edit_actions` は1～64個の名前付き操作を順に実行する。

| 操作群 | action |
|---|---|
| キー全選択 | `select_bone_keys`, `select_morph_keys`, `select_model_flag_keys`, `select_camera_keys`, `select_light_keys`, `select_shadow_keys`, `select_gravity_keys`, `select_accessory_keys` |
| 現フレーム列選択 | `select_column_keys` |
| キー編集 | `copy_keys`, `paste_keys`, `mirror_paste_keys`, `delete_keys` |
| 列編集 | `insert_bone_camera_frame`, `delete_bone_camera_column`, `insert_morph_light_frame`, `delete_morph_light_column` |
| ボーン選択・編集 | `select_all_bones`, `select_unregistered_bones`, `reset_bones`, `copy_bones`, `paste_bones`, `mirror_paste_bones` |
| 表情 | `reset_morphs`, `register_all_morphs`, `delete_lip_keys`, `delete_eye_keys`, `delete_eyebrow_keys` |
| カメラ・照明 | `reset_camera`, `reset_light`, `view_front`, `view_back`, `view_top`, `view_left`, `view_right`, `view_camera`, `camera_follow_selected` |
| 物理・再読込 | `select_physics_bones`, `select_physics_keys`, `reset_rigid_bodies`, `refresh_effects`, `reload_textures` |
| 補間UI | `copy_interpolation`, `paste_interpolation`, `linear_interpolation` |
| 取り消し | `undo`, `redo` |

利用できないボタンは実行しない。特にカメラのキー操作・モデル削除・表情変更などではMMDのUndoを当てにしない。
任意のメニューIDやWin32メッセージは受け付けない。

`mmd_transform_timeline(spec=...)` はダイアログを伴う操作。

| operation | 主な値と対象 |
|---|---|
| `scale_time` | 選択中モデルの `start_frame`, `end_frame`, `factor`, `tracks`（`bones`, `morphs`, `model_flags`）。カメラ等はVMDファイル編集を使う |
| `bone_correction` / `camera_correction` | 選択キーの `position_scale`, `position_offset`, `rotation_scale`, `rotation_offset_degrees`。XYZ辞書。カメラは距離・画角のscale/offsetも可 |
| `morph_correction` | 選択表情キーの `weight_scale`, `weight_offset` |
| `center_bias` | `position_offset` のXYZ |
| `random_blink` | `start_frame`, `end_frame`。MMD自身のランダム登録 |
| `lip_shift` | `shift_frames` |
| `physics_state` | 選択された物理影響ボーンのキーを `physics_enabled` に変換 |

ボーンの「物理」チェックは `mmd_batch_bone_keys` の各 `bones` に `physics` を指定できる。
キー登録の有無は通常どおりフレーム項目の `register_key` で制御する。

## VMD検査と補間編集

1. 対象モデル、またはカメラモードを選ぶ。
2. `select_*_keys` または範囲選択を行う。
3. `mmd_export_file(kind="motion", path=...)` で選択キーを保存する。
4. `mmd_inspect_vmd` でキー・値・補間を検査する。`next_offset` があれば次ページを読む。
5. `mmd_edit_vmd` で別の新規VMDへ編集する。
6. MMDの0フレームへ移動し、必要な対象範囲を整理して読み込む。

```json
{
  "source_path":"C:/Work/original.vmd",
  "output_path":"C:/Work/curves.vmd",
  "edits":[{
    "action":"interpolation","track":"bones","names":["左腕"],
    "start_frame":20,"end_frame":20,
    "curves":{"rotation":{"x1":10,"y1":5,"x2":90,"y2":120}}
  }]
}
```

補間は到着側のキーに設定する。カメラは `x,y,z,rotation,distance,fov`。
ネイティブの物理フラグや未編集レコードを保持する。
同じツールの `shift` / `scale_time` / `delete` は時刻変更・削除。衝突や対象ゼロは出力前に拒否する。

**VMD読込はマージ**のため、削除・時刻変更の結果を読むだけでは古いキーが残る。
その場合は対応するライブのキー範囲を削除してから読み込む。補間だけの変更なら同じキーを上書きできる。
VMDのカメラ距離・角度・セルフ影距離は保存形式の値であり、UI値へ一律変換しない。
アクセサリ・重力・外部親等の完全な保持にはPMMを使う。

## 画像・動画

`mmd_export_file(kind="image")` はMMDの画像出力。`mmd_capture_window` はUIを含む画面キャプチャ。
`kind="pose"` はVPD、`kind="motion"` は選択キーのVMD。

```text
mmd_output_size {"size":{"width":1280,"height":720}}
mmd_export_video {"path":"C:/Work/movie.avi","options":{"start_frame":0,"end_frame":120,"fps":30,"codec":"未圧縮","include_audio":false}}
mmd_get_video_export_status {"job_id":"返されたID"}
```

コーデック名はインストール済み一覧と完全一致。未対応名の場合は一覧を返す。
独自コーデックの「詳細設定」は操作しない。音声出力にはWAVを先に読み込む。
`rendering` の間は同じサーバーで完了を確認し、MMDを閉じたり別の編集を始めたりしない。
完了判定には出力ファイルのロック解除と映像ストリーム情報を使う。
ジョブIDはサーバー再起動後には利用できない。

## MME

`mmd_transfer_effect_assignments` で `export` → ファイル編集 → `import` → 再`export`の順に使う。
RayMMDでは先にray.xやSkyboxを読み込んでオフスクリーンを作り、現在のEMMを保存する。
オブジェクトIDはUI番号と異なるためファイルパスと対応させる。詳細は [effects.md](effects.md)。
