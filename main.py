# main.py
# オノマトペ学習支援システム
#   Step1: 意味・音韻形態・種類（感情感覚/動作）の判断
#   Step2: 3つの素性（継続性・動作性・意志性）+ 8カテゴリーの判断
#   Step3: 文法形式との線結び
#   Step4: 例文の練習
import random
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from database import load_all

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---- 起動時に DB から全データを読み込む ----
DB = load_all()

WORDS       = DB["words"]
WORD_BY_ID  = DB["word_by_id"]
CATEGORIES  = DB["categories"]
CAT_BY_ID   = DB["cat_by_id"]
EXPRESSIONS = DB["expressions"]
CAT_EXPRS   = DB["cat_exprs"]
PHON_DEFS   = DB["phon_defs"]
PHON_BY_KEY = DB["phon_by_key"]
KNOWLEDGE   = DB["knowledge"]
PRACTICE    = DB["practice"]

KIND_OPTIONS = ["感情・感覚", "動作"]

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

# =====================================================================
#  補助関数
# =====================================================================
def get_word(word_id: str):
    return WORD_BY_ID.get(word_id)

def get_category(word):
    return CAT_BY_ID[word["category_id"]]

def feature_hint(cat):
    """単語の素性ヒント文字列（例：継続性＋・動作性（中）・意志性ー）"""
    return f"継続性{cat['continuity']}・動作性（{cat['action']}）・意志性{cat['volition']}"

def meaning_options(word, n=4):
    """1-1（意味の確認）の選択肢を作る。
    誤答の選定基準：意味が紛らわしく学習効果が高い順に、
      ① 同じカテゴリーの語（最大2語）
      ② 同じ種類（感情・感覚／動作）の語
      ③ その他の語
    から不足分を補う。学習中の語は除外する。
    """
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


def phon_defs_for(word):
    """1-2（音韻形態）用の選択肢。例示から学習中の語を除外し、
    例がそのまま答えにならないようにする。"""
    defs = []
    for p in PHON_DEFS:
        d = dict(p)
        examples = [e for e in p["example"].split("・") if e != word["word"]]
        d["example"] = "・".join(examples[:3])
        defs.append(d)
    return defs


def kind_examples_for(word, n=3):
    """1-3（種類の判断）用の例。学習中の語を除外してランダムに選ぶ。"""
    result = {}
    for kind in KIND_OPTIONS:
        pool = [w["word"] for w in WORDS
                if w["id"] != word["id"]
                and CAT_BY_ID[w["category_id"]]["kind"] == kind]
        result[kind] = "・".join(random.sample(pool, min(n, len(pool))))
    return result

# =====================================================================
#  トップページ（知識の提示）
# =====================================================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    groups = [{"category": c, "words": [w for w in WORDS if w["category_id"] == c["id"]]}
              for c in CATEGORIES]
    return templates.TemplateResponse(request, "index.html", {
        "knowledge": KNOWLEDGE,
        "categories": CATEGORIES,
        "phon_defs": PHON_DEFS,
        "expressions": EXPRESSIONS,
        "groups": groups,
        "total": len(WORDS),
    })


# =====================================================================
#  Step1：意味・音韻形態・種類の判断
# =====================================================================
@app.get("/step1/{word_id}", response_class=HTMLResponse)
async def step1(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "step1.html", {
        "word": w,
        "meaning_opts": meaning_options(w),
        "phon_defs": phon_defs_for(w),
        "kind_options": KIND_OPTIONS,
        "kind_examples": kind_examples_for(w),
    })


@app.post("/step1/{word_id}/check", response_class=HTMLResponse)
async def step1_check(
    request: Request, word_id: str,
    meaning: str = Form(...), phon: str = Form(...), kind: str = Form(...),
):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)

    meaning_correct = (meaning == word_id)
    cmw = get_word(meaning)
    chosen_meaning_text = cmw["meaning"] if cmw else "(不明)"

    phon_correct = (phon == w["phon"])
    kind_correct = (kind == cat["kind"])

    all_correct = meaning_correct and phon_correct and kind_correct

    return templates.TemplateResponse(request, "step1_result.html", {
        "word": w, "category": cat,
        "meaning_correct": meaning_correct, "chosen_meaning_text": chosen_meaning_text,
        "phon_correct": phon_correct,
        "chosen_phon": PHON_BY_KEY.get(phon), "correct_phon": PHON_BY_KEY[w["phon"]],
        "kind_correct": kind_correct, "chosen_kind": kind,
        "all_correct": all_correct,
    })


# =====================================================================
#  Step2：3つの素性 + 8カテゴリーの判断
# =====================================================================
@app.get("/step2/{word_id}", response_class=HTMLResponse)
async def step2(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "step2.html", {
        "word": w,
        "features": FEATURE_DEFS,
        "continuity_knowledge": KNOWLEDGE["continuity"],
        "rule": KNOWLEDGE["rule"][0],
    })


