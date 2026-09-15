# main.py
# オノマトペ学習支援システム
#   フェーズ1：語ごとの連鎖学習（/phase1/word/{id}/1〜5）
#             意味 → 音の形 → 継続性 → 動作性 → 意志性 を1語でたどる
#             ＋ 総合ドリル（/phase1/drill）＋ まとめ（/phase1/summary）
#   フェーズ2：文法形式の学習（/phase2）＋ 前接条件ドリル（/phase2/drill）
#             ＋ 線結び（/step3/{id}）
#   フェーズ3：例文への適用（/phase3）＋ 例文練習（/step4/{id}）
#
# 2026-09 改修の中心：
#   表現形式の前接条件を素性の集合として持ち、○×の判定と誤答フィードバックを
#   「どの素性が条件を満たさないか」から自動生成する（feedback engine）。
import random
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import init_db
from database import load_all

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---- 起動時：DB が無い／古ければ作り直してから読み込む ----
#   init_db.py の学習データを直して onomatopoeia.db を更新し忘れても、
#   ここで指紋が食い違うので自動的に作り直される。
#   そのとき研究資料との整合性チェック（80セル照合など）も必ず走り、
#   一致しなければ起動が止まる＝デプロイが失敗する。
init_db.ensure_current()

DB = load_all()

WORDS        = DB["words"]
WORD_BY_ID   = DB["word_by_id"]
CATEGORIES   = DB["categories"]
CAT_BY_ID    = DB["cat_by_id"]
EXPRESSIONS  = DB["expressions"]
EXPR_BY_KEY  = DB["expr_by_key"]
EXPR_GROUPS  = DB["expr_groups"]
CAT_EXPRS    = DB["cat_exprs"]
PHON_DEFS    = DB["phon_defs"]
PHON_BY_KEY  = DB["phon_by_key"]
KNOWLEDGE    = DB["knowledge"]
PRACTICE     = DB["practice"]
STAGE_GUIDES    = DB["stage_guides"]
CONTRAST_PAIRS  = DB["contrast_pairs"]
WORKED_EXAMPLES = DB["worked_examples"]
WORKED_STEPS    = DB["worked_steps"]

# =====================================================================
#  素性のラベル表示
# =====================================================================
FEATURE_NAME = {"continuity": "継続性", "action": "動作性", "volition": "意志性"}

CONT_LABEL = {"＋": "＋継続性", "変化結果の＋": "＋変化結果の継続性", "ー": "ー継続性"}
VOL_LABEL  = {"＋": "＋意志性", "ー": "ー意志性", "関与しない": "意志性は関与しない"}


def val_label(fkey: str, value: str) -> str:
    """素性値を学習者向けの表記にする"""
    if fkey == "continuity":
        return CONT_LABEL.get(value, value)
    if fkey == "action":
        return f"動作性（{value}）"
    return VOL_LABEL.get(value, value)


def req_label(fkey: str, allowed) -> str:
    """前接条件（許容値のリスト）を学習者向けの表記にする"""
    if fkey == "continuity":
        return " または ".join(CONT_LABEL.get(v, v) for v in allowed)
    if fkey == "action":
        return "動作性（" + "・".join(allowed) + "）"
    if set(allowed) == {"ー", "関与しない"}:
        return "意志的でないこと（ー意志性／関与しない）"
    return " または ".join(VOL_LABEL.get(v, v) for v in allowed)


# 素性ごとの一般的な考え方（ドリル・Step2 の解説で使用）
FEATURE_EXPLAINS = {
    "continuity": "継続性は図のイメージで判断します（＋：続く／変化結果の＋：変化後の結果が残る／ー：一瞬）。",
    "action": "継続性が低いほど動作性は高くなります（ー継続性→高、続く状態→中、だらけた状態→低）。",
    "volition": "自分の意志で行える動き・行為なら「＋」、感情・感覚など自然に起こるものは「ー」、状況に反応して起こる動きは「関与しない」です。",
}

WHY_COL = {"continuity": "why_cont", "action": "why_act", "volition": "why_vol"}
REQ_COL = {"continuity": "req_cont", "action": "req_act", "volition": "req_vol"}
PRED_COL = {"continuity": "pred_cont", "action": "pred_act"}

# Step2 の3素性の選択肢
FEATURE_DEFS = [
    {"key": "continuity", "name": "継続性",
     "desc": "状態・動作が時間幅をもって続くか（図を参考に）",
     "options": ["＋", "変化結果の＋", "ー"]},
    {"key": "action", "name": "動作性",
     "desc": "動き・行為としての強さ",
     "options": ["高", "中", "低"]},
    {"key": "volition", "name": "意志性",
     "desc": "自分の意志で行えるか",
     "options": ["＋", "ー", "関与しない"]},
]


def profile_str(cat):
    """カテゴリの素性を短い表記にする"""
    return (f'{CONT_LABEL[cat["continuity"]]}・動作性（{cat["action"]}）・'
            f'{VOL_LABEL[cat["volition"]]}')


