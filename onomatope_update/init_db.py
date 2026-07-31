# init_db.py
# 「学習支援データ.docx」の整理データを SQLite データベースに投入するスクリプト
# 実行方法: python init_db.py  →  onomatopoeia.db が生成される
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "onomatopoeia.db")


# =====================================================================
#  1. 知識データ（ホーム画面・学習提示用）
# =====================================================================
KNOWLEDGE = [
    # (section, ord, label, body, fig)
    ("continuity", 1, "継続性（＋）",
     "動き・状態の継続の場合。感情や状態が時間幅をもって続きます。", "cont_plus.svg"),
    ("continuity", 2, "変化結果の継続性（＋）",
     "瞬間的な変化は一度起こるが、その結果の状態が続くもの。", "result_plus.svg"),
    ("continuity", 3, "継続性（ー）",
     "瞬時の感情や感覚の変化・性格や容姿などの属性。一瞬で成立し、続きません。", "cont_minus.svg"),

    ("action", 1, "動作性（高）",
     "ある瞬間に変化や刺激が発生する → 継続性（ー）", None),
    ("action", 2, "動作性（中）",
     "感情・感覚・状態を表すが、時間の継続がある → 継続性（＋）、変化結果の継続性（＋）", None),
    ("action", 3, "動作性（低）",
     "動作性が低いもの（だらだら・のんびり など）", None),
    ("action", 4, "動作性（ー）",
     "動作性がないもの", None),

    ("volition", 1, "意志性（＋）",
     "動作主が自分の意志で行うことができる動き・行為を表す。", None),
    ("volition", 2, "意志性（ー）",
     "自分の意志で起こすことができない感情・感覚・状態を表す。", None),

    ("rule", 1, "継続性と動作性の関係",
     "継続性が低いほど、動作性が高くなる。（一瞬の変化＝動作性「高」／続く状態＝動作性「中」）", None),

    # --- 音韻形態と素性の関係 ---
    ("phon_feature", 1, "2モーラ反復形（ABAB）→ ＋継続性",
     "くり返しのリズムが「続くこと」を写し取る → ＋継続性。感情・感覚なら動作性（中）、動作なら動作性（中〜高）になりやすい（例：いらいら・ぶらぶら・きらきら）。", None),
    ("phon_feature", 2, "2モーラ反復形の変種 → ＋継続性・動作性（高）",
     "不規則なくり返しが「乱れた動き」を写す → ＋継続性で、動作性が高くなりやすい（例：あたふた・うろちょろ・どぎまぎ）。", None),
    ("phon_feature", 3, "「っ＋り」型（CVQCVri）→ 変化結果／低動作",
     "促音「っ」の区切れ＋「り」の余韻が「変化とその結果」を写す → ＋変化結果の継続性（例：びっくり・がっかり）。低動作の状態を表すものもある（例：ぐったり・ゆっくり）。", None),
    ("phon_feature", 4, "「ん＋り」型（CVNCVri）→ 動作性（低）",
     "撥音「ん」のゆるみが「ゆったりした状態」を写す → ＋継続性・動作性（低）（例：のんびり・ぼんやり）。", None),
    ("phon_feature", 5, "「っ」で終わる型（CVQ・CVCVQ）→ ー継続性",
     "促音の切れが「一瞬の変化」を写す → ー継続性・動作性（高）（例：いらっ・ずきっ）。※一部は結果が残る変化結果型（例：ほっ）。", None),

    # --- 線結び（文法形式の判断）の考え方 ---
    ("expr_guide", 1, "手順① オノマトペの素性を確認する",
     "そのオノマトペの継続性・動作性・意志性を思い出す（フェーズ1で学んだ判断）。", None),
    ("expr_guide", 2, "手順② 表現形式の「前接条件」を見る",
     "各表現形式には「＋継続性が必要」「動作性（高）が必要」のような条件がある。", None),
    ("expr_guide", 3, "手順③ 条件を満たすか照合する",
     "表現形式が必要とする素性を、オノマトペがすべて持っていれば「結びつく」。1つでも欠けていれば「結びつかない」。", None),
]