@app.post("/step2/{word_id}/check", response_class=HTMLResponse)
async def step2_check(
    request: Request, word_id: str,
    continuity: str = Form(...), action: str = Form(...), volition: str = Form(...),
):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)

    submitted = {"continuity": continuity, "action": action, "volition": volition}
    explains = {
        "continuity": "継続性は図のイメージで判断します（＋：続く／変化結果の＋：変化後の結果が残る／ー：一瞬）。",
        "action": "継続性が低いほど動作性は高くなります（ー継続性→高、続く状態→中、だらけた状態→低）。",
        "volition": "自分の意志で行える動き・行為なら「＋」、感情・感覚など自然に起こるものは「ー」です。",
    }

    feature_results = []
    n_feature_correct = 0
    for f in FEATURE_DEFS:
        correct_value = cat[f["key"]]
        ok = (submitted[f["key"]] == correct_value)
        n_feature_correct += 1 if ok else 0
        feature_results.append({
            "name": f["name"], "user": submitted[f["key"]],
            "correct_value": correct_value, "ok": ok,
            "explain": explains[f["key"]],
        })

    # カテゴリーは選択させず、Step1の種類（感情・感覚／動作）＋3素性の組み合わせから自動判定する
    derived = next((c for c in CATEGORIES
                    if c["kind"] == cat["kind"]
                    and c["continuity"] == continuity
                    and c["action"] == action
                    and c["volition"] == volition), None)
    category_correct = (derived is not None and derived["id"] == cat["id"])

    all_correct = (n_feature_correct == len(FEATURE_DEFS))

    return templates.TemplateResponse(request, "step2_result.html", {
        "word": w, "category": cat,
        "feature_results": feature_results,
        "n_feature_correct": n_feature_correct, "total_features": len(FEATURE_DEFS),
        "category_correct": category_correct,
        "derived_cat_name": derived["name"] if derived else "該当なし（素性の組み合わせを見直しましょう）",
        "all_correct": all_correct,
    })


# =====================================================================
#  Step3：文法形式との線結び
# =====================================================================
@app.get("/step3/{word_id}", response_class=HTMLResponse)
async def step3(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    expressions = EXPRESSIONS[:]
    random.shuffle(expressions)
    return templates.TemplateResponse(request, "step3.html", {
        "word": w,
        "word_hint": feature_hint(cat),   # 単語の素性ヒント（ヒントボタンで表示）
        "expressions": expressions,
    })


@app.post("/step3/{word_id}/check", response_class=HTMLResponse)
async def step3_check(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    correct_keys = CAT_EXPRS.get(cat["id"], set())

    form = await request.form()

    expr_results = []
    n_expr_correct = 0
    for e in EXPRESSIONS:
        can_combine = e["key"] in correct_keys
        user_connected = (form.get(e["key"]) == "○")
        ok = (can_combine == user_connected)
        n_expr_correct += 1 if ok else 0
        expr_results.append({
            "label": e["label"], "cond_text": e["cond_text"],
            "should": can_combine, "connected": user_connected,
            "ok": ok,
        })

    all_correct = (n_expr_correct == len(EXPRESSIONS))

    return templates.TemplateResponse(request, "step3_result.html", {
        "word": w, "category": cat,
        "expr_results": expr_results,
        "n_expr_correct": n_expr_correct, "total_expr": len(EXPRESSIONS),
        "expr_explain": cat["expr_explain"],
        "all_correct": all_correct,
    })


# =====================================================================
#  Step4：例文の練習
# =====================================================================
@app.get("/step4/{word_id}", response_class=HTMLResponse)
async def step4(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    questions = []
    for i, q in enumerate(PRACTICE[w["category_id"]]):
        opts = q["options"][:]
        random.shuffle(opts)
        questions.append({
            "idx": i,
            "text": q["frame"].replace("{word}", w["word"]),
            "options": opts,
        })
    return templates.TemplateResponse(request, "step4.html", {
        "word": w, "questions": questions,
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
    qs = PRACTICE[w["category_id"]]
    for i, q in enumerate(qs):
        choice = form.get(f"choice_{i}", "")
        correct_label = next(o["label"] for o in q["options"] if o["correct"])
        ok = (choice == correct_label)
        n_correct += 1 if ok else 0
        results.append({
            "no": i + 1,
            "ok": ok,
            "completed": q["frame"].replace("{word}", w["word"]).replace("[ ？ ]", "〈" + correct_label + "〉"),
            "explain": q["explain"],
            "option_results": [{
                "label": o["label"], "meaning": o["meaning"],
                "is_correct": o["correct"], "is_chosen": (o["label"] == choice),
            } for o in q["options"]],
        })

    all_correct = (n_correct == len(qs))

    return templates.TemplateResponse(request, "step4_result.html", {
        "word": w, "category": cat, "all_correct": all_correct,
        "n_correct": n_correct, "total": len(qs),
        "results": results,
    })