# =====================================================================
#  フィードバックエンジン
#    「どの素性が条件を満たすか／満たさないか」を計算し、説明文を組み立てる
# =====================================================================
def expr_checks(cat, e):
    """カテゴリー cat と表現形式 e の素性照合。条件が空の素性は対象外。"""
    checks = []
    for fkey in ("continuity", "action", "volition"):
        allowed = [v for v in e[REQ_COL[fkey]].split("|") if v]
        if not allowed:
            continue
        checks.append({
            "key": fkey,
            "name": FEATURE_NAME[fkey],
            "req": req_label(fkey, allowed),
            "actual": val_label(fkey, cat[fkey]),
            "ok": cat[fkey] in allowed,
            "why": e[WHY_COL[fkey]],
        })
    return checks


def expr_combines(cat, e):
    return all(c["ok"] for c in expr_checks(cat, e))


def expr_feedback(word, cat, e):
    """語 × 表現形式 のフィードバックを組み立てる。

    戻り値:
      ok        … 結びつくか
      checks    … 素性ごとの照合結果
      headline  … 結論の一文
      lines     … 素性ごとの説明（満たす／満たさない）
      no_cond   … 前接条件が「不問」の形式か
    """
    checks = expr_checks(cat, e)
    ok = all(c["ok"] for c in checks)

    if not checks:
        return {
            "ok": True, "checks": [], "no_cond": True,
            "headline": f'「〜{e["label"]}」は前接条件がなく、どの素性のオノマトペにも付きます。',
            "lines": [f'「〜{e["label"]}」は{e["phase"]}を表し、完遂・不本意の意味を添えるだけなので、'
                      f'素性による制限がありません。ー継続性の語（いらっ・ずきっ など）が'
                      f'結びつける形は、事実上これだけです。'],
        }

    lines = []
    for c in checks:
        if c["ok"]:
            lines.append(f'{c["name"]}：「〜{e["label"]}」は〈{c["req"]}〉を必要とし、'
                         f'「{word["word"]}」は〈{c["actual"]}〉→ 満たす ○')
        else:
            msg = (f'{c["name"]}：「〜{e["label"]}」は〈{c["req"]}〉を必要としますが、'
                   f'「{word["word"]}」は〈{c["actual"]}〉→ 満たさない ×')
            if c["why"]:
                msg += f'　{c["why"]}'
            lines.append(msg)

    if ok:
        headline = (f'必要な素性をすべて満たすので、「{word["word"]}〜{e["label"]}」は結びつきます。')
    else:
        ng = "・".join(c["name"] for c in checks if not c["ok"])
        headline = (f'{ng}が条件を満たさないので、「{word["word"]}〜{e["label"]}」は結びつきません。')

    return {"ok": ok, "checks": checks, "no_cond": False,
            "headline": headline, "lines": lines}


def phon_note(word, fkey):
    """音韻形態からの予測と実際の素性を比べたコメント（continuity / action のみ）"""
    if fkey not in PRED_COL:
        return None
    phon = PHON_BY_KEY[word["phon"]]
    cat = CAT_BY_ID[word["category_id"]]
    pred = phon[PRED_COL[fkey]]
    if not pred:
        # この形からは予測できない素性
        return {"match": None,
                "text": f'{phon["label"]}からは{FEATURE_NAME[fkey]}を予測できません。'
                        f'{phon["pred_note"]}'}
    if pred == cat[fkey]:
        return {"match": True,
                "text": f'音の形（{phon["label"]}）からの予測どおりです。'
                        f'この形は〈{val_label(fkey, pred)}〉になりやすい形です。'}
    return {"match": False,
            "text": f'{phon["label"]}は〈{val_label(fkey, pred)}〉になりやすい形ですが、'
                    f'「{word["word"]}」は〈{val_label(fkey, cat[fkey])}〉です。'
                    f'{phon["pred_note"]}'}


def feature_feedback(word, fkey):
    """素性1つぶんのフィードバック（Step2・素性ドリルで使う）"""
    cat = CAT_BY_ID[word["category_id"]]
    return {
        "correct_value": cat[fkey],
        "correct_label": val_label(fkey, cat[fkey]),
        "why": cat[WHY_COL[fkey]],
        "general": FEATURE_EXPLAINS[fkey],
        "phon": phon_note(word, fkey),
    }


# =====================================================================
#  補助関数
# =====================================================================
def get_word(word_id: str):
    return WORD_BY_ID.get(word_id)


def get_category(word):
    return CAT_BY_ID[word["category_id"]]




def meaning_options(word, n=4):
    """1-1（意味の確認）の選択肢。紛らわしい順に誤答を補う。"""
    kind = CAT_BY_ID[word["category_id"]]["kind"]
    same_cat = [w for w in WORDS if w["id"] != word["id"]
                and w["category_id"] == word["category_id"]]
    same_kind = [w for w in WORDS if w["id"] != word["id"]
                 and w["category_id"] != word["category_id"]
                 and CAT_BY_ID[w["category_id"]]["kind"] == kind]
    others = [w for w in WORDS if w["id"] != word["id"]
              and CAT_BY_ID[w["category_id"]]["kind"] != kind]

    distractors = random.sample(same_cat, min(2, len(same_cat)))
    for pool in (same_kind, others):
        need = (n - 1) - len(distractors)
        if need <= 0:
            break
        distractors += random.sample(pool, min(need, len(pool)))

    opts = [{"text": word["meaning"], "src": word["id"]}]
    opts += [{"text": d["meaning"], "src": d["id"]} for d in distractors]
    random.shuffle(opts)
    return opts