# =====================================================================
#  2. 音韻形態（田守・スコウラップ 1999 より作成）
# =====================================================================
PHON_FORMS = [
    # (key, ord, label, term, example, hint)
    ("repeat",     1, "2モーラ反復形（ABAB）",       "CVCV-CVCV",
     "いらいら・わくわく・きらきら・ごろごろ", "継続する状態・動作を表しやすい"),
    ("repeat_var", 2, "2モーラ反復形の変種",          "ABCD型の反復",
     "うろちょろ・あたふた・どぎまぎ・ぎくしゃく", "不規則な反復で、乱れた動きを表しやすい"),
    ("qri",        3, "「っ＋り」型",                "CVQCVri形",
     "びっくり・がっかり・ぐったり・ゆっくり", "変化結果や低動作の状態を表しやすい"),
    ("nri",        4, "「ん＋り」型",                "CVNCVri形",
     "ぼんやり・のんびり", "ゆるやかで低動作の状態を表しやすい"),
    ("q",          5, "「っ」で終わる型",             "CVQ・CVCVQ形",
     "ほっ・いらっ・ずきっ・ちくっ", "瞬間的な変化を表しやすい（一部は変化結果型）"),
]


# =====================================================================
#  3. 8つのカテゴリー
# =====================================================================
CATEGORIES = [
    # (id, ord, name, kind, continuity, action, volition, profile_text, expr_explain)
    ("emo_cont", 1, "感情・感覚表現（継続性があるもの）", "感情・感覚",
     "＋", "中", "ー",
     "{＋直接感覚、＋継続性、動作性（中）、ー意志性}",
     "＋継続性・動作性（中）を持つため、開始を表す「しはじめる・しだす」、状態の出現を表す「してくる」、最中を表す「しているところだ」、そして「してしまう」と結びつきます。"),
    ("emo_result", 2, "感情・感覚表現（変化結果の継続性があるもの）", "感情・感覚",
     "変化結果の＋", "中", "ー",
     "{＋直接感覚、＋変化結果の継続性、動作性（中）、ー意志性}",
     "＋変化結果の継続性を持つため、結果の最中を表す「しているところだ」、完了直後を表す「したところだ」、「してしまう」と結びつきます。"),
    ("emo_moment", 3, "感情・感覚表現（継続性がないもの）", "感情・感覚",
     "ー", "高", "ー",
     "{ー直接感覚、ー継続性、動作性（高）、ー意志性}",
     "ー継続性（一瞬で成立）のため、開始・継続を表す形式とは結びつかず、「してしまう」のみと結びつきます。"),
    ("act_high_vol", 4, "動作性が高いもの（意志性があるもの）", "動作",
     "＋", "高", "＋",
     "{ー直接感覚、＋継続性、動作性（高）、＋意志性}",
     "動作性（高）・＋意志性を持つため、「するところだ」「しようとする」など意志的な動作の形式に加え、「しはじめる」「しつづける」「しているところだ」「してしまう」と結びつきます。"),
    ("act_high_novol", 5, "動作性が高いもの（意志性が関わらないもの）", "動作",
     "＋", "高", "関与しない",
     "{ー直接感覚、＋継続性、動作性（高）}",
     "＋継続性・動作性（高）を持つため「しはじめる」「しだす」「しつづける」「しているところだ」「してしまう」と結びつきますが、意志性が関わらないため「するところだ」「しようとする」は使えません。"),
    ("act_mid", 6, "動作性が中程度のもの（継続性があるもの）", "動作",
     "＋", "中", "ー",
     "{ー直接感覚、＋継続性、動作性（中）、ー意志性}",
     "＋継続性・動作性（中）を持つため、「しはじめる」「しだす」「してくる」「しているところだ」「してしまう」と結びつきます。"),
    ("act_low_vol", 7, "動作性が低いもの（意志性があるもの）", "動作",
     "＋", "低", "＋",
     "{ー直接感覚、＋継続性、動作性（低）、＋意志性}",
     "動作性（低）のため開始・継続を表す形式とは結びつきにくく、「しているところだ」「してしまう」と結びつきます。"),
    ("act_low_novol", 8, "動作性が低いもの（意志性がないもの）", "動作",
     "＋", "低", "ー",
     "{ー直接感覚、＋継続性、動作性（低）、ー意志性}",
     "動作性（低）・ー意志性のため、「していく」「しているところだ」「してしまう」と結びつきます。"),
]


