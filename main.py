# main.py
# オノマトペ学習支援システム
#   語を1つ選んだら、その語でフェーズ1〜3を通して学ぶ。
#     /                       出題対象16語の一覧（語を選ぶのはここだけ）
#     /word/{id}              その語の学習マップ（3フェーズの現在地）
#     /word/{id}/f1/1〜5      フェーズ1：意味 → 音の形 → 継続性 → 動作性 → 意志性
#     /word/{id}/f1/done      フェーズ1のまとめ（カテゴリー確定）
#     /reference             学習前：素性・表現形式・前接条件を学ぶ
#     /word/{id}/f2           フェーズ2：線結び
#     /word/{id}/f3           フェーズ3：例文の練習
#     /word/{id}/complete     この語の学習完了
#   語に紐づかない補助：/drill/features・/drill/expressions・/reference
#
# 2026-09 改修の中心：
#   表現形式の前接条件を素性の集合として持ち、○×の判定と誤答フィードバックを
#   「どの素性が条件を満たさないか」から自動生成する（feedback engine）。
import random
import json
import uuid
import math
import study_logging
import research
import hashlib
import learning_state
import deferred_logging
from urllib.parse import urlencode
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import init_db
from database import load_all

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
research.install(app, templates)
deferred_logging.install(app, templates)

# Neutral participant URLs map to stable researcher-only group names.
STUDY_GROUPS = {"/a": "experiment", "/b": "control"}
LEGACY_PREFIXES = {"/experiment": "/a", "/control": "/b"}