# =====================================================================
#  トップページ
# =====================================================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "total": len(WORDS),
    })


# =====================================================================
#  フェーズ1：素性の学習
# =====================================================================
def build_phon_table():
    """音韻形態 × 素性の対応表（予測できない素性は「—」、予測と違う語は例外として列挙）"""
    table = []
    for p in PHON_DEFS:
        exceptions = []
        for w in WORDS:
            if w["phon"] != p["key"]:
                continue
            cat = CAT_BY_ID[w["category_id"]]
            for fkey in ("continuity", "action"):
                pred = p[PRED_COL[fkey]]
                if pred and cat[fkey] != pred:
                    exceptions.append(f'{w["word"]}（{FEATURE_NAME[fkey]}）')
        table.append({
            "form": p,
            "pred_cont_label": val_label("continuity", p["pred_cont"]) if p["pred_cont"] else "—（語による）",
            "pred_act_label": val_label("action", p["pred_act"]) if p["pred_act"] else "—（語による）",
            "exceptions": exceptions,
        })
    return table


# その形からの予測と実際の素性が食い違う語（段階4の出題に使う）
EXCEPTION_WORDS = []
for _w in WORDS:
    _p = PHON_BY_KEY[_w["phon"]]
    _c = CAT_BY_ID[_w["category_id"]]
    for _f in ("continuity", "action"):
        if _p[PRED_COL[_f]] and _c[_f] != _p[PRED_COL[_f]]:
            EXCEPTION_WORDS.append((_w, _f))


# =====================================================================
#  フェーズ1：語ごとの連鎖学習
#    意味 → 音の形 → 継続性 → 動作性 → 意志性 を1語で最後までたどる。
#    前の問いの答えが次の問いの前提になる（「ABAB型なので、継続性は？」）。
# =====================================================================
CHAIN = [
    {"k": 1, "key": "meaning",    "icon": "\U0001f4ad", "title": "意味"},
    {"k": 2, "key": "phon",       "icon": "\U0001f524", "title": "音の形"},
    {"k": 3, "key": "continuity", "icon": "\u23f1",     "title": "継続性"},
    {"k": 4, "key": "action",     "icon": "\U0001f3c3", "title": "動作性"},
    {"k": 5, "key": "volition",   "icon": "\u270b",     "title": "意志性"},
]
CHAIN_BY_K = {c["k"]: c for c in CHAIN}

# 素性値 → 図（選択肢にそのまま出す）
FEATURE_FIGS = {
    "continuity": {"＋": "cont_plus.svg", "変化結果の＋": "result_plus.svg", "ー": "cont_minus.svg"},
    "action":     {"高": "act_high.svg", "中": "act_mid.svg", "低": "act_low.svg"},
    "volition":   {"＋": "vol_plus.svg", "ー": "vol_minus.svg", "関与しない": "vol_na.svg"},
}

# 選択肢に添える短い説明
FEATURE_OPTION_NOTES = {
    "continuity": {
        "＋": "その状態・動きが時間幅をもって続く",
        "変化結果の＋": "変化は一度きり。そのあと結果の状態が残る",
        "ー": "一瞬で成立し、あとに残らない",
    },
    "action": {
        "高": "外から見える具体的で激しい動きがある",
        "中": "動きより気持ち・感覚が中心だが、時間の幅がある",
        "低": "積極的な動きがなく、ゆるやか／力が抜けている",
    },
    "volition": {
        "＋": "「今から〜しよう」と言える",
        "ー": "意志では起こせない感情・感覚",
        "関与しない": "動きはあるが、状況に反応して起こる",
    },
}


def feature_options(fkey):
    """素性の選択肢（図つき）"""
    fdef = next(f for f in FEATURE_DEFS if f["key"] == fkey)
    return [{"value": v,
             "label": val_label(fkey, v),
             "fig": FEATURE_FIGS[fkey][v],
             "note": FEATURE_OPTION_NOTES[fkey][v]} for v in fdef["options"]]


def phon_options(word, n_distractors=2):
    """音韻形態の選択肢（正解＋紛らわしい形）。例から学習中の語は外す。"""
    correct = PHON_BY_KEY[word["phon"]]
    others = [p for p in PHON_DEFS if p["key"] != correct["key"]]
    opts = [correct] + random.sample(others, min(n_distractors, len(others)))
    random.shuffle(opts)
    out = []
    for p in opts:
        ex = [e for e in p["example"].split("・") if e != word["word"]][:3]
        out.append({"value": p["key"], "label": p["label"], "term": p["term"],
                    "example": "・".join(ex)})
    return out


