# init_db.py
# 「学習支援データ.docx」＋研究資料の整理データを SQLite データベースに投入するスクリプト
# 実行方法: python init_db.py  →  onomatopoeia.db が生成される
#
# 2026-09 改修：
#   ・表現形式の「前接条件」を素性の集合として構造化（req_cont / req_act / req_vol）
#   ・カテゴリー／音韻形態に「なぜその素性になるのか」の根拠文を追加
#   ・Step4 の例文を語ごとの自然文に置き換え（誤答は実行時に自動生成）
#   ・構造化条件から計算した○×が、研究資料由来の正解表と一致することを検証
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "onomatopoeia.db")


# =====================================================================
#  1. 知識データ（学習提示用）
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
    ("volition", 3, "意志性（関与しない）",
     "状況に反応して起こる動きで、意志で始めるとも言えないもの（おろおろ・あたふた など）。", None),

    ("rule", 1, "継続性と動作性の関係",
     "継続性が低いほど、動作性が高くなる。（一瞬の変化＝動作性「高」／続く状態＝動作性「中」）", None),

    # --- 音韻形態と素性の関係 ---
    ("phon_feature", 1, "2モーラ反復形（ABAB）→ ＋継続性",
     "くり返しのリズムが「続くこと」を写し取る → ＋継続性。継続性はこの形から安定して予測できます。一方、動作性は語の意味しだいで高（きょろきょろ）にも中（いらいら）にも低（ごろごろ）にもなります。", None),
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

    # --- 接続表現そのものの学び方（項目3） ---
    ("expr_note", 1, "「前接条件」は覚えるものではなく、意味から出てくる",
     "各形式の条件は、その形式が表す時間的な局面（直前・開始・継続・完了・完遂）から自然に決まります。たとえば「開始」を表す形式は、開始したあとに続くものでなければ使えません（＝＋継続性が必要）。", None),
    ("expr_note", 2, "同じ局面でも条件が違うことがある",
     "「しはじめる」と「しだす」はどちらも開始ですが、「しだす」は〈思いがけず急に始まる〉意味なので、自分の意志で始める動き（＋意志性）とは結びつきません。局面だけでなく、その形式が加える意味に注目しましょう。", None),
    ("expr_note", 3, "条件が「不問」の形式もある",
     "「してしまう」は完遂・不本意の意味を添えるだけなので、素性を問わずどのオノマトペにも付きます。ー継続性の語（いらっ・ずきっ など）と結びつくのは、事実上この形だけです。", None),
]


# =====================================================================
#  2. 音韻形態（田守・スコウラップ 1999 より作成）
#     pred_cont / pred_act：この形から予測される素性（例外検出に使う）
# =====================================================================
PHON_FORMS = [
    # (key, ord, label, term, example, hint, pred_cont, pred_act, pred_note)
    ("repeat",     1, "2モーラ反復形（ABAB）",       "CVCV-CVCV",
     "いらいら・わくわく・きらきら・ごろごろ", "継続する状態・動作を表しやすい",
     "＋", "",
     "くり返しのリズムが「続くこと」を写すので、継続性は安定して＋です。ただし動作性はこの形からは決まりません（きょろきょろ＝高／いらいら＝中／ごろごろ＝低）。動作性は語の意味から判断しましょう。"),
    ("repeat_var", 2, "2モーラ反復形の変種",          "ABCD型の反復",
     "うろちょろ・あたふた・どぎまぎ・ぎくしゃく", "不規則な反復で、乱れた動きを表しやすい",
     "＋", "高",
     "不規則なくり返しが「乱れた・落ち着かない動き」を写すため、動作性が高くなりやすいです。"),
    ("qri",        3, "「っ＋り」型",                "CVQCVri形",
     "びっくり・がっかり・ぐったり・ゆっくり", "変化結果や低動作の状態を表しやすい",
     "変化結果の＋", "中",
     "促音の区切れ＋「り」の余韻が「変化とその結果」を写します。ただし、ぐったり・ゆっくりのように低動作の状態を表す例外があります。"),
    ("nri",        4, "「ん＋り」型",                "CVNCVri形",
     "ぼんやり・のんびり", "ゆるやかで低動作の状態を表しやすい",
     "＋", "低",
     "撥音「ん」のゆるみが「ゆったりした状態」を写すため、動作性は低くなります。"),
    ("q",          5, "「っ」で終わる型",             "CVQ・CVCVQ形",
     "ほっ・いらっ・ずきっ・ちくっ", "瞬間的な変化を表しやすい（一部は変化結果型）",
     "ー", "高",
     "促音の切れが「一瞬の変化」を写します。ただし「ほっ」のように、変化の結果が残る型になる例外があります。"),
]


