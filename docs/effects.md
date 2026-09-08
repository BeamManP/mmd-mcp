# MME割当ファイルの編集

`mmd_read_effect_assignments` と `mmd_write_effect_assignments` は、保存されたEMMファイルを扱います。Mainだけでなく、RayMMDのEnvLightMap・MaterialMap・PSSM等の複数セクションを1回で編集できます。MMDの画面・フレーム・PMMは変更しません。

## 現在の割当を取得する

MMEの「エフェクト割当」ダイアログ内の「ファイル → 設定を保存」でEMMを出力します。これはPMM保存・シーン再読み込みとは別の操作です。「割当ファイル自動保存」が有効ならPMM保存時にも隣接EMMが生成されますが、以前のEMMには現在の変更が含まれていない場合があります。

```text
mmd_read_effect_assignments {"emm_path":"C:/MyProject/scene.emm"}
```

返却値の使い分け:

| フィールド | 内容 |
| --- | --- |
| `objects` | EMM内のオブジェクトIDとモデル／アクセサリのパス |
| `effect_sections` | セクション名ごとの`owner`・`default`・`assignments`・`visibility` |
| `effects` | 互換性維持用のMain（`Effect`）の値。`.show`等も含む旧形式 |
| `sections` | その他のセクションも含む、生のキーと文字列値 |

**EMMのIDはMMDのUI選択インデックスではありません。** `objects` のパスから対応を確認します。再読み込み・追加・描画順変更をまたいでIDを流用しません。`Effect` がMain、`Effect@EnvLightMap` 等がオフスクリーンの割当です。セクション名も読み取り結果をそのまま使います。

`assignments` と `visibility` は明示的に保存された値だけです。ワイルドカードを含む`Default`や、省略された表示設定を展開した実効値ではありません。

## 複数セクションを編集する

以下は`objects`に`Pmd2`=Skybox、`Pmd3`=ステージ、`Pmd4`=キャラクターがある場合の例です。対象のファイルと材質番号は実際のシーンに合わせます。

```json
{
  "emm_path": "C:/MyProject/scene.emm",
  "output_path": "C:/MyProject/scene-ray.emm",
  "sections": [
    {
      "section": "Effect@EnvLightMap",
      "assignments": {
        "Pmd2": "UserFile/MME/ray-mmd-1.5.2/Skybox/Sky Hemisphere/Sky with lighting.fx"
      },
      "visibility": {"Pmd2": true}
    },
    {
      "section": "Effect@MaterialMap",
      "assignments": {
        "Pmd4[0]": "UserFile/MME/ray-mmd-1.5.2/Materials/material_2.0.fx"
      }
    },
    {
      "section": "Effect@PSSM1",
      "visibility": {"Pmd3": false}
    }
  ]
}
```

この引数を`mmd_write_effect_assignments`へ渡します。既存のMain用`assignments`引数も使えます。`sections`に`Effect`を指定する場合はトップレベルの`assignments`と併用せず、1セクションの変更を1項目にまとめます。

- 材質単位はMMEの実際の形式`Pmd4[0]`（0始まり）です。旧APIの`Pmd4.0`入力は互換用に受け付けますが、書き出しと変更結果のキーは角括弧へ正規化します。EMMだけではモデルの材質数を検証できません。
- 割当に`null`を渡すと`none`になります。非表示とは別で、非表示には`visibility: {"Pmd4[0]": false}`を指定します。`.show`はAPI側で付加するため、入力キーに書きません。
- 相対パスは通常MMDフォルダ基準です。EMMの保存先基準には変換しません。絶対パスはファイルの存在を確認します。拡張子は`.fx`・`.fxsub`・`.fxm`です。
- オフスクリーンのセクションは、対応エフェクトをMMDへ読み込んだ後に出力したEMMに存在するものだけ編集できます。存在しないセクションを推測して新設しません。
- `Owner`・`Default`・`Object`は編集対象外で、そのまま保持します。指定のない割当、別セクション、コメント、改行、CP932の元バイトも保持します。
- 全項目を検証してから書き込みます。無効なオブジェクト、重複セクション、曖昧な重複キー、不正なパス・型等があればファイルは変更しません。
- `output_path`は新規EMM専用です。省略時は入力ファイルを更新します。入力ファイルの更新は一時ファイルを使い、置き換えに失敗しても元を切り詰めません。MMDからの保存と同時には実行しません。

結果はセクション別の`changed_sections`と`applied_to_mmd: false`を返します。従来の`changed`にはMainの割当変更だけを返します。

## MMDへ反映する

EMMを書き換えるだけでは画面は変わりません。MMEの「エフェクト割当」ダイアログ内の「ファイル → 設定を読込」で編集したEMMを読み込みます。この手順はPMMの再読み込みを伴いません。現在のシーンとオブジェクトの対応が一致するEMMを使います。

隣接する同名PMMを再読み込みする方法もありますが、その場合はシーンが置き換わります。EMM編集後に先にPMMを保存すると、自動保存によってEMMが現在の割当で上書きされることがあります。

v0.3.0では `mmd_transfer_effect_assignments` でこの手順を実行できます。

```text
mmd_transfer_effect_assignments {"operation":"export","path":"C:/Work/current.emm"}
mmd_write_effect_assignments {"emm_path":"C:/Work/current.emm","output_path":"C:/Work/edited.emm","sections":[{"section":"Effect@PSSM1","visibility":{"Pmd2":false}}]}
mmd_transfer_effect_assignments {"operation":"import","path":"C:/Work/edited.emm"}
mmd_transfer_effect_assignments {"operation":"export","path":"C:/Work/readback.emm"}
```

最後に再保存したEMMを読み、指定したパス・材質・表示状態を照合します。
読み込みはMME自身のオブジェクト照合を利用するため、別シーンからのEMMを無条件に流用しません。
シェーダーのコンパイル中は既送信の読込を再実行せず、制限時間内で観測だけを再試行します。
タイムアウトや未知のダイアログは成功扱いせず、状態を残します。