def chain_question(w, k):
    """k番目の問い。前の段の「正解」を踏まえた導入文をつける。"""
    cat = get_category(w)
    phon = PHON_BY_KEY[w["phon"]]
    step = CHAIN_BY_K[k]

    if k == 1:
        return {"step": step, "kind": "meaning",
                "lead": "まず、この語がどんな意味かを確かめます。場面を読んでから選んでください。",
                "prompt": f'この場面の「{w["word"]}」に最も近い意味はどれ？',
                "meaning_opts": meaning_options(w)}

    if k == 2:
        return {"step": step, "kind": "phon",
                "lead": (f'「{w["word"]}」は〈{w["meaning"]}〉という意味でした。'
                         f'次は<strong>音の形</strong>を見ます。音の形は素性のヒントになります。'),
                "prompt": f'「{w["word"]}」はどの音韻形態？',
                "phon_opts": phon_options(w)}

    if k == 3:
        pred = phon["pred_cont"]
        lead = (f'「{w["word"]}」は<strong>{phon["label"]}</strong>（{phon["term"]}）でした。'
                f'この形は「{phon["hint"]}」という特徴があり、'
                f'<strong>〈{val_label("continuity", pred)}〉になりやすい形</strong>です。')
        return {"step": step, "kind": "feature", "fkey": "continuity",
                "lead": lead + "　では、実際はどうでしょうか。",
                "prompt": f'「{w["word"]}」の継続性は？',
                "options": feature_options("continuity")}

    if k == 4:
        pred = phon["pred_act"]
        lead = (f'継続性は<strong>〈{val_label("continuity", cat["continuity"])}〉</strong>でした。'
                f'{KNOWLEDGE["rule"][0]["body"]}')
        if pred:
            lead += (f'　音の形（{phon["label"]}）からは'
                     f'〈{val_label("action", pred)}〉が予測されます。')
        else:
            lead += (f'　なお{phon["label"]}からは動作性を予測できません'
                     f'（語の意味しだいで変わります）。')
        return {"step": step, "kind": "feature", "fkey": "action",
                "lead": lead,
                "prompt": f'「{w["word"]}」の動作性は？',
                "options": feature_options("action")}

    lead = (f'ここまでで<strong>〈{val_label("continuity", cat["continuity"])}・'
            f'{val_label("action", cat["action"])}〉</strong>と決まりました。最後は意志性です。'
            f'<strong>「今から{w["word"]}しよう」と言えるか</strong>を試してみてください。')
    return {"step": step, "kind": "feature", "fkey": "volition",
            "lead": lead,
            "prompt": f'「{w["word"]}」の意志性は？',
            "options": feature_options("volition")}


def chain_feedback(w, k, choice):
    """k番目の答え合わせ。正誤と、素性にもとづく理由を返す。"""
    cat = get_category(w)
    phon = PHON_BY_KEY[w["phon"]]

    if k == 1:
        chosen = get_word(choice)
        return {"ok": choice == w["id"],
                "user": chosen["meaning"] if chosen else "(未選択)",
                "correct": w["meaning"],
                "why": f'場面：{w["scene"]}',
                "extra": "意味がはっきりすると、このあとの素性の判断がぶれなくなります。"}

    if k == 2:
        chosen = PHON_BY_KEY.get(choice)
        pred_act = (val_label("action", phon["pred_act"]) if phon["pred_act"]
                    else "予測できない（語による）")
        return {"ok": choice == phon["key"],
                "user": chosen["label"] if chosen else "(未選択)",
                "correct": f'{phon["label"]}（{phon["term"]}）',
                "why": f'この形は「{phon["hint"]}」という特徴があります。',
                "extra": (f'予測される継続性：〈{val_label("continuity", phon["pred_cont"])}〉／'
                          f'予測される動作性：〈{pred_act}〉')}

    fkey = {3: "continuity", 4: "action", 5: "volition"}[k]
    fb = feature_feedback(w, fkey)
    return {"ok": choice == fb["correct_value"],
            "user": val_label(fkey, choice) if choice else "(未選択)",
            "correct": fb["correct_label"],
            "why": fb["why"],
            "extra": fb["phon"]["text"] if fb["phon"] else fb["general"],
            "phon_match": fb["phon"]["match"] if fb["phon"] else None,
            "fig": FEATURE_FIGS[fkey].get(fb["correct_value"])}


@app.get("/phase1", response_class=HTMLResponse)
async def phase1(request: Request):
    groups = [{"category": c, "words": [w for w in WORDS if w["category_id"] == c["id"]]}
              for c in CATEGORIES]
    return templates.TemplateResponse(request, "phase1.html", {
        "chain": CHAIN, "groups": groups, "total": len(WORDS),
    })


@app.get("/phase1/summary", response_class=HTMLResponse)
async def phase1_summary(request: Request):
    return templates.TemplateResponse(request, "phase1_summary.html", {
        "knowledge": KNOWLEDGE,
        "categories": CATEGORIES,
        "phon_table": build_phon_table(),
        "figs": FEATURE_FIGS,
    })