# =====================================================================
#  3. 8つのカテゴリー（why_* ＝ その素性値になる理由）
# =====================================================================
CATEGORIES = [
    # (id, ord, name, kind, continuity, action, volition, profile_text, expr_explain,
    #  why_cont, why_act, why_vol)
    ("emo_cont", 1, "感情・感覚表現（継続性があるもの）", "感情・感覚",
     "＋", "中", "ー",
     "{＋直接感覚、＋継続性、動作性（中）、ー意志性}",
     "＋継続性・動作性（中）を持つため、開始を表す「しはじめる・しだす」、状態の出現を表す「してくる」、最中を表す「しているところだ」、そして「してしまう」と結びつきます。",
     "感情・感覚が時間幅をもって続くタイプです。一瞬で成立して消えるならー継続性、変化が起きてその結果が残るなら〈変化結果の＋〉になります。",
     "感情・感覚を表しますが時間の継続があるため動作性は（中）です。継続性が低いほど動作性は高くなり、一瞬の変化なら（高）になります。",
     "自分の意志で起こしたりやめたりできない感情・感覚なので、意志性はーです。"),

    ("emo_result", 2, "感情・感覚表現（変化結果の継続性があるもの）", "感情・感覚",
     "変化結果の＋", "中", "ー",
     "{＋直接感覚、＋変化結果の継続性、動作性（中）、ー意志性}",
     "＋変化結果の継続性を持つため、結果の最中を表す「しているところだ」、完了直後を表す「したところだ」、「してしまう」と結びつきます。",
     "驚く・落ち込むといった変化が一度起こり、そのあと結果の状態が残ります。続くのは「変化そのもの」ではなく「変化の結果」なので〈変化結果の＋〉です。",
     "感情・感覚の変化を表し、時間の幅をもつため動作性は（中）です。",
     "意志で起こせない感情・感覚の変化なので、意志性はーです。"),

    ("emo_moment", 3, "感情・感覚表現（継続性がないもの）", "感情・感覚",
     "ー", "高", "ー",
     "{ー直接感覚、ー継続性、動作性（高）、ー意志性}",
     "ー継続性（一瞬で成立）のため、開始・継続を表す形式とは結びつかず、「してしまう」のみと結びつきます。",
     "一瞬で成立し、あとに状態が残りません。だから継続性はーです。",
     "継続性が低いほど動作性は高くなります。一瞬の変化・刺激なので動作性は（高）です。",
     "意志で起こせない瞬間的な感情・感覚なので、意志性はーです。"),

    ("act_high_vol", 4, "動作性が高いもの（意志性があるもの）", "動作",
     "＋", "高", "＋",
     "{ー直接感覚、＋継続性、動作性（高）、＋意志性}",
     "動作性（高）・＋意志性を持つため、「するところだ」「しようとする」など意志的な動作の形式に加え、「しはじめる」「しつづける」「しているところだ」「してしまう」と結びつきます。",
     "動き自体が時間幅をもって続くので＋継続性です。",
     "目に見える具体的な動きなので動作性は（高）です。",
     "自分の意志で始めたりやめたりできる行為なので＋意志性です。"),

    ("act_high_novol", 5, "動作性が高いもの（意志性が関わらないもの）", "動作",
     "＋", "高", "関与しない",
     "{ー直接感覚、＋継続性、動作性（高）}",
     "＋継続性・動作性（高）を持つため「しはじめる」「しだす」「しつづける」「しているところだ」「してしまう」と結びつきますが、意志性が関わらないため「するところだ」「しようとする」は使えません。",
     "あわてる・見回すといった動きが続くので＋継続性です。",
     "具体的で激しい動きを表すため動作性は（高）です。",
     "状況に反応して起こる動きで、自分の意志で始めるとは言えないため、意志性は「関与しない」と扱います。"),

    ("act_mid", 6, "動作性が中程度のもの（継続性があるもの）", "動作",
     "＋", "中", "ー",
     "{ー直接感覚、＋継続性、動作性（中）、ー意志性}",
     "＋継続性・動作性（中）を持つため、「しはじめる」「しだす」「してくる」「しているところだ」「してしまう」と結びつきます。",
     "動きやようすが続くので＋継続性です。",
     "動きはありますが激しくなく、状態に近いため動作性は（中）です。",
     "意志的に始める行為とは言いにくいので意志性はーです。"),

    ("act_low_vol", 7, "動作性が低いもの（意志性があるもの）", "動作",
     "＋", "低", "＋",
     "{ー直接感覚、＋継続性、動作性（低）、＋意志性}",
     "動作性（低）のため開始・継続を表す形式とは結びつきにくく、「しているところだ」「してしまう」と結びつきます。",
     "その状態が続くので＋継続性です。",
     "積極的な動きがなく、ゆるやかな過ごし方なので動作性は（低）です。",
     "自分でそう過ごすことを選べるので＋意志性です。"),

    ("act_low_novol", 8, "動作性が低いもの（意志性がないもの）", "動作",
     "＋", "低", "ー",
     "{ー直接感覚、＋継続性、動作性（低）、ー意志性}",
     "動作性（低）・ー意志性のため、「していく」「しているところだ」「してしまう」と結びつきます。",
     "力の抜けた状態・気持ちが続くので＋継続性です。",
     "積極的な動きがなく、状態に近いため動作性は（低）です。",
     "自分の意志でそうするものではないので意志性はーです。"),
]