# =====================================================================
#  4. アスペクチュアリティーの表現形式（前接条件つき）
# =====================================================================
EXPRESSIONS = [
    # (key, ord, label, cond_text)
    ("surutokoroda",     1,  "するところだ",     "動作性（高）・＋意志性"),
    ("shiyoutosuru",     2,  "しようとする",     "動作性（高）・＋意志性"),
    ("shihajimeru",      3,  "しはじめる",       "＋継続性・動作性（中・高）"),
    ("shidasu",          4,  "しだす",           "＋継続性・動作性（中・高）"),
    ("shitekuru",        5,  "してくる",         "＋継続性・動作性（中）（状態の出現）"),
    ("shiteiku",         6,  "していく",         "＋継続性・ー動作性（長期的な変化・変化前に視点）"),
    ("shitsuzukeru",     7,  "しつづける",       "＋継続性・動作性（高）（具体的な動き）"),
    ("shiteirutokoroda", 8,  "しているところだ", "＋（変化結果の）継続性・動作性（低〜高）"),
    ("shitatokoroda",    9,  "したところだ",     "＋変化結果の継続性・動作性（中）"),
    ("shiteshimau",      10, "してしまう",       "±継続性・動作性（低〜高）"),
]

# カテゴリー × 結びつく表現（docx の「表現形式」欄より）
CATEGORY_EXPRESSIONS = {
    "emo_cont":       ["shihajimeru", "shidasu", "shitekuru", "shiteirutokoroda", "shiteshimau"],
    "emo_result":     ["shiteirutokoroda", "shitatokoroda", "shiteshimau"],
    "emo_moment":     ["shiteshimau"],
    "act_high_vol":   ["surutokoroda", "shiyoutosuru", "shihajimeru", "shitsuzukeru", "shiteirutokoroda", "shiteshimau"],
    "act_high_novol": ["shihajimeru", "shidasu", "shitsuzukeru", "shiteirutokoroda", "shiteshimau"],
    "act_mid":        ["shihajimeru", "shidasu", "shitekuru", "shiteirutokoroda", "shiteshimau"],
    "act_low_vol":    ["shiteirutokoroda", "shiteshimau"],
    "act_low_novol":  ["shiteiku", "shiteirutokoroda", "shiteshimau"],
}


