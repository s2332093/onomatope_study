# verify_routes.py  … 全ルートの動作確認（開発用。デプロイ不要）
import random
import sys

from fastapi.testclient import TestClient

import main
from main import app, WORDS, EXPRESSIONS, CAT_EXPRS, CAT_BY_ID, PRACTICE, EXPR_BY_KEY

client = TestClient(app)
fails = []


def get(path):
    r = client.get(path)
    if r.status_code != 200:
        fails.append(f"GET {path} -> {r.status_code}")
    return r


def post(path, data):
    r = client.post(path, data=data)
    if r.status_code != 200:
        fails.append(f"POST {path} -> {r.status_code}\n{r.text[:600]}")
    return r


# ---- 静的ページ ----
for p in ["/", "/phase1", "/phase1/summary", "/phase2", "/phase3",
          "/phase1/drill", "/phase2/drill"]:
    get(p)

# ---- フェーズ1：5段階の演習（各段階を複数回出題して採点） ----
import re as _re

for stage in main.STAGES:
    n = stage["n"]
    for attempt in range(15):
        get(f"/phase1/stage/{n}")
        r = get(f"/phase1/stage/{n}/practice")
        specs = _re.findall(r'name="spec_(\d+)" value="([^"]+)"', r.text)
        if len(specs) != 3:
            fails.append(f'段階{n}の問題数が {len(specs)} 問です（3問必要）')
            break
        data = {}
        for idx, spec in specs:
            data[f"spec_{idx}"] = spec
            kind = spec[0]
            # 段階の内容と出題タイプが合っているか
            if stage["key"] in ("continuity", "action", "volition"):
                if kind != "f" or not spec.endswith(stage["key"]):
                    fails.append(f'段階{n}（{stage["title"]}）に別の素性の問題が出ました：{spec}')
            elif stage["key"] == "phon" and kind not in ("p", "f"):
                fails.append(f'段階{n}に想定外の問題が出ました：{spec}')
            elif stage["key"] == "category" and kind not in ("S", "C"):
                fails.append(f'段階{n}に想定外の問題が出ました：{spec}')
            # 正解を投入する
            if kind == "f":
                _, wid, fkey = spec.split(":", 2)
                data[f"choice_{idx}"] = main.CAT_BY_ID[main.WORD_BY_ID[wid]["category_id"]][fkey]
            elif kind == "p":
                _, pkey, fkey = spec.split(":", 2)
                pred = main.PHON_BY_KEY[pkey][main.PRED_COL[fkey]]
                if not pred:
                    fails.append(f'予測できない素性が出題されました：{spec}')
                data[f"choice_{idx}"] = pred
            elif kind == "S":
                _, wid, fkey = spec.split(":", 2)
                tv = main.CAT_BY_ID[main.WORD_BY_ID[wid]["category_id"]][fkey]
                data[f"choice_{idx}"] = next(
                    w["id"] for w in WORDS
                    if w["id"] != wid and main.CAT_BY_ID[w["category_id"]][fkey] == tv)
            else:  # C
                cid = spec[2:]
                data[f"choice_{idx}"] = next(w["id"] for w in WORDS if w["category_id"] == cid)
        res = post(f"/phase1/stage/{n}/practice/check", data)
        if "全問正解" not in res.text:
            fails.append(f'段階{n}：正解を入力したのに全問正解になりません')
            break

# ---- 段階1〜3で、同じ答えばかりにならないか（素性値が2種類以上出るか） ----
for stage in main.STAGES[:3]:
    fkey = stage["key"]
    varied = 0
    for _ in range(20):
        qs = main.build_stage_questions(stage)
        vals = {main.CAT_BY_ID[q["word"]["category_id"]][fkey] for q in qs}
        if len(vals) >= 2:
            varied += 1
    if varied < 20:
        fails.append(f'段階{stage["n"]}：答えが1種類に偏る出題が {20 - varied} 回ありました')