# =====================================================================
#  4. アスペクチュアリティーの表現形式
#     req_* ＝ 前接条件（許容する素性値。"" は不問）
#     why_* ＝ その条件が必要な理由（誤答フィードバックに使う）
# =====================================================================
EXPRESSIONS = [
    # (key, ord, label, phase, group, cond_text, example,
    #  req_cont, req_act, req_vol, why_cont, why_act, why_vol,
    #  ok_example, ng_example, form_base, form_past)
    ("surutokoroda", 1, "するところだ", "直前", "直前",
     "動作性（高）・＋意志性", "今から出かけるところだ",
     "", "高", "＋",
     "",
     "これから始める具体的な動きを指し示す形なので、動きとしての強さ（動作性 高）が必要です。",
     "自分の意志でこれから行う場面を表すので、意志的に起こせる動きでなければ使えません。",
     "○今から商店街をぶらぶらするところだ", "×いらいらするところだ",
     "するところだ", "するところだった"),

    ("shiyoutosuru", 2, "しようとする", "直前（意志）", "直前",
     "動作性（高）・＋意志性", "席を立とうとする",
     "", "高", "＋",
     "",
     "動作に取りかかろうとする場面を表すので、具体的な動き（動作性 高）が必要です。",
     "「しよう」という意図を含む形なので、意志で起こせない感情・感覚には使えません。",
     "○うろうろしようとする", "×どぎまぎしようとする",
     "しようとする", "しようとした"),

    ("shihajimeru", 3, "しはじめる", "開始", "開始",
     "＋継続性・動作性（中・高）", "雨が降りはじめる",
     "＋", "中|高", "",
     "開始したあとに状態や動きが続いていくことが前提なので、＋継続性が必要です。一瞬で終わるもの、変化の結果だけが残るものには使えません。",
     "動きや状態が立ち上がることを表すので、動作性が低い（だらけた・ゆるやかな）ものには使いにくいです。",
     "",
     "○いらいらしはじめる", "×ぐったりしはじめる",
     "しはじめる", "しはじめた"),

    ("shidasu", 4, "しだす", "突発的開始", "開始",
     "＋継続性・動作性（中・高）・意志的でないこと", "急に泣きだす",
     "＋", "中|高", "ー|関与しない",
     "始まったあとに続くことが前提なので、＋継続性が必要です。",
     "動きや状態が急に立ち上がることを表すので、動作性が低いものには使いにくいです。",
     "「しだす」は〈思いがけず急に始まる〉意味なので、自分の意志で始める動き（＋意志性）とは結びつきません。",
     "○急にそわそわしだす", "×ぶらぶらしだす",
     "しだす", "しだした"),

    ("shitekuru", 5, "してくる", "出現・持続", "出現・変化",
     "＋継続性・動作性（中）", "だんだん眠くなってくる",
     "＋", "中", "",
     "出現した状態がそのまま続くことを表すので、＋継続性が必要です。",
     "だんだん現れてくる〈状態〉を表す形なので、動作性（中）の感情・感覚・ようすに限られます。強い動き（高）やだらけた状態（低）では使えません。",
     "",
     "○だんだんいらいらしてくる", "×うろうろしてくる",
     "してくる", "してきた"),

    ("shiteiku", 6, "していく", "変化の進行", "出現・変化",
     "＋継続性・動作性（低）・ー意志性", "これから寒くなっていく",
     "＋", "低", "ー",
     "変化が長い時間をかけて進んでいくことを表すので、＋継続性が必要です。",
     "長期的でゆるやかな変化を表すので、瞬間的・具体的な動き（動作性 中・高）とは結びつきません。",
     "自然にそうなっていく変化を表すので、意志的な行為（＋意志性）とは結びつきません。",
     "○記憶がだんだんぼんやりしていく", "×きょろきょろしていく",
     "していく", "していった"),

    ("shitsuzukeru", 7, "しつづける", "継続", "継続・最中",
     "＋継続性・動作性（高）", "走りつづける",
     "＋", "高", "",
     "動きが続くことを表すので、＋継続性が必要です。",
     "具体的で目に見える動きの継続を表すので、動作性（高）が必要です。感情・感覚（中）やだらけた状態（低）では使えません。",
     "",
     "○きょろきょろしつづける", "×いらいらしつづける",
     "しつづける", "しつづけた"),

    ("shiteirutokoroda", 8, "しているところだ", "最中", "継続・最中",
     "＋継続性 または ＋変化結果の継続性", "いまご飯を食べているところだ",
     "＋|変化結果の＋", "", "",
     "続いている状態・動き、または変化の結果が残っている「最中」を指すので、一瞬で終わる（ー継続性）ものには使えません。",
     "",
     "",
     "○ごろごろしているところだ", "×いらっとしているところだ",
     "しているところだ", "しているところだった"),

    ("shitatokoroda", 9, "したところだ", "完了直後", "完了",
     "＋変化結果の継続性・動作性（中）", "たった今駅に着いたところだ",
     "変化結果の＋", "中", "",
     "変化が終わってその結果が残っている状態を指すので、＋変化結果の継続性が必要です。ただ続くだけの状態（＋継続性）や、結果が残らないもの（ー継続性）では使えません。",
     "変化として捉えられる感情・感覚の動き（動作性 中）に限られます。",
     "",
     "○たった今びっくりしたところだ", "×いらいらしたところだ",
     "したところだ", "したところだった"),

    ("shiteshimau", 10, "してしまう", "完遂", "完遂",
     "素性を問わない（どのオノマトペにも付く）", "全部食べてしまう",
     "", "", "",
     "", "", "",
     "○すっかりぐったりしてしまった", "（結びつかない語はありません）",
     "してしまう", "してしまった"),
]

# 局面グループの表示順（Step3 のグループ表示に使う）
EXPR_GROUPS = ["直前", "開始", "出現・変化", "継続・最中", "完了", "完遂"]


# カテゴリー × 結びつく表現（研究資料の「表現形式」欄より）＝ 正解表
# ※ 構造化条件（req_*）から計算した結果がこの表と一致することを下で検証する
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
#  5. オノマトペ本体（感情・感覚16語 + 動作23語）
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