# =====================================================================
#  5. オノマトペ本体（既存16語 + 動作オノマトペ23語）
# =====================================================================
WORDS = [
    # --- 感情・感覚表現（継続性があるもの） ---
    ("iraira",   "いらいら", "😣", "repeat", "emo_cont",
     "電車が遅れて、進まない列にずっと並んでいる", "思い通りにならず、不快な気持ちが続く"),
    ("wakuwaku", "わくわく", "🤩", "repeat", "emo_cont",
     "明日の旅行が楽しみで、気持ちが高ぶる", "期待で気持ちが高ぶり、落ち着かない"),
    ("hirihiri", "ひりひり", "🥵", "repeat", "emo_cont",
     "日焼けした肌が、さわると焼けるように痛む", "肌や傷が焼けるように痛む感覚が続く"),
    ("zukizuki", "ずきずき", "🤕", "repeat", "emo_cont",
     "頭が脈打つように痛みが続く", "脈打つように痛みがくり返し続く"),
    ("betabeta", "べたべた", "😖", "repeat", "emo_cont",
     "手にのりがついて、さわるものにくっつく", "表面が粘つく／くっついて離れない"),

    # --- 感情・感覚表現（変化結果の継続性があるもの） ---
    ("bikkuri", "びっくり", "😲", "qri", "emo_result",
     "後ろから急に声をかけられて、ハッと驚いた", "突然のことに驚く"),
    ("gakkari", "がっかり", "😞", "qri", "emo_result",
     "楽しみにしていた試合が中止になった", "期待が外れて落ち込む"),
    ("sukkiri", "すっきり", "😌", "qri", "emo_result",
     "悩みが解決して、気分が爽やかになった", "不快感が取れて気分が爽やかになる"),
    ("hotto",   "ほっ",     "😮‍💨", "q", "emo_result",
     "試験が終わって、緊張がとけて安心した", "緊張がとけて安心する"),

    # --- 感情・感覚表現（継続性がないもの） ---
    ("iratto",   "いらっ", "😠", "q", "emo_moment",
     "横入りされて、一瞬かっとなった", "一瞬、不快感や怒りがわく"),
    ("mukatto",  "むかっ", "😡", "q", "emo_moment",
     "失礼なことを言われた瞬間", "一瞬、強い怒りがこみ上げる"),
    ("zukitto",  "ずきっ", "😖", "q", "emo_moment",
     "立ち上がった瞬間、ひざに痛みが走った", "一瞬、鋭い痛みが走る"),
    ("kuratto",  "くらっ", "😵‍💫", "q", "emo_moment",
     "立ちくらみで、一瞬めまいがした", "一瞬、めまいがする"),
    ("furatto",  "ふらっ", "😵", "q", "emo_moment",
     "疲れていて、一瞬体がよろけた", "一瞬、体がよろける"),
    ("chikutto", "ちくっ", "😬", "q", "emo_moment",
     "注射の針が刺さった瞬間", "一瞬、針で刺すような痛みを感じる"),
    ("katto",    "かっ",   "🤬", "q", "emo_moment",
     "ばかにされて、一瞬頭に血がのぼった", "一瞬、かっと頭に血がのぼる"),

    # --- 動作性が高いもの（意志性があるもの） ---
    ("burabura", "ぶらぶら", "🚶", "repeat", "act_high_vol",
     "予定のない休日に、街を気ままに歩き回る", "あてもなく、気ままに歩き回るようす"),
    ("urouro",   "うろうろ", "🔄", "repeat", "act_high_vol",
     "道に迷って、同じ場所を行ったり来たりする", "行き先が定まらず歩き回るようす"),
    ("urochoro", "うろちょろ", "🐿️", "repeat_var", "act_high_vol",
     "子どもが部屋の中をあちこち動き回る", "落ち着きなくあちこち動き回るようす"),

    # --- 動作性が高いもの（意志性が関わらないもの） ---
    ("orooro",     "おろおろ",   "😨", "repeat", "act_high_novol",
     "突然のトラブルに、どうしていいかわからない", "うろたえて落ち着かないようす"),
    ("kyorokyoro", "きょろきょろ", "👀", "repeat", "act_high_novol",
     "初めての場所で、あたりを見回す", "落ち着きなくあたりを見回すようす"),
    ("magomago",   "まごまご",   "😕", "repeat", "act_high_novol",
     "乗り換えがわからず、その場で手間取る", "どうしてよいかわからず手間取るようす"),
    ("sowasowa",   "そわそわ",   "🪑", "repeat", "act_high_novol",
     "発表の順番が近づいて、落ち着かない", "気になることがあって落ち着かないようす"),
    ("dogimagi",   "どぎまぎ",   "😳", "repeat_var", "act_high_novol",
     "急に話しかけられて、あわててしまう", "不意をつかれて、うろたえるようす"),
    ("yoroyoro",   "よろよろ",   "🚶‍♂️", "repeat", "act_high_novol",
     "重い荷物を持って、足元がふらつく", "足取りが不安定でふらつくようす"),
    ("atafuta",    "あたふた",   "🏃", "repeat_var", "act_high_novol",
     "寝坊して、大あわてで準備する", "大あわてで行動するようす"),

    # --- 動作性が中程度のもの（継続性があるもの） ---
    ("nikoniko",  "にこにこ",   "😊", "repeat", "act_mid",
     "うれしいことがあって、ずっと笑顔でいる", "うれしそうにほほえみ続けるようす"),
    ("gikushaku", "ぎくしゃく", "🤝", "repeat_var", "act_mid",
     "けんかのあとで、会話がうまくかみ合わない", "動きや関係がなめらかでないようす"),
    ("zawazawa",  "ざわざわ",   "🏫", "repeat", "act_mid",
     "授業前の教室が、ざわめいている", "多くの人が小声で話して騒がしいようす"),
    ("kirakira",  "きらきら",   "✨", "repeat", "act_mid",
     "夜空の星が輝いている", "小さく光り輝き続けるようす"),

    # --- 動作性が低いもの（意志性があるもの） ---
    ("gorogoro", "ごろごろ", "🛋️", "repeat", "act_low_vol",
     "休みの日に、家で何もせず過ごす", "何もせず、だらけて過ごすようす"),
    ("nonbiri",  "のんびり", "🍵", "nri", "act_low_vol",
     "温泉で、ゆったりと過ごす", "あくせくせず、ゆったりするようす"),
    ("yukkuri",  "ゆっくり", "🐢", "qri", "act_low_vol",
     "時間をかけて、食事を楽しむ", "急がず、時間をかけるようす"),

    # --- 動作性が低いもの（意志性がないもの） ---
    ("mesomeso", "めそめそ", "😢", "repeat", "act_low_novol",
     "失敗を思い出して、いつまでも泣いている", "弱々しく泣き続けるようす"),
    ("daradara", "だらだら", "📺", "repeat", "act_low_novol",
     "やるべきことをせず、テレビを見続ける", "しまりなく、続けるようす"),
    ("kuyokuyo", "くよくよ", "😔", "repeat", "act_low_novol",
     "済んだことを、いつまでも気にしている", "小さなことを気にし続けるようす"),
    ("odoodo",   "おどおど", "😟", "repeat", "act_low_novol",
     "怒られそうで、びくびくしている", "自信がなく、おびえているようす"),
    ("bonyari",  "ぼんやり", "🌫️", "nri", "act_low_novol",
     "何も考えずに、窓の外を眺めている", "頭や輪郭がはっきりしないようす"),
    ("guttari",  "ぐったり", "🥱", "qri", "act_low_novol",
     "暑さで疲れ切って、力が出ない", "疲れて力が抜けたようす"),
]


