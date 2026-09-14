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
    data["expr_by_key"] = {e["key"]: e for e in data["expressions"]}

    # 局面グループ → 表現形式
    data["expr_groups"] = []
    for e in data["expressions"]:
        if not data["expr_groups"] or data["expr_groups"][-1]["name"] != e["grp"]:
            data["expr_groups"].append({"name": e["grp"], "exprs": []})
        data["expr_groups"][-1]["exprs"].append(e)

    # カテゴリー → 結びつく表現キー集合（研究資料由来の正解表）
    data["cat_exprs"] = {}
    for r in cur.execute("SELECT * FROM category_expression"):
        data["cat_exprs"].setdefault(r["category_id"], set()).add(r["expression_key"])

    # 単語
    data["words"] = [dict(r) for r in cur.execute(
        "SELECT w.* FROM words w JOIN categories c ON w.category_id = c.id ORDER BY c.ord, w.rowid")]
    data["word_by_id"] = {w["id"]: w for w in data["words"]}

    # 例文練習（語ごとに2問）
    data["practice"] = {}
    for r in cur.execute("SELECT * FROM practice ORDER BY word_id, ord"):
        data["practice"].setdefault(r["word_id"], []).append(dict(r))

    # フェーズ1の学習コンテンツ（段階ごと）
    data["stage_guides"] = {}
    for r in cur.execute("SELECT * FROM stage_guides ORDER BY stage, ord"):
        data["stage_guides"].setdefault(r["stage"], []).append(dict(r))

    data["contrast_pairs"] = {}
    for r in cur.execute("SELECT * FROM contrast_pairs ORDER BY stage, ord"):
        data["contrast_pairs"].setdefault(r["stage"], []).append(dict(r))

    data["worked_examples"] = {r["stage"]: dict(r)
                               for r in cur.execute("SELECT * FROM worked_examples")}
    data["worked_steps"] = {}
    for r in cur.execute("SELECT * FROM worked_steps ORDER BY stage, ord"):
        data["worked_steps"].setdefault(r["stage"], []).append(dict(r))

    con.close()
    return data