# =====================================================================
#  6. Step4：語ごとの例文（2問ずつ）
#     frame … オノマトペ（必要なら接続の「と」も）まで書き込んだ完成文。空所は [ ？ ]
#     correct_key … 正解の表現形式キー（そのカテゴリーと結びつく形式でなければエラー）
#     form … 使う活用形（base / past）
#     誤答選択肢はDBに持たない。実行時に「結びつかない形式」から自動生成する。
# =====================================================================
STAGE_GUIDES = [
    # (stage, ord, question, detail)  … 段階ごとの「判断手順チェックリスト」
    ("continuity", 1, "① 場面を思い浮かべる",
     "その気持ち・状態・動きが「いつ起こって、いつ終わるのか」を場面の中で確かめます。語だけを見ても決まりません。"),
    ("continuity", 2, "② 「今もまだ続いているか？」と聞く",
     "続いているなら ＋継続性。「いらいらしている」「ずきずきしている」と言えるかが目安です。"),
    ("continuity", 3, "③ 続いていないなら「変化の結果は残っているか？」と聞く",
     "変化そのものは一度きりでも、そのあとの状態が残っているなら 変化結果の＋。何も残らず一瞬で終わるなら ー継続性です。"),

    ("action", 1, "① まず継続性を見る",
     "ー継続性（一瞬で終わる）なら、その時点で動作性は（高）です。一瞬に強い変化・刺激が集中するからです。"),
    ("action", 2, "② 「外から見える具体的な動きがあるか？」と聞く",
     "体が実際に動いている（歩き回る・見回す・あわてる）なら 動作性（高）。"),
    ("action", 3, "③ 動きより気持ち・感覚が中心か？",
     "心の中の変化や体の感覚が中心で、時間の幅をもつなら 動作性（中）。"),
    ("action", 4, "④ 動きがなく、だらけた・ゆるやかな状態か？",
     "積極的な動きがなく、力が抜けている／ゆったりしているなら 動作性（低）。"),

    ("volition", 1, "① 「今から〜しよう」と言えるか？",
     "○「今から公園をぶらぶらしよう」と言えるなら ＋意志性。これが一番はっきりした見分け方です。"),
    ("volition", 2, "② 言えないなら「感情・感覚か？」と聞く",
     "×「今からいらいらしよう」。心の中の気持ちや体の感覚は意志で起こせないので ー意志性。"),
    ("volition", 3, "③ 感情ではなく動きなのに、意志で始められないか？",
     "×「今からおろおろしよう」。動き自体はあるが状況に反応して起こるものは 意志性は関与しない として扱います。"),

    ("phon", 1, "① 語の形を見分ける",
     "反復か／「っ＋り」か／「ん＋り」か／「っ」で終わるか。まず形だけを見ます。"),
    ("phon", 2, "② その形から予測できる素性を確認する",
     "形によっては予測できない素性もあります（反復形の動作性など）。予測できるものだけを手がかりにします。"),
    ("phon", 3, "③ 語の意味で確かめ、食い違ったら意味を優先する",
     "予測はあくまで出発点です。ゆっくり・ぐったり・ほっ のように、形からの予測が外れる語があります。"),

    ("category", 1, "① 種類を決める（感情・感覚／動作）",
     "心の中の気持ち・体の感覚なら「感情・感覚」、外から見えるふるまい・ようすなら「動作」。"),
    ("category", 2, "② 3つの素性を順に出す",
     "継続性 → 動作性 → 意志性 の順に、段階1〜3の手順で決めていきます。"),
    ("category", 3, "③ 種類＋3素性の組み合わせでカテゴリーが1つに決まる",
     "素性が同じでも種類が違えば別のカテゴリーです（いらいら と にこにこ）。逆に、種類も素性もほぼ同じで、意志性だけで分かれる組もあります。"),
    ("category", 4, "④ そのカテゴリーが、結びつく文法形式を決める",
     "ここで出したカテゴリーが、フェーズ2で「どの表現形式と結びつくか」を決めます。素性を出すことがゴールではなく、出発点です。"),
]


CONTRAST_PAIRS = [
    # (stage, ord, word_a, word_b, feature, point)
    #   feature が "" のときは3素性すべてを並べて表示する
    ("continuity", 1, "iraira", "iratto", "continuity",
     "同じ「不快な気持ち」でも、続くか一瞬かが違います。「いらいらしている」とは言えますが「×いらっとしている」とは言えません。"),
    ("continuity", 2, "wakuwaku", "bikkuri", "continuity",
     "どちらも続いているように見えますが、「わくわく」は気持ちそのものが続き、「びっくり」は驚く変化が一度起きてその結果が残っているだけです。"),
    ("continuity", 3, "iratto", "hotto", "continuity",
     "どちらも「っ」で終わる同じ音の形。それでも「ほっ」は安心した状態が残るので変化結果型になります。形だけでは決まりません。"),

    ("action", 1, "kyorokyoro", "iraira", "action",
     "どちらも＋継続性ですが、「きょろきょろ」は外から見える体の動きがあり、「いらいら」は気持ちだけです。"),
    ("action", 2, "urouro", "gorogoro", "action",
     "どちらも動作のオノマトペ。動き回るか、動かないかで分かれます。"),
    ("action", 3, "zukitto", "zukizuki", "action",
     "同じ痛みでも、一瞬で終わる（＝継続性がないので動作性は高）か、続く感覚（＝動作性は中）かが違います。"),

    ("volition", 1, "burabura", "orooro", "volition",
     "どちらも歩き回る動きですが、「ぶらぶらしよう」とは言えても「×おろおろしよう」とは言えません。状況に反応して起こる動きです。"),
    ("volition", 2, "gorogoro", "daradara", "volition",
     "どちらも動作性（低）。休みの日に自分で選んで「ごろごろしよう」とは言えますが、「×だらだらしよう」は不自然です。"),
    ("volition", 3, "urochoro", "wakuwaku", "volition",
     "動き（意志で始められる）と、感情（意志では起こせない）の対比です。"),

    ("phon", 1, "bikkuri", "yukkuri", "",
     "同じ「っ＋り」型。「びっくり」は予測どおり（変化結果の＋・動作性 中）ですが、「ゆっくり」は＋継続性・動作性（低）で予測が外れます。"),
    ("phon", 2, "iratto", "hotto", "continuity",
     "同じ「っ」で終わる型。予測は ー継続性ですが、「ほっ」は結果が残るので変化結果型です。"),
    ("phon", 3, "kyorokyoro", "gorogoro", "action",
     "同じ2モーラ反復形。動作性は高にも低にもなります。だからこの形からは動作性を予測できません。"),

    ("category", 1, "iraira", "nikoniko", "",
     "3つの素性はまったく同じ〈＋継続性・動作性（中）・ー意志性〉。それでも種類（感情・感覚／動作）が違うので、別のカテゴリーになります。"),
    ("category", 2, "gorogoro", "daradara", "",
     "種類も継続性も動作性も同じ。意志性だけで2つのカテゴリーに分かれます。"),
    ("category", 3, "burabura", "orooro", "",
     "こちらも継続性・動作性まで同じで、意志性（＋／関与しない）だけが違います。この違いが「するところだ」が使えるかどうかを決めます。"),
]