# 例文練習用：各語の文脈フレーズ（Step4 の文に {ctx} として挿入。句読点なし）
WORD_CTX = {
    "iraira": "順番を待っていて", "wakuwaku": "旅行のことを考えて", "hirihiri": "日焼けした肌が",
    "zukizuki": "頭が", "betabeta": "手が",
    "bikkuri": "急に呼ばれて", "gakkari": "中止の知らせに", "sukkiri": "悩みが解決して", "hotto": "試験が終わって",
    "iratto": "横入りされて", "mukatto": "失礼なことを言われて", "zukitto": "ひざが",
    "kuratto": "立ちくらみで", "furatto": "疲れて", "chikutto": "注射のとき", "katto": "ばかにされて",
    "burabura": "公園を", "urouro": "駅の周りを", "urochoro": "町を",
    "orooro": "トラブルが起きて", "kyorokyoro": "初めての駅で", "magomago": "改札の前で",
    "sowasowa": "発表が近づいて", "dogimagi": "急に話しかけられて", "yoroyoro": "重い荷物で", "atafuta": "寝坊して",
    "nikoniko": "彼女が", "gikushaku": "二人の関係が", "zawazawa": "教室が", "kirakira": "夜空の星が",
    "gorogoro": "ソファで", "nonbiri": "温泉で", "yukkuri": "休日に",
    "mesomeso": "失敗を思い出して", "daradara": "宿題をせずに", "kuyokuyo": "済んだことを",
    "odoodo": "怒られそうで", "bonyari": "窓の外を見ながら", "guttari": "暑さで",
}


