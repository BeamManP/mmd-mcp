"""Exact Japanese/English labels for the verified MMD 9.32 executable.

Windows common dialogs follow the OS language independently of MMD's mode.
Unknown translations are deliberately not accepted.
"""

# Native spelling/capitalization (including typos) is intentional.
LABELS = {
    "カメラ編": ("camera", "To camera"), "モデル編": "To model", "全ボーンﾌﾚｰﾑ": "All bone",
    "新規作成": ("new", "delete lip frame"), "モデル削除": "model delete", "アクセサリ削除": "delete accessory",
    "モーションデータ読込": "load motion data", "ポーズデータ読込": "load pose data",
    "モーションデータ保存": "save motion data", "ポーズデータ保存": "save pose data",
    "画像ファイル出力": "render to picture file", "WAVE Fileを開く": "open WAVE File",
    "背景画像データ読込": "load picture data", "AVIデータ読込": "load AVI file",
    "AVI出力": "output AVI file", "ファイルを開く": "open file data",
    "開く": "open file",
    "モデル情報": "model infomation",
    "名前を付けて保存の確認": "Confirm Save As", "はい(&Y)": "&Yes",
    "色の設定": "Color", "リップフレーム削除": "delete lip frame",
    "エッジ太さ設定": "thickness of edge line", "地面影色設定": "ground shadow color",
    "出力画面サイズ変更": "screen size", "モデル描画順設定": "model disply order",
    "モデル計算順設定": "model calculate order", "重力設定": "gravity setting",
    "ﾎﾞｰﾝﾌﾚｰﾑ位置角度補正": "multiply of bone position-angle",
    "ｶﾒﾗﾌﾚｰﾑ位置角度補正": "multiply of camera frame position-angle",
    "表情大きさ補正": "multiply of facial expression ", "バイアス付加": "apply center position bias",
    "まばたき登録": "register blinking", "シフトするﾌﾚｰﾑ数": "frame number to shift",
    "物理ON/OFFフレーム変換": "change physics ON/OFF frame",
    "AVI出力設定": "AVI-out",
    "時間拡大(縮小)率": "expand/shrink",
    "エフェクトファイル割り当て": "Map Effect File",
    "外部親設定": "outside parent(OP) setting",
}


def matches(actual, japanese):
    return actual in variants([japanese])


def variants(labels):
    result = set(labels)
    for label in labels:
        translated = LABELS.get(label, ())
        result.update((translated,) if isinstance(translated, str) else translated)
    return result


def english_mode(reader):
    label = reader.text(reader.control(536, "Button"))
    if label in {"camera", "To camera", "To model"}:
        return True
    if label in {"カメラ編", "モデル編"}:
        return False
    raise ValueError("Unsupported MMD UI language or editing mode.")