WORKED_EXAMPLES = [
    # (stage, word_id, conclusion, note)
    ("continuity", "gakkari", "変化結果の＋（変化結果の継続性）",
     "「一度きりの変化」と「そのあと残る状態」を分けて考えるのがコツです。落ち込んだ気分が続いていても、＋継続性ではありません。"),
    ("action", "guttari", "動作性（低）",
     "音の形（「っ＋り」型）からは動作性（中）と予測されますが、この語は例外です。最後は意味で決めます。"),
    ("volition", "sowasowa", "意志性は関与しない",
     "「ー」ではなく「関与しない」です。感情ではなく動き・ようすがあるのに、意志で始められないタイプです。"),
    ("phon", "yukkuri", "＋継続性・動作性（低）＝予測の例外",
     "「っ＋り」型でも、変化ではなく「急がない過ごし方」を表す語があります。形は手がかり、意味が決定です。"),
    ("category", "kyorokyoro", "動作性が高いもの（意志性が関わらないもの）",
     "このカテゴリーだから「しはじめる」「しつづける」とは結びつき、「するところだ」とは結びつきません。"),
]


WORKED_STEPS = [
    # (stage, ord, question, answer)
    ("continuity", 1, "① 場面を思い浮かべる：どんなときに「がっかり」する？",
     "楽しみにしていた試合が中止だと聞いた、その瞬間に起こります。"),
    ("continuity", 2, "② 今もまだ「がっかりする」という変化が続いている？",
     "いいえ。落ち込むという変化そのものは、知らせを聞いた一度きりです。"),
    ("continuity", 3, "③ では、変化の結果は残っている？",
     "残っています。落ち込んだ気分はそのあとも続きます。だから〈変化結果の＋〉です。"),

    ("action", 1, "① まず継続性は？",
     "＋継続性です。疲れて力が抜けた状態が続いています（一瞬ではありません）。"),
    ("action", 2, "② 外から見える具体的な動きはある？",
     "ありません。むしろ「動かない」ことを表しています。"),
    ("action", 3, "③ だらけた・力の抜けた状態か？",
     "そうです。積極的な動きがないので〈動作性（低）〉になります。"),

    ("volition", 1, "①「今からそわそわしよう」と言える？",
     "言えません。だから ＋意志性ではありません。"),
    ("volition", 2, "② 感情・感覚か、それとも動き・ようすか？",
     "落ち着かず体が動いてしまう「ようす」です。心の中だけの話ではありません。"),
    ("volition", 3, "③ なぜ起こっている？",
     "発表の順番が近づいたという状況に反応して起こっています。意志が関与しないタイプです。"),

    ("phon", 1, "① 語の形は？",
     "「ゆっくり」は「っ＋り」型（CVQCVri形）です。"),
    ("phon", 2, "② この形からの予測は？",
     "変化結果の＋・動作性（中）。びっくり・がっかり と同じ形です。"),
    ("phon", 3, "③ 意味で確かめると？",
     "「ゆっくり」は変化ではなく「急がない過ごし方」が続くことを表します。予測と食い違うので、意味を優先します。"),

    ("category", 1, "① 種類は？",
     "外から見えるふるまいなので「動作」のオノマトペです。"),
    ("category", 2, "② 継続性は？",
     "あたりを見回す動きが続くので ＋継続性。"),
    ("category", 3, "③ 動作性は？",
     "首や目が実際に動いています。外から見える具体的な動きなので 動作性（高）。"),
    ("category", 4, "④ 意志性は？",
     "×「今からきょろきょろしよう」。初めての場所という状況に反応して起こるので、意志性は関与しない。"),
]