# ---- 学習ページに必要な要素がそろっているか ----
for stage in main.STAGES:
    r = get(f'/phase1/stage/{stage["n"]}')
    for needle, what in [("判断のしかた", "判断手順チェックリスト"),
                         ("似ているのに違う語", "対比ペア"),
                         ("一緒に考えてみよう", "思考ガイド"),
                         ("練習に進む", "練習への導線")]:
        if needle not in r.text:
            fails.append(f'段階{stage["n"]}の学習ページに{what}がありません')
    # 学習ページには問題（回答フォーム）を置かない
    if 'name="choice_0"' in r.text:
        fails.append(f'段階{stage["n"]}の学習ページに練習問題が混ざっています')
    # 対比ペアが実際に値の違う組になっているか
    pairs = main.build_contrast_pairs(stage["key"])
    if len(pairs) < 2:
        fails.append(f'段階{stage["n"]}の対比ペアが少なすぎます')
    for pr in pairs:
        # 対比になっているか：表示される値、または種類（感情・感覚／動作）のどちらかが違うこと
        # （段階5の「いらいら／にこにこ」は素性が同じで種類だけが違う、という対比）
        same_value = pr["a"]["value"] == pr["b"]["value"]
        same_kind = pr["a"]["kind"] == pr["b"]["kind"]
        if same_value and same_kind:
            fails.append(f'段階{stage["n"]}の対比ペアが素性も種類も同じです：'
                         f'{pr["a"]["word"]["word"]}／{pr["b"]["word"]["word"]}')
        if same_value and pr["a"]["key"]:
            fails.append(f'段階{stage["n"]}：単一素性の対比なのに値が同じです：'
                         f'{pr["a"]["word"]["word"]}／{pr["b"]["word"]["word"]}')
    # 思考ガイドの手順と結論
    ex = main.build_worked_example(stage["key"])
    if not ex or len(ex["steps"]) < 3 or not ex["conclusion"]:
        fails.append(f'段階{stage["n"]}の思考ガイドが不足しています')

# ---- 「予測できない素性」が phon 問題に出ないこと ----
for _ in range(80):
    q = main._q_phon()
    pkey, fkey = q["spec"].split(":")[1], q["spec"].split(":")[2]
    if not main.PHON_BY_KEY[pkey][main.PRED_COL[fkey]]:
        fails.append(f"総合ドリルで予測できない素性が出題されました：{q['spec']}")

# ---- 素性ドリル：出題→採点（全タイプを踏むまで繰り返す） ----
seen = set()


def extract(html, name_prefix):
    import re
    return re.findall(r'name="' + name_prefix + r'(\d+)" value="([^"]+)"', html)


for attempt in range(60):
    r = client.get("/phase1/drill")
    specs = extract(r.text, "spec_")
    data = {}
    for idx, spec in specs:
        data[f"spec_{idx}"] = spec
        seen.add(spec[0])
        if spec[0] in ("f", "p"):
            # 素性値の選択肢から適当に1つ
            fkey = spec.split(":")[-1]
            opts = {"continuity": "＋", "action": "中", "volition": "ー"}[fkey]
            data[f"choice_{idx}"] = opts
        else:
            data[f"choice_{idx}"] = random.choice(WORDS)["id"]
    post("/phase1/drill/check", data)
    if seen >= {"f", "p", "S", "C"}:
        break
if seen < {"f", "p", "S", "C"}:
    fails.append(f"素性ドリルの全タイプが出題されませんでした：{seen}")

# ---- 前接条件ドリル ----
seen2 = set()
for attempt in range(60):
    r = client.get("/phase2/drill")
    specs = extract(r.text, "spec_")
    data = {}
    for idx, spec in specs:
        data[f"spec_{idx}"] = spec
        seen2.add(spec[0])
        if spec[0] == "x":
            data[f"choice_{idx}"] = EXPRESSIONS[0]["cond_text"]
        else:
            data[f"choice_{idx}"] = random.choice(WORDS)["id"]
    post("/phase2/drill/check", data)
    if seen2 >= {"x", "y"}:
        break
if seen2 < {"x", "y"}:
    fails.append(f"前接条件ドリルの全タイプが出題されませんでした：{seen2}")