# =====================================================================
#  6. 例文の練習（Step4）
# =====================================================================
PRACTICE = {
    "emo_cont": [
        {"frame": "{ctx}、だんだん{word}[ ？ ]。",
         "explain": "＋継続性・動作性（中）なので、状態の出現を表す「してくる（してきた）」が自然です。「した」は一瞬で完了する形、「するところだ」は意志的な動作の直前を表す形で、合いません。",
         "options": [("してきた", "状態が現れて続く", 1),
                     ("した", "一瞬で完了", 0),
                     ("するところだ", "これから行う直前（意志的）", 0)]},
        {"frame": "{ctx}、急に{word}[ ？ ]。",
         "explain": "＋継続性・動作性（中）なので、開始を表す「しはじめる（しはじめた）」が使えます。「するところだ」は＋意志性・高動作性が、「したところだ」は変化結果の継続性が必要です。",
         "options": [("しはじめた", "状態の開始", 1),
                     ("するところだ", "これから行う直前（要意志性）", 0),
                     ("したところだ", "変化の完了直後", 0)]},
    ],
    "emo_result": [
        {"frame": "さっき{word}して、いまも{word}[ ？ ]。",
         "explain": "＋変化結果の継続性なので、変化の結果の最中を表す「しているところだ」が自然です。「しつづけている」は具体的な動きの継続、「しはじめた」は開始で、結びつきません。",
         "options": [("しているところだ", "変化の結果が残っている最中", 1),
                     ("しつづけている", "動作が継続している", 0),
                     ("しはじめた", "開始", 0)]},
        {"frame": "{ctx}、たった今{word}[ ？ ]。",
         "explain": "＋変化結果の継続性・動作性（中）なので、完了直後を表す「したところだ」が使えます。「してきた」「しつづけた」は＋継続性が必要で、変化結果型とは結びつきません。",
         "options": [("したところだ", "変化の完了直後", 1),
                     ("してきた", "状態の出現", 0),
                     ("しつづけた", "動作の継続", 0)]},
    ],
    "emo_moment": [
        {"frame": "{ctx}、一瞬{word}[ ？ ]。",
         "explain": "ー継続性（一瞬で成立）なので「してしまった（した）」が自然です。「している」（状態の継続）や「しつづけた」は使えません。",
         "options": [("としてしまった", "瞬間の完了", 1),
                     ("としている", "状態の継続", 0),
                     ("としつづけた", "継続", 0)]},
        {"frame": "{ctx}、{word}[ ？ ]が、すぐにおさまった。",
         "explain": "ー継続性のオノマトペと結びつくのは「してしまう」だけです。「しはじめる」「しつづける」は＋継続性が必要です。",
         "options": [("としてしまった", "瞬間の完了", 1),
                     ("としはじめた", "開始", 0),
                     ("としつづけた", "継続", 0)]},
    ],
    "act_high_vol": [
        {"frame": "これから、{ctx}{word}[ ？ ]。",
         "explain": "動作性（高）・＋意志性なので、これから行う直前を表す「するところだ」が使えます。「してきた」は状態の出現（感情・感覚向け）、「したところだ」は変化結果の継続性が必要です。",
         "options": [("するところだ", "これから行う直前（意志的）", 1),
                     ("してきた", "状態の出現", 0),
                     ("したところだ", "変化の完了直後", 0)]},
        {"frame": "ちょうど今、{ctx}{word}[ ？ ]。",
         "explain": "＋継続性・動作性（高）なので、動作の最中を表す「しているところだ」が使えます。「したところだ」は変化結果の継続性が必要、「してくる」はこのカテゴリーとは結びつきません。",
         "options": [("しているところだ", "動作の最中", 1),
                     ("したところだ", "変化の完了直後", 0),
                     ("してきた", "状態の出現", 0)]},
    ],
    "act_high_novol": [
        {"frame": "{ctx}、{word}[ ？ ]。",
         "explain": "＋継続性・動作性（高）なので開始の「しはじめた」が自然です。意志性が関わらないため、「するところだ」（＋意志性が必要）は使えません。",
         "options": [("しはじめた", "動作の開始", 1),
                     ("するところだ", "これから行う直前（要意志性）", 0),
                     ("したところだ", "変化の完了直後", 0)]},
        {"frame": "急に、{word}[ ？ ]。",
         "explain": "＋継続性・動作性（高）なので、突発的な開始を表す「しだす（しだした）」が使えます。「しようとする」「するところだ」は＋意志性が必要です。",
         "options": [("しだした", "突発的な開始", 1),
                     ("しようとした", "意志的な動作の直前", 0),
                     ("するところだった", "これから行う直前（要意志性）", 0)]},
    ],
    "act_mid": [
        {"frame": "{ctx}、だんだん{word}[ ？ ]。",
         "explain": "＋継続性・動作性（中）なので、状態の出現を表す「してきた」が自然です。「しようとした」は＋意志性が必要、「したところだ」は変化結果の継続性が必要です。",
         "options": [("してきた", "状態の出現", 1),
                     ("しようとした", "意志的な動作の直前", 0),
                     ("したところだ", "変化の完了直後", 0)]},
        {"frame": "{ctx}、{word}[ ？ ]。",
         "explain": "＋継続性・動作性（中）なので、開始を表す「しはじめた」が使えます。「しようとした」は＋意志性が、「したところだった」は変化結果の継続性が必要です。",
         "options": [("しはじめた", "状態・動作の開始", 1),
                     ("しようとした", "意志的な動作の直前", 0),
                     ("したところだった", "変化の完了直後", 0)]},
    ],
    "act_low_vol": [
        {"frame": "今、家で{word}[ ？ ]。",
         "explain": "動作性（低）なので「しているところだ」「してしまう」だけが結びつきます。「するところだ」は動作性（高）が、「しだした」は動作性（中・高）が必要です。",
         "options": [("しているところだ", "その状態の最中", 1),
                     ("するところだ", "これから行う直前（要高動作性）", 0),
                     ("しだした", "突発的な開始（要中・高動作性）", 0)]},
        {"frame": "連休は、結局ずっと家で{word}[ ？ ]。",
         "explain": "±継続性・動作性（低〜高）と結びつく「してしまう（してしまった）」が使えます。「しだした」は動作性（中・高）、「するところだった」は動作性（高）が必要です。",
         "options": [("してしまった", "そのまま過ごしてしまった", 1),
                     ("しだした", "突発的な開始（要中・高動作性）", 0),
                     ("するところだった", "これから行う直前（要高動作性）", 0)]},
    ],
    "act_low_novol": [
        {"frame": "彼は今、{word}[ ？ ]。",
         "explain": "動作性（低）・ー意志性なので「しているところだ」が自然です。「しようとした」は＋意志性が、「しだした」は動作性（中・高）が必要です。",
         "options": [("しているところだ", "その状態の最中", 1),
                     ("しようとした", "意志的な動作の直前", 0),
                     ("しだした", "突発的な開始（要中・高動作性）", 0)]},
        {"frame": "気がつくと、また{word}[ ？ ]。",
         "explain": "±継続性・動作性（低〜高）と結びつく「してしまう（してしまっていた）」が使えます。「しだしていた」は動作性（中・高）、「しようとしていた」は＋意志性が必要です。",
         "options": [("してしまっていた", "気づかないうちにその状態になっていた", 1),
                     ("しだしていた", "突発的な開始（要中・高動作性）", 0),
                     ("しようとしていた", "意志的な動作の直前", 0)]},
    ],
}