PRACTICE = [
    # (word_id, frame, correct_key, form)
    # --- emo_cont：しはじめる／しだす／してくる／しているところだ／してしまう ---
    ("iraira",   "電車がなかなか来なくて、だんだんいらいら[ ？ ]。", "shitekuru", "past"),
    ("iraira",   "まだ順番が来なくて、今いらいら[ ？ ]。", "shiteirutokoroda", "base"),
    ("wakuwaku", "明日の旅行を思うと、急にわくわく[ ？ ]。", "shidasu", "past"),
    ("wakuwaku", "準備をしているうちに、だんだんわくわく[ ？ ]。", "shitekuru", "past"),
    ("hirihiri", "日焼けした肌が、夜になってひりひり[ ？ ]。", "shihajimeru", "past"),
    ("hirihiri", "さっきぬった薬のせいで、傷口が今ひりひり[ ？ ]。", "shiteirutokoroda", "base"),
    ("zukizuki", "薬が切れて、頭がまたずきずき[ ？ ]。", "shidasu", "past"),
    ("zukizuki", "朝から頭が痛くて、今もずきずき[ ？ ]。", "shiteirutokoroda", "base"),
    ("betabeta", "汗をかいて、背中がだんだんべたべた[ ？ ]。", "shitekuru", "past"),
    ("betabeta", "あめを触ったので、指が今べたべた[ ？ ]。", "shiteirutokoroda", "base"),

    # --- emo_result：しているところだ／したところだ／してしまう ---
    ("bikkuri", "後ろから急に声をかけられて、たった今びっくり[ ？ ]。", "shitatokoroda", "base"),
    ("bikkuri", "急に名前を呼ばれて、思わずびっくり[ ？ ]。", "shiteshimau", "past"),
    ("gakkari", "試合が中止だと聞いて、たった今がっかり[ ？ ]。", "shitatokoroda", "base"),
    ("gakkari", "ずっと楽しみにしていたのに、すっかりがっかり[ ？ ]。", "shiteshimau", "past"),
    ("sukkiri", "長い悩みが解決して、今すっきり[ ？ ]。", "shiteirutokoroda", "base"),
    ("sukkiri", "話を聞いてもらって、たった今すっきり[ ？ ]。", "shitatokoroda", "base"),
    ("hotto",   "長い試験が終わって、たった今ほっと[ ？ ]。", "shitatokoroda", "base"),
    ("hotto",   "無事に着いたと聞いて、思わずほっと[ ？ ]。", "shiteshimau", "past"),

    # --- emo_moment：してしまう のみ ---
    ("iratto",   "横入りされて、一瞬いらっと[ ？ ]。", "shiteshimau", "past"),
    ("iratto",   "疲れているときは、小さなことでもいらっと[ ？ ]。", "shiteshimau", "base"),
    ("mukatto",  "失礼なことを言われて、思わずむかっと[ ？ ]。", "shiteshimau", "past"),
    ("mukatto",  "あんな言い方をされると、誰でもむかっと[ ？ ]。", "shiteshimau", "base"),
    ("zukitto",  "立ち上がった瞬間、ひざがずきっと[ ？ ]。", "shiteshimau", "past"),
    ("zukitto",  "無理に動かすと、ひざが一瞬ずきっと[ ？ ]。", "shiteshimau", "base"),
    ("kuratto",  "急に立ち上がって、一瞬くらっと[ ？ ]。", "shiteshimau", "past"),
    ("kuratto",  "寝不足だと、立った瞬間にくらっと[ ？ ]。", "shiteshimau", "base"),
    ("furatto",  "疲れていて、歩き出した瞬間ふらっと[ ？ ]。", "shiteshimau", "past"),
    ("furatto",  "熱があると、立ち上がったときにふらっと[ ？ ]。", "shiteshimau", "base"),
    ("chikutto", "注射の針が入った瞬間、ちくっと[ ？ ]。", "shiteshimau", "past"),
    ("chikutto", "傷に薬をぬると、一瞬ちくっと[ ？ ]。", "shiteshimau", "base"),
    ("katto",    "ばかにされて、一瞬かっと[ ？ ]。", "shiteshimau", "past"),
    ("katto",    "強く言い返されると、ついかっと[ ？ ]。", "shiteshimau", "base"),

    # --- act_high_vol：するところだ／しようとする／しはじめる／しつづける／しているところだ／してしまう ---
    ("burabura", "これから、商店街をぶらぶら[ ？ ]。", "surutokoroda", "base"),
    ("burabura", "行く先も決めず、一時間も公園をぶらぶら[ ？ ]。", "shitsuzukeru", "past"),
    ("urouro",   "道がわからなくて、駅の周りをうろうろ[ ？ ]。", "shihajimeru", "past"),
    ("urouro",   "今、出口を探して駅の中をうろうろ[ ？ ]。", "shiteirutokoroda", "base"),
    ("urochoro", "子どもが、部屋の中をうろちょろ[ ？ ]。", "shihajimeru", "past"),
    ("urochoro", "今、子どもが庭でうろちょろ[ ？ ]。", "shiteirutokoroda", "base"),

    # --- act_high_novol：しはじめる／しだす／しつづける／しているところだ／してしまう ---
    ("orooro",     "突然のトラブルに、急におろおろ[ ？ ]。", "shidasu", "past"),
    ("orooro",     "どうしていいかわからず、今もおろおろ[ ？ ]。", "shiteirutokoroda", "base"),
    ("kyorokyoro", "初めての駅で、あたりをきょろきょろ[ ？ ]。", "shihajimeru", "past"),
    ("kyorokyoro", "落ち着かないようすで、さっきからあたりをきょろきょろ[ ？ ]。", "shitsuzukeru", "past"),
    ("magomago",   "切符の買い方がわからず、急にまごまご[ ？ ]。", "shidasu", "past"),
    ("magomago",   "乗り換えがわからず、今改札の前でまごまご[ ？ ]。", "shiteirutokoroda", "base"),
    ("sowasowa",   "発表の順番が近づいて、急にそわそわ[ ？ ]。", "shidasu", "past"),
    ("sowasowa",   "時計を気にしながら、さっきからそわそわ[ ？ ]。", "shitsuzukeru", "past"),
    ("dogimagi",   "急に話しかけられて、すっかりどぎまぎ[ ？ ]。", "shiteshimau", "past"),
    ("dogimagi",   "名前を呼ばれて、急にどぎまぎ[ ？ ]。", "shidasu", "past"),
    ("yoroyoro",   "重い荷物を持って、足元がよろよろ[ ？ ]。", "shihajimeru", "past"),
    ("yoroyoro",   "今、荷物を抱えて階段をよろよろ[ ？ ]。", "shiteirutokoroda", "base"),
    ("atafuta",    "寝坊して、朝からあたふた[ ？ ]。", "shitsuzukeru", "past"),
    ("atafuta",    "約束の時間に気づいて、急にあたふた[ ？ ]。", "shidasu", "past"),

    # --- act_mid：しはじめる／しだす／してくる／しているところだ／してしまう ---
    ("nikoniko",  "うれしい知らせを聞いて、彼女はにこにこ[ ？ ]。", "shihajimeru", "past"),
    ("nikoniko",  "話を聞きながら、彼女は今にこにこ[ ？ ]。", "shiteirutokoroda", "base"),
    ("gikushaku", "けんかのあとで、二人の関係がだんだんぎくしゃく[ ？ ]。", "shitekuru", "past"),
    ("gikushaku", "あの一言から、急に会話がぎくしゃく[ ？ ]。", "shidasu", "past"),
    ("zawazawa",  "授業が始まる前で、教室がだんだんざわざわ[ ？ ]。", "shitekuru", "past"),
    ("zawazawa",  "先生が出て行くと、教室が急にざわざわ[ ？ ]。", "shidasu", "past"),
    ("kirakira",  "日が暮れて、星がきらきら[ ？ ]。", "shihajimeru", "past"),
    ("kirakira",  "今、夜空の星がきらきら[ ？ ]。", "shiteirutokoroda", "base"),

    # --- act_low_vol：しているところだ／してしまう ---
    ("gorogoro", "休みの日なので、今ソファでごろごろ[ ？ ]。", "shiteirutokoroda", "base"),
    ("gorogoro", "連休は、結局ずっと家でごろごろ[ ？ ]。", "shiteshimau", "past"),
    ("nonbiri",  "温泉に着いて、今のんびり[ ？ ]。", "shiteirutokoroda", "base"),
    ("nonbiri",  "予定を入れずに、一日のんびり[ ？ ]。", "shiteshimau", "past"),
    ("yukkuri",  "時間があるので、今ゆっくり[ ？ ]。", "shiteirutokoroda", "base"),
    ("yukkuri",  "話が長引いて、思ったよりゆっくり[ ？ ]。", "shiteshimau", "past"),

    # --- act_low_novol：していく／しているところだ／してしまう ---
    ("mesomeso", "失敗を思い出して、今もめそめそ[ ？ ]。", "shiteirutokoroda", "base"),
    ("mesomeso", "言われたことが気になって、ついめそめそ[ ？ ]。", "shiteshimau", "past"),
    ("daradara", "宿題をせずに、今もだらだら[ ？ ]。", "shiteirutokoroda", "base"),
    ("daradara", "テレビをつけたまま、一日だらだら[ ？ ]。", "shiteshimau", "past"),
    ("kuyokuyo", "済んだことを、まだくよくよ[ ？ ]。", "shiteirutokoroda", "base"),
    ("kuyokuyo", "考えても仕方ないのに、ついくよくよ[ ？ ]。", "shiteshimau", "past"),
    ("odoodo",   "怒られそうで、さっきからおどおど[ ？ ]。", "shiteirutokoroda", "base"),
    ("odoodo",   "初めての面接で、すっかりおどおど[ ？ ]。", "shiteshimau", "past"),
    ("bonyari",  "何も考えずに、窓の外をぼんやり[ ？ ]。", "shiteirutokoroda", "base"),
    ("bonyari",  "年をとって、昔の記憶がだんだんぼんやり[ ？ ]。", "shiteiku", "base"),
    ("guttari",  "暑さで力が出なくて、今ぐったり[ ？ ]。", "shiteirutokoroda", "base"),
    ("guttari",  "一日歩き回って、すっかりぐったり[ ？ ]。", "shiteshimau", "past"),
]