@app.get("/phase1/word/{word_id}/done", response_class=HTMLResponse)
async def phase1_chain_done(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/phase1")
    cat = get_category(w)
    idx = [x["id"] for x in WORDS].index(w["id"])
    nxt = WORDS[idx + 1] if idx + 1 < len(WORDS) else None
    return templates.TemplateResponse(request, "phase1_chain_done.html", {
        "word": w, "category": cat, "chain": CHAIN,
        "profile": profile_str(cat),
        "phon": PHON_BY_KEY[w["phon"]],
        "figs": FEATURE_FIGS,
        "next_word": nxt,
    })



def _q_feat(fkey=None, word=None):
    w = word or random.choice(WORDS)
    f = (next(x for x in FEATURE_DEFS if x["key"] == fkey) if fkey
         else random.choice(FEATURE_DEFS))
    phon = PHON_BY_KEY[w["phon"]]
    return {
        "type": "feat", "spec": f'f:{w["id"]}:{f["key"]}',
        "word": w, "feature": f,
        "prompt": f'「{w["word"]}」の{f["name"]}は？',
        "options": f["options"],
        "hint_feature": f["key"],
        "hint_extra": f'音の形：{phon["label"]}（{phon["term"]}）→ {phon["hint"]}',
    }


def _q_phon(phon=None, fkey=None):
    p = phon or random.choice([x for x in PHON_DEFS if x["pred_cont"] or x["pred_act"]])
    if not fkey:
        fkey = random.choice([f for f in ("continuity", "action") if p[PRED_COL[f]]])
    fdef = next(f for f in FEATURE_DEFS if f["key"] == fkey)
    return {
        "type": "phon", "spec": f'p:{p["key"]}:{fkey}',
        "word": None, "feature": fdef,
        "prompt": f'「{p["label"]}」（{p["term"]}）の語は、{fdef["name"]}がどうなりやすい？',
        "sub": f'この形の語の例：{p["example"]}',
        "options": fdef["options"],
        "hint_feature": fkey,
        "hint_extra": f'この形は「{p["hint"]}」という特徴があります。',
    }


def _q_same(fkey=None):
    fkey = fkey or random.choice(["continuity", "action", "volition"])
    fdef = next(f for f in FEATURE_DEFS if f["key"] == fkey)
    for _ in range(30):
        target = random.choice(WORDS)
        tv = CAT_BY_ID[target["category_id"]][fkey]
        same = [w for w in WORDS if w["id"] != target["id"]
                and CAT_BY_ID[w["category_id"]][fkey] == tv]
        diff = [w for w in WORDS if CAT_BY_ID[w["category_id"]][fkey] != tv]
        if same and len(diff) >= 3:
            opts = [random.choice(same)] + random.sample(diff, 3)
            random.shuffle(opts)
            return {
                "type": "same", "spec": f'S:{target["id"]}:{fkey}',
                "word": target, "feature": fdef,
                "prompt": f'「{target["word"]}」と同じ{fdef["name"]}を持つオノマトペはどれ？',
                "sub": f'まず「{target["word"]}」の{fdef["name"]}を考え、次に選択肢の語と比べましょう。',
                "word_options": opts,
                "hint_feature": fkey,
                "hint_extra": f'「{target["word"]}」の場面：{target["scene"]}',
            }
    return _q_feat()


def _q_cat():
    for _ in range(30):
        cat = random.choice(CATEGORIES)
        inside = [w for w in WORDS if w["category_id"] == cat["id"]]
        outside = [w for w in WORDS if w["category_id"] != cat["id"]]
        if inside and len(outside) >= 3:
            opts = [random.choice(inside)] + random.sample(outside, 3)
            random.shuffle(opts)
            return {
                "type": "cat", "spec": f'C:{cat["id"]}',
                "word": None, "feature": None, "category": cat,
                "prompt": f'〈{profile_str(cat)}〉を持つ{cat["kind"]}のオノマトペはどれ？',
                "sub": "選択肢の語の素性を1つずつ確かめて、3つの素性がすべて合うものを選びましょう。",
                "word_options": opts,
                "hint_feature": None,
                "hint_extra": f'このカテゴリーは「{cat["name"]}」です。',
            }
    return _q_feat()


# 総合ドリルの出題構成（タイプ, 問数）
DRILL_PLAN = [("feat", 3), ("phon", 1), ("same", 1), ("cat", 1)]



@app.get("/phase1/word/{word_id}/{k}", response_class=HTMLResponse)
async def phase1_chain(request: Request, word_id: str, k: int):
    w = get_word(word_id)
    if not w or k not in CHAIN_BY_K:
        return RedirectResponse("/phase1")
    return templates.TemplateResponse(request, "phase1_chain.html", {
        "word": w, "chain": CHAIN, "k": k,
        "q": chain_question(w, k),
    })


@app.post("/phase1/word/{word_id}/{k}/check", response_class=HTMLResponse)
async def phase1_chain_check(request: Request, word_id: str, k: int):
    w = get_word(word_id)
    if not w or k not in CHAIN_BY_K:
        return RedirectResponse("/phase1")
    form = await request.form()
    choice = form.get("choice", "")
    return templates.TemplateResponse(request, "phase1_chain_result.html", {
        "word": w, "chain": CHAIN, "k": k,
        "step": CHAIN_BY_K[k],
        "fb": chain_feedback(w, k, choice),
        "next_k": k + 1 if k < len(CHAIN) else None,
    })


@app.get("/phase1/drill", response_class=HTMLResponse)
async def phase1_drill(request: Request):
    builders = {"feat": _q_feat, "phon": _q_phon, "same": _q_same, "cat": _q_cat}
    questions = []
    for kind, n in DRILL_PLAN:
        for _ in range(n):
            questions.append(builders[kind]())
    random.shuffle(questions)
    for i, q in enumerate(questions):
        q["idx"] = i
    return templates.TemplateResponse(request, "phase1_drill.html", {
        "questions": questions, "n": len(questions),
        "knowledge": KNOWLEDGE,
    })


def grade_feature_questions(form):
    """素性系の問題（feat / phon / same / cat）を採点し、素性ベースの解説をつける。
    段階演習（/phase1/stage/n）と総合ドリル（/phase1/drill）で共用する。"""
    results = []
    n_correct = 0
    i = 0
    while f"spec_{i}" in form:
        spec = form.get(f"spec_{i}", "")
        choice = form.get(f"choice_{i}", "")
        r = None

        if spec.startswith("f:"):
            _, word_id, fkey = spec.split(":", 2)
            w = get_word(word_id)
            if w:
                fb = feature_feedback(w, fkey)
                ok = (choice == fb["correct_value"])
                r = {"type": "feat", "word": w,
                     "title": f'「{w["word"]}」の{FEATURE_NAME[fkey]}',
                     "user": choice, "correct_value": fb["correct_value"],
                     "ok": ok,
                     "explain": fb["why"],
                     "extra": fb["phon"]["text"] if fb["phon"] else fb["general"]}

        elif spec.startswith("p:"):
            _, pkey, fkey = spec.split(":", 2)
            p = PHON_BY_KEY.get(pkey)
            if p:
                correct = p[PRED_COL[fkey]]
                ok = (choice == correct)
                exceptions = [w["word"] for w in WORDS
                              if w["phon"] == pkey
                              and CAT_BY_ID[w["category_id"]][fkey] != correct]
                extra = (f'ただし例外もあります：{"・".join(exceptions)}。{p["pred_note"]}'
                         if exceptions else p["pred_note"])
                r = {"type": "phon", "word": None,
                     "title": f'「{p["label"]}」の{FEATURE_NAME[fkey]}の予測',
                     "user": choice, "correct_value": correct, "ok": ok,
                     "explain": f'{p["label"]}は〈{val_label(fkey, correct)}〉になりやすい形です。',
                     "extra": extra}

        elif spec.startswith("S:"):
            _, word_id, fkey = spec.split(":", 2)
            target = get_word(word_id)
            chosen = get_word(choice)
            if target:
                tv = CAT_BY_ID[target["category_id"]][fkey]
                cv = CAT_BY_ID[chosen["category_id"]][fkey] if chosen else None
                ok = (cv == tv)
                r = {"type": "same", "word": target,
                     "title": f'「{target["word"]}」と同じ{FEATURE_NAME[fkey]}の語',
                     "user": f'{chosen["word"]}（{val_label(fkey, cv)}）' if chosen else "(未選択)",
                     "correct_value": f'{val_label(fkey, tv)}の語',
                     "ok": ok,
                     "explain": f'「{target["word"]}」は〈{val_label(fkey, tv)}〉です。'
                                f'{CAT_BY_ID[target["category_id"]][WHY_COL[fkey]]}',
                     "extra": (f'選んだ「{chosen["word"]}」は〈{val_label(fkey, cv)}〉なので違います。'
                               if chosen and not ok else FEATURE_EXPLAINS[fkey])}

        elif spec.startswith("C:"):
            cat_id = spec[2:]
            cat = CAT_BY_ID.get(cat_id)
            chosen = get_word(choice)
            if cat:
                ok = (chosen is not None and chosen["category_id"] == cat_id)
                answer = next(w["word"] for w in WORDS if w["category_id"] == cat_id)
                r = {"type": "cat", "word": None,
                     "title": f'〈{profile_str(cat)}〉の{cat["kind"]}のオノマトペ',
                     "user": chosen["word"] if chosen else "(未選択)",
                     "correct_value": f'{cat["name"]}の語（例：{answer}）',
                     "ok": ok,
                     "explain": f'この素性の組み合わせは「{cat["name"]}」です。{cat["profile_text"]}',
                     "extra": (f'選んだ「{chosen["word"]}」は「{CAT_BY_ID[chosen["category_id"]]["name"]}」'
                               f'＝〈{profile_str(CAT_BY_ID[chosen["category_id"]])}〉です。'
                               if chosen and not ok else "")}

        if r:
            r["no"] = len(results) + 1
            results.append(r)
            n_correct += 1 if r["ok"] else 0
        i += 1
    return results, n_correct


@app.post("/phase1/drill/check", response_class=HTMLResponse)
async def phase1_drill_check(request: Request):
    form = await request.form()
    results, n_correct = grade_feature_questions(form)
    return templates.TemplateResponse(request, "phase1_drill_result.html", {
        "results": results, "n_correct": n_correct, "total": len(results),
    })


# =====================================================================
#  フェーズ2：文法形式の学習
# =====================================================================
@app.get("/phase2", response_class=HTMLResponse)
async def phase2(request: Request):
    # 表現形式の詳細カード（項目3）
    expr_cards = []
    for e in EXPRESSIONS:
        reqs = []
        for fkey in ("continuity", "action", "volition"):
            allowed = [v for v in e[REQ_COL[fkey]].split("|") if v]
            if allowed:
                reqs.append({"key": fkey, "name": FEATURE_NAME[fkey],
                             "text": req_label(fkey, allowed),
                             "why": e[WHY_COL[fkey]]})
        expr_cards.append({"expr": e, "reqs": reqs})

    groups = [{"category": c, "words": [w for w in WORDS if w["category_id"] == c["id"]]}
              for c in CATEGORIES]
    return templates.TemplateResponse(request, "phase2.html", {
        "expr_cards": expr_cards,
        "expr_guide": KNOWLEDGE["expr_guide"],
        "expr_note": KNOWLEDGE["expr_note"],
        "groups": groups,
    })


# ---------------------------------------------------------------------
#  前接条件ドリル
#    E cond … 表現形式の前接条件を答える
#    F pair … その表現形式と結びつく語を選ぶ
# ---------------------------------------------------------------------
EXPR_DRILL_PLAN = [("cond", 2), ("pair", 2)]


def _q_cond():
    e = random.choice(EXPRESSIONS)
    pool = list(dict.fromkeys(x["cond_text"] for x in EXPRESSIONS if x["cond_text"] != e["cond_text"]))
    opts = random.sample(pool, min(3, len(pool))) + [e["cond_text"]]
    random.shuffle(opts)
    return {
        "type": "cond", "spec": f'x:{e["key"]}',
        "prompt": f'「〜{e["label"]}」はどんな素性のオノマトペと結びつく？',
        "sub": f'局面：{e["phase"]}／使い方の例：「{e["example"]}」',
        "options": opts,
        "hint": f'この形式が表す局面（{e["phase"]}）から考えましょう。'
                f'{e["ok_example"]} ／ {e["ng_example"]}',
    }


def _q_pair():
    for _ in range(30):
        e = random.choice(EXPRESSIONS)
        ok_words = [w for w in WORDS if expr_combines(CAT_BY_ID[w["category_id"]], e)]
        ng_words = [w for w in WORDS if not expr_combines(CAT_BY_ID[w["category_id"]], e)]
        if ok_words and len(ng_words) >= 3:
            opts = [random.choice(ok_words)] + random.sample(ng_words, 3)
            random.shuffle(opts)
            return {
                "type": "pair", "spec": f'y:{e["key"]}',
                "prompt": f'「〜{e["label"]}」と結びつくオノマトペはどれ？',
                "sub": f'前接条件：{e["cond_text"]}',
                "word_options": opts,
                "hint": f'各語の素性を思い出して、条件〈{e["cond_text"]}〉を満たすか照合しましょう。',
            }
    return _q_cond()


@app.get("/phase2/drill", response_class=HTMLResponse)
async def phase2_drill(request: Request):
    builders = {"cond": _q_cond, "pair": _q_pair}
    questions = []
    for kind, n in EXPR_DRILL_PLAN:
        for _ in range(n):
            questions.append(builders[kind]())
    random.shuffle(questions)
    for i, q in enumerate(questions):
        q["idx"] = i
    return templates.TemplateResponse(request, "phase2_drill.html", {
        "questions": questions, "n": len(questions),
    })


@app.post("/phase2/drill/check", response_class=HTMLResponse)
async def phase2_drill_check(request: Request):
    form = await request.form()
    results = []
    n_correct = 0
    i = 0
    while f"spec_{i}" in form:
        spec = form.get(f"spec_{i}", "")
        choice = form.get(f"choice_{i}", "")
        r = None

        if spec.startswith("x:"):
            e = EXPR_BY_KEY.get(spec[2:])
            if e:
                ok = (choice == e["cond_text"])
                r = {"type": "cond",
                     "title": f'「〜{e["label"]}」の前接条件',
                     "user": choice, "correct_value": e["cond_text"], "ok": ok,
                     "explain": f'「〜{e["label"]}」は{e["phase"]}を表し、「{e["example"]}」のように使います。',
                     "lines": [f'{FEATURE_NAME[f]}：{e[WHY_COL[f]]}'
                               for f in ("continuity", "action", "volition") if e[WHY_COL[f]]],
                     "examples": f'{e["ok_example"]} ／ {e["ng_example"]}'}

        elif spec.startswith("y:"):
            e = EXPR_BY_KEY.get(spec[2:])
            chosen = get_word(choice)
            if e:
                ok = bool(chosen) and expr_combines(CAT_BY_ID[chosen["category_id"]], e)
                fb = (expr_feedback(chosen, CAT_BY_ID[chosen["category_id"]], e)
                      if chosen else None)
                r = {"type": "pair",
                     "title": f'「〜{e["label"]}」と結びつく語',
                     "user": chosen["word"] if chosen else "(未選択)",
                     "correct_value": f'前接条件〈{e["cond_text"]}〉を満たす語', "ok": ok,
                     "explain": fb["headline"] if fb else "",
                     "lines": fb["lines"] if fb else [],
                     "examples": f'{e["ok_example"]} ／ {e["ng_example"]}'}

        if r:
            r["no"] = len(results) + 1
            results.append(r)
            n_correct += 1 if r["ok"] else 0
        i += 1

    return templates.TemplateResponse(request, "phase2_drill_result.html", {
        "results": results, "n_correct": n_correct, "total": len(results),
    })


# =====================================================================
#  フェーズ3：例文への適用
# =====================================================================
@app.get("/phase3", response_class=HTMLResponse)
async def phase3(request: Request):
    groups = [{"category": c, "words": [w for w in WORDS if w["category_id"] == c["id"]]}
              for c in CATEGORIES]
    return templates.TemplateResponse(request, "phase3.html", {
        "groups": groups,
    })


# =====================================================================
#  Step3：文法形式との線結び（局面別グループ＋段階ヒント）
# =====================================================================
@app.get("/step3/{word_id}", response_class=HTMLResponse)
async def step3(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)

    # 局面グループごとにまとめ、グループ内はシャッフル
    groups = []
    for g in EXPR_GROUPS:
        exprs = g["exprs"][:]
        random.shuffle(exprs)
        groups.append({"name": g["name"], "exprs": exprs})

    # ヒント3（照合表）用：語の素性と各表現の条件を並べる。○×は出さない。
    match_rows = []
    for e in EXPRESSIONS:
        reqs = []
        for fkey in ("continuity", "action", "volition"):
            allowed = [v for v in e[REQ_COL[fkey]].split("|") if v]
            if allowed:
                reqs.append(req_label(fkey, allowed))
        match_rows.append({"label": e["label"],
                           "req": " ＋ ".join(reqs) if reqs else "条件なし（不問）"})

    return templates.TemplateResponse(request, "step3.html", {
        "word": w,
        "word_hint": profile_str(cat),
        "expr_groups": groups,
        "expressions": EXPRESSIONS,
        "match_rows": match_rows,
        "guide": KNOWLEDGE["expr_guide"],
    })


@app.post("/step3/{word_id}/check", response_class=HTMLResponse)
async def step3_check(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    form = await request.form()
    hint_level = form.get("hint_level", "0")

    expr_results = []
    n_expr_correct = 0
    for e in EXPRESSIONS:
        fb = expr_feedback(w, cat, e)
        can_combine = fb["ok"]
        user_connected = (form.get(e["key"]) == "○")
        ok = (can_combine == user_connected)
        n_expr_correct += 1 if ok else 0
        expr_results.append({
            "label": e["label"], "phase": e["phase"], "cond_text": e["cond_text"],
            "should": can_combine, "connected": user_connected, "ok": ok,
            "headline": fb["headline"], "lines": fb["lines"],
            "no_cond": fb["no_cond"],
            "example": e["ok_example"] if can_combine else e["ng_example"],
        })

    all_correct = (n_expr_correct == len(EXPRESSIONS))
    return templates.TemplateResponse(request, "step3_result.html", {
        "word": w, "category": cat,
        "profile": profile_str(cat),
        "expr_results": expr_results,
        "n_expr_correct": n_expr_correct, "total_expr": len(EXPRESSIONS),
        "expr_explain": cat["expr_explain"],
        "all_correct": all_correct,
        "hint_level": hint_level,
    })


# =====================================================================
#  Step4：例文の練習（語ごとの自然文＋誤答は素性条件を満たさない形から自動生成）
# =====================================================================
FORM_COL = {"base": "form_base", "past": "form_past"}


def step4_build(w, n_distractors=2):
    cat = get_category(w)
    ok_keys = CAT_EXPRS.get(cat["id"], set())
    ng_exprs = [e for e in EXPRESSIONS if e["key"] not in ok_keys]

    questions = []
    for q in PRACTICE.get(w["id"], []):
        col = FORM_COL.get(q["form"], "form_base")
        correct = EXPR_BY_KEY[q["correct_key"]]
        ds = random.sample(ng_exprs, min(n_distractors, len(ng_exprs)))
        opts = [{"key": correct["key"], "label": correct[col], "phase": correct["phase"]}]
        opts += [{"key": d["key"], "label": d[col], "phase": d["phase"]} for d in ds]
        random.shuffle(opts)
        questions.append({
            "idx": q["ord"], "text": q["frame"], "options": opts,
            "correct_key": correct["key"],
            "opt_keys": ",".join(o["key"] for o in opts),
            "form": q["form"],
        })
    return questions


@app.get("/step4/{word_id}", response_class=HTMLResponse)
async def step4(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    return templates.TemplateResponse(request, "step4.html", {
        "word": w, "questions": step4_build(w),
        "word_hint": profile_str(cat),
    })


@app.post("/step4/{word_id}/check", response_class=HTMLResponse)
async def step4_check(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    form = await request.form()

    results = []
    n_correct = 0
    for q in PRACTICE.get(w["id"], []):
        i = q["ord"]
        col = FORM_COL.get(q["form"], "form_base")
        choice = form.get(f"choice_{i}", "")
        shown = [k for k in form.get(f"opt_keys_{i}", "").split(",") if k in EXPR_BY_KEY]
        if not shown:
            shown = [q["correct_key"]]

        correct = EXPR_BY_KEY[q["correct_key"]]
        ok = (choice == correct["key"])
        n_correct += 1 if ok else 0

        opt_results = []
        for k in shown:
            e = EXPR_BY_KEY[k]
            fb = expr_feedback(w, cat, e)
            opt_results.append({
                "label": e[col], "phase": e["phase"],
                "is_correct": (k == correct["key"]),
                "is_chosen": (k == choice),
                "ok": fb["ok"], "headline": fb["headline"], "lines": fb["lines"],
            })

        fb_correct = expr_feedback(w, cat, correct)
        results.append({
            "no": i + 1, "ok": ok,
            "completed": q["frame"].replace("[ ？ ]", "〈" + correct[col] + "〉"),
            "correct_label": correct[col],
            "correct_phase": correct["phase"],
            "headline": fb_correct["headline"],
            "lines": fb_correct["lines"],
            "option_results": opt_results,
        })

    all_correct = (n_correct == len(results))
    return templates.TemplateResponse(request, "step4_result.html", {
        "word": w, "category": cat, "profile": profile_str(cat),
        "all_correct": all_correct,
        "n_correct": n_correct, "total": len(results),
        "results": results,
    })