# =====================================================================
#  DB 構築
# =====================================================================
def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.executescript("""
    CREATE TABLE knowledge (
        section TEXT NOT NULL,
        ord     INTEGER NOT NULL,
        label   TEXT NOT NULL,
        body    TEXT NOT NULL,
        fig     TEXT
    );
    CREATE TABLE phon_forms (
        key     TEXT PRIMARY KEY,
        ord     INTEGER NOT NULL,
        label   TEXT NOT NULL,
        term    TEXT NOT NULL,
        example TEXT NOT NULL,
        hint    TEXT NOT NULL
    );
    CREATE TABLE categories (
        id           TEXT PRIMARY KEY,
        ord          INTEGER NOT NULL,
        name         TEXT NOT NULL,
        kind         TEXT NOT NULL,          -- 感情・感覚 / 動作
        continuity   TEXT NOT NULL,          -- ＋ / 変化結果の＋ / ー
        action       TEXT NOT NULL,          -- 高 / 中 / 低
        volition     TEXT NOT NULL,          -- ＋ / ー / 関与しない
        profile_text TEXT NOT NULL,
        expr_explain TEXT NOT NULL
    );
    CREATE TABLE expressions (
        key       TEXT PRIMARY KEY,
        ord       INTEGER NOT NULL,
        label     TEXT NOT NULL,
        cond_text TEXT NOT NULL
    );
    CREATE TABLE category_expression (
        category_id    TEXT NOT NULL REFERENCES categories(id),
        expression_key TEXT NOT NULL REFERENCES expressions(key),
        PRIMARY KEY (category_id, expression_key)
    );
    CREATE TABLE words (
        id          TEXT PRIMARY KEY,
        word        TEXT NOT NULL,
        emoji       TEXT NOT NULL,
        phon        TEXT NOT NULL REFERENCES phon_forms(key),
        category_id TEXT NOT NULL REFERENCES categories(id),
        scene       TEXT NOT NULL,
        meaning     TEXT NOT NULL,
        ctx         TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE practice (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id TEXT NOT NULL REFERENCES categories(id),
        ord         INTEGER NOT NULL,
        frame       TEXT NOT NULL,
        explain     TEXT NOT NULL
    );
    CREATE TABLE practice_options (
        practice_id INTEGER NOT NULL REFERENCES practice(id),
        ord         INTEGER NOT NULL,
        label       TEXT NOT NULL,
        meaning     TEXT NOT NULL,
        correct     INTEGER NOT NULL
    );
    """)

    cur.executemany("INSERT INTO knowledge VALUES (?,?,?,?,?)", KNOWLEDGE)
    cur.executemany("INSERT INTO phon_forms VALUES (?,?,?,?,?,?)", PHON_FORMS)
    cur.executemany("INSERT INTO categories VALUES (?,?,?,?,?,?,?,?,?)", CATEGORIES)
    cur.executemany("INSERT INTO expressions VALUES (?,?,?,?)", EXPRESSIONS)
    for cat_id, keys in CATEGORY_EXPRESSIONS.items():
        cur.executemany("INSERT INTO category_expression VALUES (?,?)",
                        [(cat_id, k) for k in keys])
    cur.executemany("INSERT INTO words VALUES (?,?,?,?,?,?,?,?)",
                    [w + (WORD_CTX.get(w[0], ""),) for w in WORDS])
    for cat_id, questions in PRACTICE.items():
        for q_ord, q in enumerate(questions):
            cur.execute("INSERT INTO practice (category_id, ord, frame, explain) VALUES (?,?,?,?)",
                        (cat_id, q_ord, q["frame"], q["explain"]))
            pid = cur.lastrowid
            cur.executemany("INSERT INTO practice_options VALUES (?,?,?,?,?)",
                            [(pid, i, label, meaning, correct)
                             for i, (label, meaning, correct) in enumerate(q["options"])])

    con.commit()
    con.close()
    print(f"OK: {DB_PATH} を作成しました（単語 {len(WORDS)} 語 / カテゴリー {len(CATEGORIES)}）")


if __name__ == "__main__":
    main()