# =====================================================================
#  検証：構造化した前接条件から○×を計算し、研究資料の正解表と照合する
# =====================================================================
def _combines(cat, expr):
    """cat（カテゴリー辞書）と expr（表現形式辞書）が結びつくか"""
    for feat, req in (("continuity", expr["req_cont"]),
                      ("action", expr["req_act"]),
                      ("volition", expr["req_vol"])):
        allowed = [v for v in req.split("|") if v]
        if allowed and cat[feat] not in allowed:
            return False
    return True


def verify():
    cats = [{"id": c[0], "name": c[2], "kind": c[3],
             "continuity": c[4], "action": c[5], "volition": c[6]} for c in CATEGORIES]
    exprs = [{"key": e[0], "label": e[2],
              "req_cont": e[7], "req_act": e[8], "req_vol": e[9]} for e in EXPRESSIONS]

    errors = []

    # (1) 80セルの一致検証
    for c in cats:
        expected = set(CATEGORY_EXPRESSIONS[c["id"]])
        for e in exprs:
            calc = _combines(c, e)
            exp = e["key"] in expected
            if calc != exp:
                errors.append(
                    f'[条件不一致] {c["name"]} × 〜{e["label"]}：'
                    f'構造化条件の計算={"○" if calc else "×"} / 研究資料の正解={"○" if exp else "×"}')

    # (2) Step4 の正解キー検証
    word_cat = {w[0]: w[4] for w in WORDS}
    forms = {e[0]: {"base": e[15], "past": e[16]} for e in EXPRESSIONS}
    counts = {}
    for word_id, frame, key, form in PRACTICE:
        if word_id not in word_cat:
            errors.append(f"[未知の語] {word_id}")
            continue
        cat_id = word_cat[word_id]
        if key not in CATEGORY_EXPRESSIONS[cat_id]:
            errors.append(f'[Step4] 「{word_id}」（{cat_id}）に結びつかない形式が正解になっています：{key}')
        if key not in forms or form not in ("base", "past"):
            errors.append(f"[Step4] 活用形の指定が不正：{word_id} / {key} / {form}")
        if "[ ？ ]" not in frame:
            errors.append(f"[Step4] 空所 [ ？ ] がありません：{word_id} / {frame}")
        counts[word_id] = counts.get(word_id, 0) + 1

    # (3) 全語に2問あるか
    for w in WORDS:
        if counts.get(w[0], 0) != 2:
            errors.append(f'[Step4] 「{w[1]}」の問題数が {counts.get(w[0], 0)} 問です（2問必要）')

    # (3b) 段階ごとの学習コンテンツ（チェックリスト・対比ペア・思考ガイド）
    stage_keys = ["continuity", "action", "volition", "phon", "category"]
    cat_of = {w[0]: w[4] for w in WORDS}
    cat_feat = {c[0]: {"continuity": c[4], "action": c[5], "volition": c[6], "kind": c[3]}
                for c in CATEGORIES}
    ex_steps = {}
    for st, o, q, a in WORKED_STEPS:
        ex_steps.setdefault(st, []).append(o)
    ex_words = {e[0]: e[1] for e in WORKED_EXAMPLES}

    for st in stage_keys:
        if not [g for g in STAGE_GUIDES if g[0] == st]:
            errors.append(f"[学習] 段階「{st}」に判断手順チェックリストがありません")
        pairs = [p for p in CONTRAST_PAIRS if p[0] == st]
        if len(pairs) < 2:
            errors.append(f"[学習] 段階「{st}」の対比ペアが {len(pairs)} 組しかありません")
        if st not in ex_words:
            errors.append(f"[学習] 段階「{st}」に思考ガイドの例題がありません")
        elif len(ex_steps.get(st, [])) < 3:
            errors.append(f"[学習] 段階「{st}」の思考ガイドの手順が少なすぎます")

    for st, o, wa, wb, feat, point in CONTRAST_PAIRS:
        for wid in (wa, wb):
            if wid not in cat_of:
                errors.append(f"[学習] 対比ペアに未知の語：{wid}")
        if feat and wa in cat_of and wb in cat_of:
            va = cat_feat[cat_of[wa]][feat]
            vb = cat_feat[cat_of[wb]][feat]
            if va == vb:
                errors.append(
                    f"[学習] 対比ペア {wa}／{wb} は {feat} が同じ値（{va}）で、対比になっていません")

    for st, wid, concl, note in WORKED_EXAMPLES:
        if wid not in cat_of:
            errors.append(f"[学習] 思考ガイドに未知の語：{wid}")

    # (4) 誤答選択肢が2つ以上作れるか（結びつかない形式が2つ以上あるか）
    for c in cats:
        n_ng = len(exprs) - len(CATEGORY_EXPRESSIONS[c["id"]])
        if n_ng < 2:
            errors.append(f'[Step4] {c["name"]} は誤答候補が {n_ng} 個しかありません')

    return errors


