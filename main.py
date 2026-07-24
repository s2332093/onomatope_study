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

score_data = {"correct": 0, "wrong": 0, "history": []}


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
    others = [w for w in WORDS if w["id"] != word["id"]]
    distractors = random.sample(others, min(n - 1, len(others)))
    opts = [{"text": word["meaning"], "src": word["id"]}]
    opts += [{"text": d["meaning"], "src": d["id"]} for d in distractors]
    random.shuffle(opts)
    return opts

def record(step: str, word, ok: bool):
    score_data["correct" if ok else "wrong"] += 1
    score_data["history"].append({"word": word["word"], "step": step, "correct": ok})


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
        "score": score_data,
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
        "phon_defs": PHON_DEFS,
        "kind_options": KIND_OPTIONS,
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
    record("Step1", w, all_correct)

    return templates.TemplateResponse(request, "step1_result.html", {
        "word": w, "category": cat,
        "meaning_correct": meaning_correct, "chosen_meaning_text": chosen_meaning_text,
        "phon_correct": phon_correct,
        "chosen_phon": PHON_BY_KEY.get(phon), "correct_phon": PHON_BY_KEY[w["phon"]],
        "kind_correct": kind_correct, "chosen_kind": kind,
        "all_correct": all_correct, "score": score_data,
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
        "categories": CATEGORIES,
    })


@app.post("/step2/{word_id}/check", response_class=HTMLResponse)
async def step2_check(
    request: Request, word_id: str,
    continuity: str = Form(...), action: str = Form(...), volition: str = Form(...),
    category: str = Form(...),
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

    category_correct = (category == cat["id"])
    chosen_cat = CAT_BY_ID.get(category)

    all_correct = category_correct and (n_feature_correct == len(FEATURE_DEFS))
    record("Step2", w, all_correct)

    return templates.TemplateResponse(request, "step2_result.html", {
        "word": w, "category": cat,
        "feature_results": feature_results,
        "n_feature_correct": n_feature_correct, "total_features": len(FEATURE_DEFS),
        "category_correct": category_correct,
        "chosen_cat_name": chosen_cat["name"] if chosen_cat else "(未選択)",
        "all_correct": all_correct, "score": score_data,
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
            "user": "結ぶ" if user_connected else "結ばない",
            "correct_value": "結ぶ" if can_combine else "結ばない",
            "ok": ok,
        })

    all_correct = (n_expr_correct == len(EXPRESSIONS))
    record("Step3", w, all_correct)

    return templates.TemplateResponse(request, "step3_result.html", {
        "word": w, "category": cat,
        "expr_results": expr_results,
        "n_expr_correct": n_expr_correct, "total_expr": len(EXPRESSIONS),
        "expr_explain": cat["expr_explain"],
        "all_correct": all_correct, "score": score_data,
    })


# =====================================================================
#  Step4：例文の練習
# =====================================================================
@app.get("/step4/{word_id}", response_class=HTMLResponse)
async def step4(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    tpl = PRACTICE[w["category_id"]]
    question = tpl["frame"].replace("{word}", w["word"])
    opts = tpl["options"][:]
    random.shuffle(opts)
    return templates.TemplateResponse(request, "step4.html", {
        "word": w, "question": question, "options": opts,
    })


@app.post("/step4/{word_id}/check", response_class=HTMLResponse)
async def step4_check(request: Request, word_id: str, choice: str = Form(...)):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    tpl = PRACTICE[w["category_id"]]
    correct_label = next(o["label"] for o in tpl["options"] if o["correct"])
    correct = (choice == correct_label)
    completed = tpl["frame"].replace("{word}", w["word"]).replace("[ ？ ]", "〈" + correct_label + "〉")

    option_results = [{
        "label": o["label"], "meaning": o["meaning"],
        "is_correct": o["correct"], "is_chosen": (o["label"] == choice),
    } for o in tpl["options"]]

    record("Step4", w, correct)

    return templates.TemplateResponse(request, "step4_result.html", {
        "word": w, "category": cat, "correct": correct,
        "correct_label": correct_label, "completed": completed,
        "option_results": option_results, "explain": tpl["explain"], "score": score_data,
    })


@app.get("/reset")
async def reset():
    global score_data
    score_data["correct"] = 0
    score_data["wrong"] = 0
    score_data["history"] = []
    return RedirectResponse("/")
