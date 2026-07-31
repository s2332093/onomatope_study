# database.py
# onomatopoeia.db から学習データを読み込むモジュール
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "onomatopoeia.db")


def _connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def load_all():
    """DBの全データを辞書構造にして返す"""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"{DB_PATH} が見つかりません。先に `python init_db.py` を実行してください。")

    con = _connect()
    cur = con.cursor()

    data = {}

    # 知識（section → rows）
    data["knowledge"] = {}
    for r in cur.execute("SELECT * FROM knowledge ORDER BY section, ord"):
        data["knowledge"].setdefault(r["section"], []).append(dict(r))

    # 音韻形態
    data["phon_defs"] = [dict(r) for r in cur.execute(
        "SELECT * FROM phon_forms ORDER BY ord")]
    data["phon_by_key"] = {p["key"]: p for p in data["phon_defs"]}

    # カテゴリー
    data["categories"] = [dict(r) for r in cur.execute(
        "SELECT * FROM categories ORDER BY ord")]
    data["cat_by_id"] = {c["id"]: c for c in data["categories"]}

    # 表現形式
    data["expressions"] = [dict(r) for r in cur.execute(
        "SELECT * FROM expressions ORDER BY ord")]

    # カテゴリー → 結びつく表現キー集合
    data["cat_exprs"] = {}
    for r in cur.execute("SELECT * FROM category_expression"):
        data["cat_exprs"].setdefault(r["category_id"], set()).add(r["expression_key"])

    # 単語
    data["words"] = [dict(r) for r in cur.execute(
        "SELECT w.* FROM words w JOIN categories c ON w.category_id = c.id ORDER BY c.ord, w.rowid")]
    data["word_by_id"] = {w["id"]: w for w in data["words"]}

    # 例文練習（カテゴリーごとに複数問）
    data["practice"] = {}
    by_pid = {}
    for r in cur.execute("SELECT * FROM practice ORDER BY category_id, ord"):
        q = {"frame": r["frame"], "explain": r["explain"], "options": []}
        data["practice"].setdefault(r["category_id"], []).append(q)
        by_pid[r["id"]] = q
    for r in cur.execute("SELECT * FROM practice_options ORDER BY practice_id, ord"):
        by_pid[r["practice_id"]]["options"].append({
            "label": r["label"], "meaning": r["meaning"], "correct": bool(r["correct"])})

    con.close()
    return data