# Group is carried in the URL, so tabs in different groups cannot overwrite it.
@app.middleware("http")
async def study_context(request: Request, call_next):
    path = request.scope["path"]
    legacy = next((p for p in LEGACY_PREFIXES
                   if path == p or path.startswith(p + "/")), "")
    if legacy:
        target = LEGACY_PREFIXES[legacy] + (path[len(legacy):] or "/")
        return RedirectResponse(target + ("?" + request.url.query if request.url.query else ""), status_code=307)
    prefix = next((p for p in STUDY_GROUPS
                   if path == p or path.startswith(p + "/")), "")
    if not prefix and not path.startswith("/static/"):
        return RedirectResponse("/a" + path +
                                ("?" + request.url.query if request.url.query else ""), status_code=307)
    request.scope["study_prefix"] = prefix
    if prefix:
        request.scope["path"] = path[len(prefix):] or "/"
        request.scope["raw_path"] = request.scope["path"].encode()
    cookie_name = "study_participant"
    participant = request.cookies.get(cookie_name, "")
    try:
        participant = str(uuid.UUID(participant))
    except (ValueError, AttributeError):
        participant = str(uuid.uuid4())
    if research.REQUIRE_NAME and prefix:
        participant = research.identity(request) or str(uuid.uuid4())
    request.state.participant = participant
    request.state.study_group = STUDY_GROUPS.get(prefix, "")
    request.state.study_label = {"/a": "A", "/b": "B"}.get(prefix, "")
    current_path = request.scope["path"]
    request.state.form_attempt_id = str(uuid.uuid4())
    request.state.require_name = research.REQUIRE_NAME
    request.state.answer_receipt = request.cookies.get("study_receipt_" + request.state.study_label.lower(), "")
    request.state.participant_name = None
    if prefix and not current_path.startswith("/research") and current_path != "/registration" and research.REQUIRE_NAME:
        request.state.participant_name = study_logging.participant_name(participant) if research.identity(request) else None
        if not request.state.participant_name:
            if current_path.startswith("/api/"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "registration required"}, status_code=401)
            return research.private(RedirectResponse(prefix + "/registration?" + urlencode({"next":path}),status_code=303))
    if request.state.study_group == "control":
        import re
        allowed_path = request.scope["path"] in ("/", "/api/events", "/api/finish", "/finish", "/registration") or re.fullmatch(r"/word/[^/]+(?:/meaning/check|/f3(?:/check)?|/complete)?", request.scope["path"])
        if not allowed_path:
            return HTMLResponse('このページは今回の学習内容に含まれません。<a href="/b/">ホームへ</a>', status_code=404)
    if prefix and research.REQUIRE_NAME and request.method == "POST" and current_path.startswith(("/word/", "/drill/")):
        await request.body()
        learner_form = await request.form()
        if learner_form.get("_study_participant") != participant:
            from fastapi.responses import JSONResponse
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"error":"participant changed", "message":"利用者が変わりました。画面を読み込み直してください。"},status_code=409)
            return research.private(HTMLResponse('利用者が変わりました。画面を読み込み直してください。<a href="'+prefix+'/">ホームから開き直す</a>',status_code=409))
    submission = None
    if prefix and request.method == "POST" and request.scope["path"].endswith("/check"):
        # Save submitted selections, never arbitrary form text or personal information.
        await request.body()
        form = await request.form()
        choices = {k: str(v)[:200] for k, v in form.multi_items()
                   if k == "choice" or k.startswith(("choice_", "opt_keys_", "spec_", "q_")) or k in EXPR_BY_KEY}
        result = {"answers": choices}
        parts = request.scope["path"].strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "word" and parts[1] in WORD_BY_ID:
            word = WORD_BY_ID[parts[1]]
            cat = get_category(word)
            if parts[2] == "meaning":
                result["correct"] = choices.get("choice") == word["id"]
            elif parts[2] == "f1" and len(parts) == 5 and parts[3].isdigit() and 1 <= int(parts[3]) <= 5:
                result["correct"] = chain_feedback(word, int(parts[3]), choices.get("choice", ""))["ok"]
            elif parts[2] == "f2":
                result["correct_by_expression"] = {e["key"]: (choices.get(e["key"]) == "○") == expr_combines(cat, e) for e in EXPRESSIONS}
            elif parts[2] == "f3":
                result["correct_by_question"] = {str(q["ord"]): choices.get(f'choice_{q["ord"]}') == q["correct_key"] for q in PRACTICE.get(word["id"], [])}
        elif request.scope["path"] == "/drill/features/check":
            graded, _ = grade_feature_questions(form)
            result["correct_by_question"] = {str(i+1):r["ok"] for i,r in enumerate(graded)}
        elif request.scope["path"] == "/drill/expressions/check":
            checks = {}
            for key in choices:
                if not key.startswith("spec_"):
                    continue
                i = key[5:]; spec = choices[key]; choice = choices.get("choice_"+i, "")
                e = EXPR_BY_KEY.get(spec[2:])
                if e and spec.startswith("x:"):
                    checks[i] = choice == e["cond_text"]
                elif e and spec.startswith("y:"):
                    chosen = get_word(choice)
                    checks[i] = bool(chosen) and expr_combines(get_category(chosen), e)
            result["correct_by_question"] = checks
        source = str(form.get("_study_path", ""))[:300].split("?",1)[0]
        if not source.startswith(prefix + "/") or source.startswith("//"):
            source = path.removesuffix("/check")
        result["source_path"] = source
        def metric(key):
            try:
                value = float(form.get(key,0))
                return max(0,min(value,86400000)) if math.isfinite(value) else 0
            except (ValueError,TypeError):
                return 0
        elapsed = metric("_study_elapsed_ms")
        result["active_ms"] = min(metric("_study_active_ms"), elapsed)
        result["click_count"] = min(metric("_study_click_count"),100000)
        page_id = str(form.get("_study_page_id", ""))[:80]
        attempt_id = str(form.get("attempt_id", ""))[:120] or str(uuid.uuid4())
        # The same POST refreshed/retried is one attempt; a changed answer is distinct.
        fingerprint = hashlib.sha256(json.dumps(choices,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        submission = (result, participant + ":" + request.state.study_group + ":answer:" + attempt_id + ":" + fingerprint, page_id, elapsed)
    if submission:
        result, event_id, page_id, elapsed = submission
        request.state.answer_receipt = deferred_logging.receipt(participant,request.state.study_group,path,result,event_id,page_id,elapsed)
    response = await call_next(request)
    if submission and response.status_code < 400:
        result, event_id, page_id, elapsed = submission
        response.headers['X-Study-Receipt'] = request.state.answer_receipt
        if 300<=response.status_code<400:
            response.set_cookie('study_receipt_'+request.state.study_label.lower(),request.state.answer_receipt,
                                httponly=False,samesite='lax',secure=research.secure_cookie(request),max_age=600)
    elif request.state.answer_receipt and response.status_code==200:
        response.delete_cookie('study_receipt_'+request.state.study_label.lower())
    if prefix and request.scope["path"].startswith("/research"):
        research.private(response)
    elif prefix:
        response.headers["Cache-Control"] = "no-store"
    location = response.headers.get("location", "")
    if prefix and location.startswith("/") and not any(location == p or location.startswith(p + "/") for p in (*STUDY_GROUPS, "/static")):
        response.headers["location"] = prefix + location
    if prefix:
        response.set_cookie(cookie_name, participant, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https", max_age=60*60*24*30)
    return response

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
    "action": "感情・感覚では、一瞬の変化か続く状態かを区別します。動作では、具体的な動きや力の抜け方も手がかりにします。",
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
def word_groups():
    return [{"category": c, "words": [w for w in WORDS if w["category_id"] == c["id"]]}
            for c in CATEGORIES]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "control_index.html" if request.state.study_group == "control" else "index.html", {
        "total": len(WORDS), "groups": word_groups(), "chain": CHAIN, "words": WORDS,
    })


# =====================================================================
#  フェーズ1：素性の学習
# =====================================================================
def build_phon_table():
    """音韻形態 × 素性の対応表（予測できない素性は「—」、予測と違う語は例外として列挙）"""
    table = []
    for p in PHON_DEFS:
        # 語ごとにまとめる（「ゆっくり（継続性）・ゆっくり（動作性）」と重複させない）
        by_word = {}
        for w in WORDS:
            if w["phon"] != p["key"]:
                continue
            cat = CAT_BY_ID[w["category_id"]]
            for fkey in ("continuity", "action"):
                pred = p[PRED_COL[fkey]]
                if pred and cat[fkey] != pred:
                    by_word.setdefault(w["word"], []).append(FEATURE_NAME[fkey])
        exceptions = [f'{word}（{"・".join(feats)}）' for word, feats in by_word.items()]
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

# 音韻形態 → その「音のかたち」を示す図
PHON_FIGS = {
    "repeat": "phon_repeat.svg",
    "repeat_var": "phon_repeat_var.svg",
    "qri": "phon_qri.svg",
    "nri": "phon_nri.svg",
    "q": "phon_q.svg",
}

# 選択肢に添える短い説明
FEATURE_OPTION_NOTES = {
    "continuity": {
        "＋": "その状態・動きが時間幅をもって続く",
        "変化結果の＋": "変化は一度きり。そのあと結果の状態が残る",
        "ー": "一瞬で成立し、あとに残らない",
    },
    "action": {
        "高": "具体的な動き、または一瞬の強い変化・刺激",
        "中": "動きが激しくない状態や、続く気持ち・感覚",
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
                    "fig": PHON_FIGS.get(p["key"]), "example": "・".join(ex)})
    return out


def _chip(cap, val, sub=None, fig=None):
    """連鎖の可視化で使う小カード（確定した事実／問う素性）"""
    return {"cap": cap, "val": val, "sub": sub, "fig": fig}


def chain_question(w, k):
    """k番目の問い。前の段で確定したことを図で示し、次に問う素性へつなげる。

    文章での説明はやめ、「確定した事実 →（関係）→ 次に問う素性」を
    小カードと矢印で見せる（テンプレート側の .flow）。
    """
    cat = get_category(w)
    phon = PHON_BY_KEY[w["phon"]]
    step = CHAIN_BY_K[k]

    cont_chip = _chip("継続性", val_label("continuity", cat["continuity"]),
                      fig=FEATURE_FIGS["continuity"][cat["continuity"]])
    act_chip = _chip("動作性", val_label("action", cat["action"]),
                     fig=FEATURE_FIGS["action"][cat["action"]])

    if k == 1:
        return {"step": step, "kind": "meaning",
                "flow": {"known": [_chip("学習する語", f'「{w["word"]}」')],
                         "why": "場面から読みとる",
                         "ask": {"cap": "意味"}},
                "prompt": f'この場面の「{w["word"]}」に最も近い意味はどれ？',
                "meaning_opts": meaning_options(w)}

    if k == 2:
        return {"step": step, "kind": "phon",
                "flow": {"known": [_chip("意味", w["meaning"])],
                         "why": "音の形にも手がかりがある",
                         "ask": {"cap": "音の形"}},
                "prompt": f'「{w["word"]}」はどの音韻形態？',
                "phon_opts": phon_options(w)}

    if k == 3:
        return {"step": step, "kind": "feature", "fkey": "continuity",
                "flow": {"known": [_chip("音の形", phon["label"], phon["term"],
                                         fig=PHON_FIGS.get(phon["key"]))],
                         "why": phon["hint"],
                         "ask": {"cap": "継続性"}},
                "prompt": f'「{w["word"]}」の継続性は？',
                "options": feature_options("continuity")}

    if k == 4:
        return {"step": step, "kind": "feature", "fkey": "action",
                "flow": {"known": [cont_chip],
                         "why": "続き方 ＋ 動き・感覚に注目",
                         "ask": {"cap": "動作性"}},
                "prompt": f'「{w["word"]}」の動作性は？',
                "options": feature_options("action")}

    return {"step": step, "kind": "feature", "fkey": "volition",
            "flow": {"known": [cont_chip, act_chip],
                     "why": "「今から〜しよう」と言える？",
                     "ask": {"cap": "意志性"}},
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


def learner_state(request, word_id):
    return learning_state.read(request.state.participant, request.state.study_group, word_id)


def update_learner(request, word_id, change):
    return learning_state.update(request.state.participant, request.state.study_group, word_id, change)


def active_context_review(state, token):
    """Show remediation only within the return flow issued by an actual error."""
    return bool(token and token == state.get("context_review_token") and state.get("context_review"))


def clear_context_review(state):
    state.update(context_review=[], context_review_token="")


def review_target(value, k):
    """A review can return only to a later question in the same word's chain."""
    try:
        target = int(value)
    except (TypeError, ValueError):
        return None
    return target if k < target <= len(CHAIN) else None


def chain_next_url(word_id, k, review_for=None):
    if k == len(CHAIN):
        return f"/word/{word_id}/f1/done"
    url = f"/word/{word_id}/f1/{k + 1}"
    if review_for and k + 1 < review_for:
        url += f"?review_for={review_for}"
    return url


def chain_review_url(word_id, k, review_for=None):
    review_k = max(1, k - 1)
    url = f"/word/{word_id}/f1/{review_k}"
    if k > 1:
        url += f"?review_for={review_for or k}"
    return url


def chain_retry_feedback(w, k, choice):
    """One word-specific sentence; diagrams describe only the learner's selection."""
    word = f'「{w["word"]}」'
    if k == 1:
        chosen = get_word(choice)
        message = (f'「{chosen["meaning"]}」に近いオノマトペは「{chosen["word"]}」です。もう一度選んでみましょう。'
                   if chosen else '意味をもう一度選んでみましょう。')
        return {"message": message, "fig": None}
    if k == 2:
        chosen = PHON_BY_KEY.get(choice)
        message = (f'{chosen["label"]}の並びと{word}の並びは一致しません。'
                   if chosen else f'{word}の音の並びに合う形を選んでみましょう。')
        return {"message": message, "fig": None}
    fkey = {3: "continuity", 4: "action", 5: "volition"}[k]
    message = {
        3: f'{word}の続き方（続く・結果が残る・一瞬）を考え、音の形に戻って継続性を選び直しましょう。',
        4: f'{word}がどのような動き・変化・状態を表すかを考え、継続性に戻って動作性を選び直しましょう。',
        5: f'{word}を自分の意志で始めたりやめたりできるかを考え、動作性に戻って意志性を選び直しましょう。',
    }[k]
    return {"message": message, "fig": FEATURE_FIGS[fkey].get(choice)}


@app.get("/word/{word_id}", response_class=HTMLResponse)
async def word_map(request: Request, word_id: str):
    """その語の学習マップ。フェーズ1〜3のどこにいるかを示す。"""
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    if request.state.study_group == "control":
        return templates.TemplateResponse(request, "control_meaning.html", {
            "word": w, "question": chain_question(w, 1), "feedback": None})
    idx = [x["id"] for x in WORDS].index(w["id"])
    return templates.TemplateResponse(request, "word_map.html", {
        "word": w, "chain": CHAIN,
        "n": idx + 1, "total": len(WORDS),
        "next_word": WORDS[idx + 1] if idx + 1 < len(WORDS) else None,
    })


@app.post("/word/{word_id}/meaning/check", response_class=HTMLResponse)
async def control_meaning_check(request: Request, word_id: str):
    w = get_word(word_id)
    if not w or request.state.study_group != "control":
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    return templates.TemplateResponse(request, "control_meaning.html", {
        "word": w, "question": None,
        "feedback": chain_feedback(w, 1, form.get("choice", "")),
        "retry_feedback": chain_retry_feedback(w, 1, form.get("choice", ""))})

@app.get("/reference", response_class=HTMLResponse)
async def reference(request: Request):
    return templates.TemplateResponse(request, "phase1_summary.html", {
        "knowledge": KNOWLEDGE,
        "categories": CATEGORIES,
        "phon_table": build_phon_table(),
        "figs": FEATURE_FIGS,
        "expr_cards": expression_cards(),
        "expr_guide": KNOWLEDGE["expr_guide"],
        "expr_note": KNOWLEDGE["expr_note"],
    })


@app.get("/word/{word_id}/f1/done", response_class=HTMLResponse)
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



@app.get("/word/{word_id}/f1/{k}", response_class=HTMLResponse)
async def phase1_chain(request: Request, word_id: str, k: int):
    w = get_word(word_id)
    if not w or k not in CHAIN_BY_K:
        return RedirectResponse("/phase1")
    return templates.TemplateResponse(request, "phase1_chain.html", {
        "word": w, "chain": CHAIN, "k": k,
        "q": chain_question(w, k),
        "attempt_id": str(uuid.uuid4()),
        "review_for": review_target(request.query_params.get("review_for"), k),
        "failures": learner_state(request, word_id).get("feature_failures", {}).get(str(k), 0),
    })


@app.post("/word/{word_id}/f1/{k}/check", response_class=HTMLResponse)
async def phase1_chain_check(request: Request, word_id: str, k: int):
    w = get_word(word_id)
    if not w or k not in CHAIN_BY_K:
        return RedirectResponse("/phase1")
    form = await request.form()
    choice = form.get("choice", "")
    fb = chain_feedback(w, k, choice)
    outcome = learning_state.feature_attempt(request.state.participant, request.state.study_group,
        word_id, k, fb["ok"], str(form.get("attempt_id") or uuid.uuid4())[:80] + ":" + str(choice)[:80])
    # A browser refresh of the same POST is not another failed attempt.
    fb["ok"] = outcome["ok"]
    review_for = review_target(form.get("review_for"), k)
    retry_url = f"/word/{word_id}/f1/{k}" + (f"?review_for={review_for}" if review_for else "")
    review_k = max(1, k - 1)
    review_url = chain_review_url(word_id, k, review_for)
    return templates.TemplateResponse(request, "phase1_chain_result.html", {
        "word": w, "chain": CHAIN, "k": k,
        "step": CHAIN_BY_K[k],
        "fb": fb if fb["ok"] else {"ok": False, "user": fb["user"]},
        "retry_feedback": chain_retry_feedback(w, k, choice),
        "failures": outcome["failures"], "review_for": review_for,
        "retry_url": retry_url, "review_url": review_url,
        "review_title": CHAIN_BY_K[review_k]["title"] if k > 1 else "場面",
        "next_url": chain_next_url(word_id, k, review_for),
        "next_k": k + 1 if k < len(CHAIN) else None,
    })


@app.post("/word/{word_id}/f1/{k}/continue")
async def phase1_chain_continue(request: Request, word_id: str, k: int):
    if not get_word(word_id) or k not in CHAIN_BY_K:
        return RedirectResponse("/", status_code=303)
    # Legacy forms must never reveal an answer or skip an unconfirmed question.
    return RedirectResponse(f"/word/{word_id}/f1/{k}", status_code=303)



@app.get("/drill/features", response_class=HTMLResponse)
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


@app.post("/drill/features/check", response_class=HTMLResponse)
async def phase1_drill_check(request: Request):
    form = await request.form()
    results, n_correct = grade_feature_questions(form)
    return templates.TemplateResponse(request, "phase1_drill_result.html", {
        "results": results, "n_correct": n_correct, "total": len(results),
    })


# =====================================================================
#  学習前の知識：文法形式と前接条件
# =====================================================================
def expression_cards():
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

    return expr_cards


@app.get("/word/{word_id}/f2/learn")
async def f2_learn(word_id: str):
    """Keep old bookmarks pointing at the relocated introductory knowledge."""
    if not get_word(word_id):
        return RedirectResponse("/")
    return RedirectResponse("/reference#grammar", status_code=303)


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


@app.get("/drill/expressions", response_class=HTMLResponse)
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


@app.post("/drill/expressions/check", response_class=HTMLResponse)
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
# =====================================================================
#  Step3：文法形式との線結び（局面別グループ＋段階ヒント）
# =====================================================================
@app.get("/word/{word_id}/f2", response_class=HTMLResponse)
async def f2_match(request: Request, word_id: str):
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

    state = learner_state(request, word_id)
    review_token = request.query_params.get("review", "")
    reviewing = active_context_review(state, review_token)
    if not reviewing and state.get("context_review"):
        state = update_learner(request, word_id, clear_context_review)
    retry_token = request.query_params.get("retry", "")
    retrying = bool(retry_token and retry_token == state.get("matching_retry_token"))
    if not retrying and (state.get("connections") or state.get("matching_retry_token")):
        state = update_learner(request, word_id, lambda s: s.update(connections=[], matching_retry_token=""))
    return templates.TemplateResponse(request, "step3.html", {
        "word": w,
        "word_hint": profile_str(cat),
        "expr_groups": groups,
        "expressions": EXPRESSIONS,
        "saved_connections": state.get("connections", []) if retrying else [],
        "context_review": state.get("context_review", []) if reviewing else [],
        "review_token": review_token if reviewing else "",
    })


@app.post("/word/{word_id}/f2/check", response_class=HTMLResponse)
async def f2_check(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    cat = get_category(w)
    form = await request.form()

    expr_results = []
    n_expr_correct = 0
    for e in EXPRESSIONS:
        fb = expr_feedback(w, cat, e)
        can_combine = fb["ok"]
        user_connected = (form.get(e["key"]) == "○")
        ok = (can_combine == user_connected)
        n_expr_correct += 1 if ok else 0
        expr_results.append({
            "key": e["key"],
            "label": e["label"], "phase": e["phase"], "cond_text": e["cond_text"],
            "checks": fb["checks"],
            "comparison": [next((c for c in fb["checks"] if c["key"] == fkey), {
                "name": FEATURE_NAME[fkey], "actual": val_label(fkey, cat[fkey]),
                "req": "制限なし", "ok": True, "unrestricted": True,
            }) for fkey in ("continuity", "action", "volition")],
            "should": can_combine, "connected": user_connected, "ok": ok,
            "headline": fb["headline"], "lines": fb["lines"],
            "no_cond": fb["no_cond"],
            "example": e["ok_example"] if can_combine else e["ng_example"],
        })

    all_correct = (n_expr_correct == len(EXPRESSIONS))
    retry_token = str(uuid.uuid4()) if not all_correct else ""
    state = update_learner(request, word_id, lambda s: s.update(
        connections=[r["key"] for r in expr_results if r["connected"]] if not all_correct else [],
        matching_retry_token=retry_token))
    review_token = str(form.get("review_token", ""))
    reviewing = active_context_review(state, review_token)
    if not reviewing and state.get("context_review"):
        state = update_learner(request, word_id, clear_context_review)
    review_query = f"?review={review_token}" if reviewing else ""
    retry_params = {"review": review_token} if reviewing else {}
    if retry_token:
        retry_params["retry"] = retry_token
    retry_query = "?" + urlencode(retry_params) if retry_params else ""
    feedback_context = {
        "request": request,
        "word": w, "category": cat,
        "profile": profile_str(cat),
        "expr_results": expr_results,
        "n_expr_correct": n_expr_correct, "total_expr": len(EXPRESSIONS),
        "expr_explain": cat["expr_explain"],
        "all_correct": all_correct,
        "extra_results": [r for r in expr_results if r["connected"] and not r["should"]],
        "has_missing": any(r["should"] and not r["connected"] for r in expr_results),
        "context_review": state.get("context_review", []) if reviewing else [],
        "retry_url": f"/word/{word_id}/f2{retry_query}",
        "context_url": f"/word/{word_id}/f3{review_query}",
    }
    if "application/json" in request.headers.get("accept", ""):
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "all_correct": all_correct,
            "invalid_keys": [r["key"] for r in feedback_context["extra_results"]],
            "invalid_conditions": {r["key"]: r["cond_text"] for r in feedback_context["extra_results"]},
            "has_missing": feedback_context["has_missing"],
            "feedback_html": templates.env.get_template("_matching_feedback.html").render(
                {**feedback_context, "inline_feedback": True}),
            "context_url": request.scope.get("study_prefix", "") + feedback_context["context_url"],
        })
    return templates.TemplateResponse(request, "step3_result.html", feedback_context)


# =====================================================================
#  Step4：例文の練習（語ごとの自然文＋誤答は素性条件を満たさない形から自動生成）
# =====================================================================
FORM_COL = {"base": "form_base", "past": "form_past"}


def step4_build(w, n_distractors=2, saved_options=None):
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
        saved = (saved_options or {}).get(str(q["ord"]), [])
        if (len(saved) == len(set(saved)) == len(opts) and q["correct_key"] in saved
                and all(k in EXPR_BY_KEY and (k == q["correct_key"] or k not in ok_keys) for k in saved)):
            opts = [{"key": k, "label": EXPR_BY_KEY[k][col], "phase": EXPR_BY_KEY[k]["phase"]} for k in saved]
        questions.append({
            "idx": q["ord"], "text": q["frame"], "options": opts,
            "correct_key": correct["key"],
            "opt_keys": ",".join(o["key"] for o in opts),
            "form": q["form"],
        })
    return questions


@app.get("/word/{word_id}/f3", response_class=HTMLResponse)
async def f3(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    if request.state.study_group == "control":
        return templates.TemplateResponse(request, "control_context.html", {
            "word": w, "questions": step4_build(w),
        })
    cat = get_category(w)
    state = learner_state(request, word_id)
    returning = active_context_review(state, request.query_params.get("review", ""))
    questions = step4_build(w, saved_options=state.get("context_options") if returning else None)

    def prepare(s):
        s["context_options"] = {str(q["idx"]): [o["key"] for o in q["options"]] for q in questions}
        if not returning:
            clear_context_review(s)
            s["context_choices"] = {}

    state = update_learner(request, word_id, prepare)
    return templates.TemplateResponse(request, "step4.html", {
        "word": w, "questions": questions,
        "word_hint": profile_str(cat),
        "saved_choices": state.get("context_choices", {}),
        "returning": returning,
        "matching_url": f"/word/{word_id}/f2" + (f"?review={state['context_review_token']}" if returning else ""),
    })


@app.post("/word/{word_id}/f3/check", response_class=HTMLResponse)
async def f3_check(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    if request.state.study_group == "control":
        form = await request.form()
        results = []
        for q in PRACTICE.get(w["id"], []):
            col = FORM_COL.get(q["form"], "form_base")
            correct = EXPR_BY_KEY[q["correct_key"]]
            choice = form.get(f'choice_{q["ord"]}', "")
            selected = EXPR_BY_KEY.get(choice)
            results.append({
                "no": q["ord"] + 1,
                "ok": choice == q["correct_key"],
                "user_label": selected[col] if selected else "（未選択）",
                "correct_label": correct[col],
                "completed": q["frame"].replace("[ ？ ]", "〈" + correct[col] + "〉"),
            })
        return templates.TemplateResponse(request, "control_context_result.html", {
            "word": w, "results": results,
            "n_correct": sum(r["ok"] for r in results), "total": len(results),
        })
    cat = get_category(w)
    form = await request.form()

    results = []
    review = []
    saved_choices = {}
    for q in PRACTICE.get(w["id"], []):
        i = q["ord"]
        col = FORM_COL.get(q["form"], "form_base")
        choice = form.get(f"choice_{i}", "")
        correct = EXPR_BY_KEY[q["correct_key"]]
        ok = (choice == correct["key"])
        selected = EXPR_BY_KEY.get(choice)
        saved_choices[str(i)] = choice if selected else ""
        if not ok:
            mismatches = [c["name"] for c in expr_checks(cat, selected) if not c["ok"]] if selected else []
            review.append({"no": i + 1, "frame": q["frame"],
                           "choice": selected[col] if selected else "未選択",
                           "reason": ("前接条件と合わない素性：" + "・".join(mismatches)) if mismatches
                                     else "語の素性・前接条件と、文中の時間表現を見直しましょう。"})
        results.append({
            "no": i + 1, "ok": ok,
            "completed": q["frame"].replace("[ ？ ]", "〈" + correct[col] + "〉"),
            "label": correct[col], "phase": correct["phase"],
        })
    review_token = str(uuid.uuid4()) if review else ""
    update_learner(request, word_id, lambda s: s.update(
        context_review=review, context_review_token=review_token, context_choices=saved_choices,
        connections=[], matching_retry_token=""))
    if review:
        # No completed sentence or correct option is rendered on an error.
        return RedirectResponse(f"/word/{word_id}/f2?review={review_token}", status_code=303)
    return templates.TemplateResponse(request, "step4_result.html", {
        "word": w, "category": cat, "profile": profile_str(cat),
        "all_correct": True,
        "n_correct": len(results), "total": len(results),
        "results": results,
    })


# =====================================================================
#  この語の学習完了
# =====================================================================
@app.get("/word/{word_id}/complete", response_class=HTMLResponse)
async def word_complete(request: Request, word_id: str):
    w = get_word(word_id)
    if not w:
        return RedirectResponse("/")
    if request.state.study_group == "control":
        idx = [x["id"] for x in WORDS].index(w["id"])
        return templates.TemplateResponse(request, "control_complete.html", {
            "word": w,
            "next_word": WORDS[idx + 1] if idx + 1 < len(WORDS) else None,
        })
    cat = get_category(w)
    ok_keys = CAT_EXPRS.get(cat["id"], set())
    idx = [x["id"] for x in WORDS].index(w["id"])
    return templates.TemplateResponse(request, "complete.html", {
        "word": w, "category": cat, "profile": profile_str(cat), "chain": CHAIN,
        "phon": PHON_BY_KEY[w["phon"]],
        "figs": FEATURE_FIGS,
        "ok_exprs": [e for e in EXPRESSIONS if e["key"] in ok_keys],
        "ng_exprs": [e for e in EXPRESSIONS if e["key"] not in ok_keys],
        "n": idx + 1, "total": len(WORDS),
        "next_word": WORDS[idx + 1] if idx + 1 < len(WORDS) else None,
    })


# =====================================================================
#  旧URLからのリダイレクト（ブックマークを壊さない）
# =====================================================================
@app.get("/phase1")
@app.get("/phase2")
@app.get("/phase3")
async def redirect_phases():
    return RedirectResponse("/")


@app.get("/phase1/summary")
async def redirect_summary():
    return RedirectResponse("/reference")


@app.get("/phase1/drill")
async def redirect_drill1():
    return RedirectResponse("/drill/features")


@app.get("/phase2/drill")
async def redirect_drill2():
    return RedirectResponse("/drill/expressions")


@app.get("/phase1/word/{word_id}/{k}")
async def redirect_chain(word_id: str, k: str):
    return RedirectResponse(f"/word/{word_id}/f1/{k}")


@app.get("/step3/{word_id}")
async def redirect_step3(word_id: str):
    return RedirectResponse(f"/word/{word_id}/f2")


@app.get("/step4/{word_id}")
async def redirect_step4(word_id: str):
    return RedirectResponse(f"/word/{word_id}/f3")