# =====================================================================
#  DB 構築
# =====================================================================
def main():
    errors = verify()
    if errors:
        print("検証エラーのためDBを作成しませんでした：")
        for e in errors:
            print("  - " + e)
        sys.exit(1)

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
        key       TEXT PRIMARY KEY,
        ord       INTEGER NOT NULL,
        label     TEXT NOT NULL,
        term      TEXT NOT NULL,
        example   TEXT NOT NULL,
        hint      TEXT NOT NULL,
        pred_cont TEXT NOT NULL,
        pred_act  TEXT NOT NULL,
        pred_note TEXT NOT NULL
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
        expr_explain TEXT NOT NULL,
        why_cont     TEXT NOT NULL,
        why_act      TEXT NOT NULL,
        why_vol      TEXT NOT NULL
    );
    CREATE TABLE expressions (
        key        TEXT PRIMARY KEY,
        ord        INTEGER NOT NULL,
        label      TEXT NOT NULL,
        phase      TEXT NOT NULL,
        grp        TEXT NOT NULL,            -- 局面グループ
        cond_text  TEXT NOT NULL,            -- 学習者向けの前接条件表示
        example    TEXT NOT NULL,
        req_cont   TEXT NOT NULL,            -- "" は不問
        req_act    TEXT NOT NULL,
        req_vol    TEXT NOT NULL,
        why_cont   TEXT NOT NULL,
        why_act    TEXT NOT NULL,
        why_vol    TEXT NOT NULL,
        ok_example TEXT NOT NULL,
        ng_example TEXT NOT NULL,
        form_base  TEXT NOT NULL,
        form_past  TEXT NOT NULL
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
        meaning     TEXT NOT NULL
    );
    CREATE TABLE practice (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id     TEXT NOT NULL REFERENCES words(id),
        ord         INTEGER NOT NULL,
        frame       TEXT NOT NULL,
        correct_key TEXT NOT NULL REFERENCES expressions(key),
        form        TEXT NOT NULL
    );
    CREATE TABLE stage_guides (
        stage    TEXT NOT NULL,
        ord      INTEGER NOT NULL,
        question TEXT NOT NULL,
        detail   TEXT NOT NULL
    );
    CREATE TABLE contrast_pairs (
        stage   TEXT NOT NULL,
        ord     INTEGER NOT NULL,
        word_a  TEXT NOT NULL REFERENCES words(id),
        word_b  TEXT NOT NULL REFERENCES words(id),
        feature TEXT NOT NULL,
        point   TEXT NOT NULL
    );
    CREATE TABLE worked_examples (
        stage      TEXT PRIMARY KEY,
        word_id    TEXT NOT NULL REFERENCES words(id),
        conclusion TEXT NOT NULL,
        note       TEXT NOT NULL
    );
    CREATE TABLE worked_steps (
        stage    TEXT NOT NULL,
        ord      INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer   TEXT NOT NULL
    );
    """)

    cur.executemany("INSERT INTO knowledge VALUES (?,?,?,?,?)", KNOWLEDGE)
    cur.executemany("INSERT INTO phon_forms VALUES (?,?,?,?,?,?,?,?,?)", PHON_FORMS)
    cur.executemany("INSERT INTO categories VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", CATEGORIES)
    cur.executemany("INSERT INTO expressions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", EXPRESSIONS)
    for cat_id, keys in CATEGORY_EXPRESSIONS.items():
        cur.executemany("INSERT INTO category_expression VALUES (?,?)",
                        [(cat_id, k) for k in keys])
    cur.executemany("INSERT INTO words VALUES (?,?,?,?,?,?,?)", WORDS)
    cur.executemany("INSERT INTO stage_guides VALUES (?,?,?,?)", STAGE_GUIDES)
    cur.executemany("INSERT INTO contrast_pairs VALUES (?,?,?,?,?,?)", CONTRAST_PAIRS)
    cur.executemany("INSERT INTO worked_examples VALUES (?,?,?,?)", WORKED_EXAMPLES)
    cur.executemany("INSERT INTO worked_steps VALUES (?,?,?,?)", WORKED_STEPS)

    ords = {}
    for word_id, frame, key, form in PRACTICE:
        o = ords.get(word_id, 0)
        ords[word_id] = o + 1
        cur.execute("INSERT INTO practice (word_id, ord, frame, correct_key, form) VALUES (?,?,?,?,?)",
                    (word_id, o, frame, key, form))

    con.commit()
    con.close()
    print(f"OK: {DB_PATH} を作成しました"
          f"（単語 {len(WORDS)} 語 / カテゴリー {len(CATEGORIES)} / 表現形式 {len(EXPRESSIONS)} / 例文 {len(PRACTICE)} 問）")
    print("検証：前接条件 × カテゴリー "
          f"{len(CATEGORIES) * len(EXPRESSIONS)} セルが研究資料の正解表と一致しました。")


if __name__ == "__main__":
    main()