# ---- 全語 × Step1〜Step4 ----
for w in WORDS:
    cat = CAT_BY_ID[w["category_id"]]
    get(f'/step1/{w["id"]}')
    post(f'/step1/{w["id"]}/check',
         {"meaning": w["id"], "phon": w["phon"], "kind": cat["kind"]})

    get(f'/step2/{w["id"]}')
    # 正解の素性
    r = post(f'/step2/{w["id"]}/check',
             {"continuity": cat["continuity"], "action": cat["action"], "volition": cat["volition"]})
    if "3/3 正解" not in r.text and "3/3" not in r.text:
        fails.append(f'Step2 正解入力が全問正解になりません：{w["word"]}')
    # 誤答も通ることを確認
    post(f'/step2/{w["id"]}/check',
         {"continuity": "ー", "action": "低", "volition": "関与しない"})

    get(f'/step3/{w["id"]}')
    # 正解の線結び
    data = {k: "○" for k in CAT_EXPRS[cat["id"]]}
    data["hint_level"] = "2"
    r = post(f'/step3/{w["id"]}/check', data)
    if f'{len(EXPRESSIONS)}/{len(EXPRESSIONS)} 正解' not in r.text:
        fails.append(f'Step3 正解入力が全問正解になりません：{w["word"]}')
    # 全部×でも動くか
    post(f'/step3/{w["id"]}/check', {"hint_level": "0"})

    get(f'/step4/{w["id"]}')
    qs = main.step4_build(w)
    data = {}
    for q in qs:
        data[f'opt_keys_{q["idx"]}'] = q["opt_keys"]
        data[f'choice_{q["idx"]}'] = q["correct_key"]
    r = post(f'/step4/{w["id"]}/check', data)
    if "全問正解" not in r.text:
        fails.append(f'Step4 正解入力が全問正解になりません：{w["word"]}')
    # 誤答を選んだ場合
    data2 = {}
    for q in qs:
        wrong = next((o["key"] for o in q["options"] if o["key"] != q["correct_key"]), q["correct_key"])
        data2[f'opt_keys_{q["idx"]}'] = q["opt_keys"]
        data2[f'choice_{q["idx"]}'] = wrong
    post(f'/step4/{w["id"]}/check', data2)

# ---- Step4：誤答選択肢が必ず「結びつかない形式」であること ----
for w in WORDS:
    ok_keys = CAT_EXPRS[w["category_id"]]
    for _ in range(10):
        for q in main.step4_build(w):
            for o in q["options"]:
                if o["key"] != q["correct_key"] and o["key"] in ok_keys:
                    fails.append(f'Step4 誤答に結びつく形式が混入：{w["word"]} / {o["key"]}')
        # 正解キーは必ず結びつく形式
        for q in main.step4_build(w):
            if q["correct_key"] not in ok_keys:
                fails.append(f'Step4 正解が結びつかない形式：{w["word"]} / {q["correct_key"]}')

# ---- フィードバックが「満たさない素性」を必ず名指しするか ----
for w in WORDS:
    cat = CAT_BY_ID[w["category_id"]]
    for e in EXPRESSIONS:
        fb = main.expr_feedback(w, cat, e)
        if not fb["ok"]:
            ng = [c for c in fb["checks"] if not c["ok"]]
            if not ng:
                fails.append(f'×なのに不足素性がありません：{w["word"]} × {e["label"]}')
            for c in ng:
                if c["name"] not in fb["headline"]:
                    fails.append(f'結論文に素性名がありません：{w["word"]} × {e["label"]} / {c["name"]}')
        # 判定が研究資料の正解表と一致するか
        expected = e["key"] in CAT_EXPRS[cat["id"]]
        if fb["ok"] != expected:
            fails.append(f'判定不一致：{w["word"]} × {e["label"]}')

print("=" * 60)
if fails:
    print(f"NG：{len(fails)} 件")
    for f in fails[:25]:
        print("  - " + f)
    sys.exit(1)
print(f"OK：全ルート・全{len(WORDS)}語の Step1〜Step4・両ドリルが正常に動作しました。")
print(f"    素性フィードバックは {len(WORDS) * len(EXPRESSIONS)} 通りすべて研究資料の正解表と一致。")
