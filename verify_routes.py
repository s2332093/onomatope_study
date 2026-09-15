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

# ---- フェーズ1：語ごとの連鎖学習（全39語 × 5問） ----
CHAIN_FIGS = {
    "continuity": {"＋": "cont_plus.svg", "変化結果の＋": "result_plus.svg", "ー": "cont_minus.svg"},
    "action": {"高": "act_high.svg", "中": "act_mid.svg", "低": "act_low.svg"},
    "volition": {"＋": "vol_plus.svg", "ー": "vol_minus.svg", "関与しない": "vol_na.svg"},
}
FKEY_BY_K = {3: "continuity", 4: "action", 5: "volition"}

for w in WORDS:
    cat = CAT_BY_ID[w["category_id"]]
    phon = main.PHON_BY_KEY[w["phon"]]
    for k in range(1, 6):
        r = get(f'/phase1/word/{w["id"]}/{k}')
        # 正解を入力すると「正解です」になること
        correct = {1: w["id"], 2: w["phon"]}.get(k) or cat[FKEY_BY_K[k]]
        res = post(f'/phase1/word/{w["id"]}/{k}/check', {"choice": correct})
        if "正解です" not in res.text:
            fails.append(f'フェーズ1：{w["word"]} の第{k}問で、正解を入れても正解になりません')
        # 誤答でも落ちないこと
        wrong = {1: "iraira" if w["id"] != "iraira" else "hotto",
                 2: "qri" if w["phon"] != "qri" else "repeat"}.get(k)
        if wrong is None:
            wrong = [v for v in CHAIN_FIGS[FKEY_BY_K[k]] if v != cat[FKEY_BY_K[k]]][0]
        post(f'/phase1/word/{w["id"]}/{k}/check', {"choice": wrong})

        # 素性の問いは選択肢に図が出ていること（3枚とも）
        if k in FKEY_BY_K:
            for val, fig in CHAIN_FIGS[FKEY_BY_K[k]].items():
                if f'/static/{fig}' not in r.text:
                    fails.append(f'{w["word"]} 第{k}問：選択肢に図 {fig} がありません')
        # 第3問は音の形を踏まえた導入になっていること
        if k == 3 and phon["label"] not in r.text:
            fails.append(f'{w["word"]} 第3問：導入に音の形（{phon["label"]}）が出ていません')
        # 第4問は継続性の結果を踏まえた導入になっていること
        if k == 4 and main.val_label("continuity", cat["continuity"]) not in r.text:
            fails.append(f'{w["word"]} 第4問：導入に継続性の結果が出ていません')

    # まとめページ
    r = get(f'/phase1/word/{w["id"]}/done')
    if cat["name"] not in r.text:
        fails.append(f'{w["word"]} のまとめにカテゴリー名が出ていません')

# ---- 図のファイルが実在すること ----
import os
for fkey, m in CHAIN_FIGS.items():
    for val, fig in m.items():
        if not os.path.exists(os.path.join("static", fig)):
            fails.append(f"図が存在しません：static/{fig}")

# ---- 廃止したルートが残っていないこと ----
for path in ["/step1/iraira", "/step2/iraira", "/phase1/stage/1"]:
    if client.get(path).status_code == 200:
        fails.append(f"廃止したはずのページが残っています：{path}")

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

# ---- 全語 × Step3・Step4 ----
for w in WORDS:
    cat = CAT_BY_ID[w["category_id"]]

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
print(f"OK：全ルート・全{len(WORDS)}語の連鎖学習（5問）・Step3・Step4・両ドリルが正常に動作しました。")
print(f"    素性フィードバックは {len(WORDS) * len(EXPRESSIONS)} 通りすべて研究資料の正解表と一致。")
