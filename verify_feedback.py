"""Non-revealing feedback, selected diagrams, review paths and answer preservation."""
import os
import re
import tempfile
from pathlib import Path
os.environ['STUDY_LOG_PATH'] = str(Path(tempfile.mkdtemp()) / 'feedback.db')
from fastapi.testclient import TestClient
os.environ['STUDY_REQUIRE_NAME'] = '0'
import main
import learning_state

client = TestClient(main.app)
base = '/a/word/iraira'


def submit(k, choice, review_for=None, attempt_id=None):
    page = client.get(f'{base}/f1/{k}')
    data = {'choice': choice, 'attempt_id': attempt_id or re.search(r'name="attempt_id" value="([^"]+)"', page.text)[1]}
    if review_for:
        data['review_for'] = str(review_for)
    return client.post(f'{base}/f1/{k}/check', data=data)


# Repeated errors retain the selected diagram and show all generic reference diagrams, without marking the correct option.
for word in main.WORDS:
    fresh=TestClient(main.app)
    for k in range(1,6):
        fkey={3:'continuity',4:'action',5:'volition'}.get(k)
        correct=word['id'] if k==1 else word['phon'] if k==2 else main.get_category(word)[fkey]
        choices=list(main.WORD_BY_ID) if k==1 else list(main.PHON_BY_KEY) if k==2 else list(main.FEATURE_FIGS[fkey])
        wrong=next(v for v in choices if v!=correct)
        for attempt in range(5):
            data={'choice':wrong,'attempt_id':f'{k}-{attempt}'}
            r=fresh.post(f'/a/word/{word["id"]}/f1/{k}/check',data=data)
            assert r.status_code==200 and set(r.context['fb'])=={'ok','user'}
            assert r.context['failures']==attempt+1
            assert all(text not in r.text for text in ['正解：','知識を確認','回で知識を表示','選んだ答えの捉え方','場面と合わない点','確かめること'])
            if fkey:
                assert all(fig in r.text for fig in main.FEATURE_FIGS[fkey].values())
                assert len(r.context["feedback_feature_options"]) == 3
                if k == 5:
                    assert f'href="/a/word/{word["id"]}/f1/5"' in r.text
                    assert '動作性から見直す' not in r.text
                    if main.get_category(word)['kind'] == '感情・感覚':
                        message = r.context['retry_feedback']['message']
                        assert '意味をもう一度確かめ' in message
                        assert '感情・感覚を表すオノマトペかどうか' in message
                        assert not any(v in message for v in ('「ー」', 'ー意志性', '意志性は', 'ため'))
                    else:
                        message = r.context['retry_feedback']['message']
                        assert '自分でその動作・過ごし方を選べるのか' in message
                        assert not any(v in message for v in ('意志性は', '「＋」', '「ー」', 'ため'))
                else:
                    assert f'href="/a/word/{word["id"]}/f1/{k-1}?review_for={k}"' in r.text
            elif k==1: assert '近いオノマトペは「'+main.WORD_BY_ID[wrong]['word']+'」' in r.text
            else:
                assert main.PHON_FIGS[wrong] in r.text
                assert all(fig in r.text for fig in main.PHON_FIGS.values())
                assert main.PHON_BY_KEY[wrong]['label']+'の並びと「'+word['word']+'」の並びは一致しません。' in r.text
            repeat=fresh.post(f'/a/word/{word["id"]}/f1/{k}/check',data=data)
            assert repeat.context['failures']==attempt+1
r=submit(1,'bikkuri')
assert '「突然のことに驚く」に近いオノマトペは「びっくり」です。もう一度選んでみましょう。' in r.text
r=submit(2,'nri')
assert '「ん＋り」型の並びと「いらいら」の並びは一致しません。' in r.text
assert client.post(f'{base}/f1/4/continue',follow_redirects=False).headers['location']==f'{base}/f1/4'
r=submit(4,'高');assert 'act_high.svg' in r.text and 'act_mid.svg' in r.text
r=submit(3,'ー',review_for=4);assert f'href="{base}/f1/2?review_for=4"' in r.text
r=submit(2,'repeat',review_for=4);assert f'href="{base}/f1/3?review_for=4"' in r.text
r=submit(3,'＋',review_for=4);assert f'href="{base}/f1/4"' in r.text
r=submit(4,'中');assert r.context['fb']['ok'] and '正解です' in r.text
assert submit(4,'高').context['failures']==1
for suffix in ['f1/1','f1/2','f1/3','f1/4','f1/5','f1/done']:
    page=client.get(base+'/'+suffix).text
    assert all(label not in page for label in ['迷ったら','判断の手順','似た語との違い','別の語で練習'])
assert 'class="hint-toggle"' not in client.get('/a/drill/features').text
b=client.post('/b/word/iraira/meaning/check',data={'choice':'bikkuri'})
assert '近いオノマトペは「びっくり」' in b.text and '正しい意味' not in b.text and '/b/word/iraira/f3' not in b.text


# Five choices, target-free feedback tables, and omission of the feature being retried.
for word in main.WORDS:
    phon_page = client.get(f'/a/word/{word["id"]}/f1/2')
    options = phon_page.context['q']['phon_opts']
    assert len(options) == 5 and {o['value'] for o in options} == set(main.PHON_BY_KEY)
    assert '例：' not in phon_page.text and all('example' not in o for o in options)
    assert f'href="/a/word/{word["id"]}/f1/2/kind"' in phon_page.text
    for k, hidden in [(2, 'both'), (3, 'both')]:
        feature = {3: 'continuity', 4: 'action'}.get(k)
        correct = word['phon'] if k == 2 else main.get_category(word)[feature]
        choices = main.PHON_BY_KEY if k == 2 else main.FEATURE_FIGS[feature]
        wrong = next(v for v in choices if v != correct)
        response = client.post(f'/a/word/{word["id"]}/f1/{k}/check', data={'choice':wrong})
        table = re.search(r'<table class="dtable phon-reference-table".*?</table>', response.text, re.S)[0]
        assert word['word'] not in table
        assert all('/static/' + fig in table for fig in main.PHON_FIGS.values())
        assert ('<th>継続性の予測</th>' in table) == (hidden not in ('continuity', 'both'))
        assert ('<th>動作性の予測</th>' in table) == (hidden not in ('action', 'both'))
        if hidden == 'both':
            assert '<th>例外</th>' not in table
            assert '<h2>音の形</h2>' in response.text
            assert all(not row['exceptions'] for row in response.context['feedback_phon_table'])
        else:
            assert all(main.FEATURE_NAME[hidden] not in e for row in response.context['feedback_phon_table'] for e in row['exceptions'])
    assert '音の形にも手がかりがある' not in phon_page.text
    assert 'class="flow"' not in phon_page.text
    assert f'「{word["word"]}」の音の形は？' in phon_page.text

# Continuity never displays the answer-bearing phonology hint. Its feedback links the three diagrams to sound shapes.
for word in main.WORDS:
    base_word = f'/a/word/{word["id"]}'
    continuity = client.get(base_word + '/f1/3')
    assert not continuity.context['q']['flow']['why']
    assert main.PHON_BY_KEY[word['phon']]['hint'] not in continuity.text
    wrong = next(v for v in main.FEATURE_FIGS['continuity'] if v != main.get_category(word)['continuity'])
    response = client.post(base_word + '/f1/3/check', data={'choice': wrong})
    for label in ('2モーラ反復形', '「っ＋り」型', '「っ」でおわる型'):
        assert '音の形：' + label in response.text
    cat = main.get_category(word)
    wrong = next(v for v in main.FEATURE_FIGS['action'] if v != cat['action'])
    response = client.post(base_word + '/f1/4/check', data={'choice': wrong})
    if cat['kind'] == '感情・感覚':
        assert response.context['feedback_phon_table'] == main.build_phon_table()
        assert '<th>継続性の予測</th>' in response.text and '<th>動作性の予測</th>' in response.text
        assert 'id="example-action"' not in response.text
    else:
        assert not response.context['feedback_phon_table']
        assert 'id="example-action"' in response.text
        assert '例題：「ぶらぶら」の素性を考える' in response.text
        assert 'id="example"' not in response.text and 'id="example-transfer"' not in response.text

# Meaning now leads through a separately graded two-choice kind question, before choosing sound shape.
for word in main.WORDS:
    base_word = f'/a/word/{word["id"]}'
    meaning = client.post(base_word + '/f1/1/check', data={'choice': word['id']})
    assert f'href="{base_word}/f1/2/kind"' in meaning.text
    page = client.get(base_word + '/f1/2/kind?review_for=4')
    assert page.text.count('<input type="radio"') == 2
    assert f'「{word["word"]}」は何を表すオノマトペですか？' in page.text
    kind = main.get_category(word)['kind']
    wrong = '動作' if kind == '感情・感覚' else '感情・感覚'
    response = client.post(base_word + '/f1/2/kind/check', data={'choice': wrong, 'review_for': '4'})
    assert not response.context['feedback']['ok'] and '× 不正解です' in response.text
    assert f'href="{base_word}/f1/2?review_for=4"' not in response.text
    response = client.post(base_word + '/f1/2/kind/check', data={'choice': kind, 'review_for': '4'})
    assert response.context['feedback']['ok'] and f'href="{base_word}/f1/2?review_for=4"' in response.text
    assert client.get('/b' + base_word[2:] + '/f1/2/kind').status_code == 404
    assert client.post('/b' + base_word[2:] + '/f1/2/kind/check', data={'choice': kind}).status_code == 404

# Home cards provide no meaning/scene answers. Only A groups words by the two broad kinds.
for prefix in ('/a', '/b'):
    home = client.get(prefix + '/').text
    assert all(word['scene'] not in home and word['meaning'] not in home for word in main.WORDS)
    assert all(cat['name'] not in home for cat in main.CATEGORIES)
assert [g['kind'] for g in main.word_groups()] == ['感情・感覚', '動作']
intro_page = client.get('/a/reference').text
assert intro_page.index('<summary>素性の一覧') < intro_page.index('<summary>音の形') < intro_page.index('<summary>文法形式')
assert '素性の組み合わせと8つのカテゴリー' not in intro_page
assert 'id="study-scope"' in intro_page
assert intro_page.count('class="knowledge-tag"') == 3
assert 'この3つの知識を確認してから' in intro_page
grammar = re.search(r'<section id="grammar".*?</section>', intro_page, re.S)[0]
assert '<th>例</th>' not in grammar
assert all(e['ok_example'] not in grammar for e in main.EXPRESSIONS)

assert 'この研究では，感情・感覚を表すオノマトペと，動作を表すオノマトペを扱います．' in intro_page
assert '結びつく形式を，理由を考えて選ぶ練習です．' not in client.get('/a/word/iraira/f2').text
assert 'learning-scene' in client.get('/a/word/iraira/f1/1').text
assert 'learning-scene' in client.get('/b/word/iraira').text
assert not any(q['spec'].startswith('C:') for q in client.get('/a/drill/features').context['questions'])

# Grammar knowledge is introductory content; phase 2 starts directly with matching.
intro = client.get('/a/reference')
assert '学習前の知識：素性と文法形式' in intro.text
assert 'id="grammar"' in intro.text and '例題：「いらいら」の素性を考える' in intro.text
assert len(intro.context['expr_cards']) == len(main.EXPRESSIONS)
assert 'フェーズ2' not in intro.text
assert 'フェーズ1で学んだ判断' not in intro.text
summary = client.get(f'{base}/f1/done')
assert 'expr_explain' not in summary.text and main.get_category(main.WORD_BY_ID['iraira'])['expr_explain'] not in summary.text
assert '迷ったら：' not in summary.text and 'done-guides' not in summary.text
assert f'href="{base}/f2"' in summary.text and '/f2/learn' not in summary.text
legacy = client.get(f'{base}/f2/learn', follow_redirects=False)
assert legacy.status_code == 303 and legacy.headers['location'] == '/a/reference#grammar'
assert '/f2/learn' not in client.get(base).text

# Initial entry, unsubmitted context questions and legacy stored errors do not show a return notice.
notice = '線結びで、条件を確かめ直しましょう'
assert notice not in client.get(f'{base}/f2?review=not-issued').text
client.get(f'{base}/f3')
assert notice not in client.get(f'{base}/f2').text
learning_state.update(client.cookies['study_participant'], 'experiment', 'iraira',
    lambda s: s.update(context_review=[{'no': 1, 'frame': 'old', 'choice': 'old', 'reason': 'old'}]))
assert notice not in client.get(f'{base}/f2').text

# A missing line produces only a generic reminder, without listing its identity.
word = main.WORD_BY_ID['iraira']
correct = {k: '○' for k in main.CAT_EXPRS[word['category_id']]}
r = client.post(f'{base}/f2/check', data={})
assert 'まだ結べていない形式があります' in r.text
assert not r.context['selected_results'] and '<table' not in r.text
assert '正解の線結び' not in r.text and '/f3"' not in r.text

# Invalid selected links show only their prerequisites; correct forms stay undisclosed.
invalid = next(e for e in main.EXPRESSIONS if e['key'] not in correct)
submitted = {invalid['key']: '○'}
r = client.post(f'{base}/f2/check', data=submitted)
assert [e['key'] for e in r.context['selected_results']] == [invalid['key']]
assert r.text.count('<table') == 1
assert 'が合わない理由' not in r.text
assert '<th scope="col">「いらいら」の素性</th>' in r.text
assert '× 合わない' in r.text and 'var(--red-soft)' in r.text
for c in r.context['selected_results'][0]['checks']: assert c['req'] in r.text
for e in main.EXPRESSIONS:
    if e['key']!=invalid['key']: assert '「〜'+e['label']+'」の比較' not in r.text
assert 'まだ結べていない形式があります' in r.text
assert '正解の線結び' not in r.text
assert '<th scope="col">' + invalid['label'] + 'の条件</th>' in r.text
assert '<th>必要な条件</th>' not in r.text
assert 'invalid-expression' not in r.text
retry_url = '/a' + r.context['retry_url']
retry = client.get(retry_url)
assert f'id="input-{invalid["key"]}" value="○"' in retry.text
assert 'matching_retry_token' not in retry.text
assert '>消す</button>' in retry.text and '>✕</button>' not in retry.text
other = TestClient(main.app).get(f'{base}/f2')
assert f'id="input-{invalid["key"]}" value="×"' in other.text
assert '線結びで、条件を確かめ直しましょう' not in other.text
assert client.get('/b/word/iraira/f2').status_code == 404
new_start = client.get(f'{base}/f2')
assert not new_start.context['saved_connections']
assert not client.get(retry_url).context['saved_connections']

r = client.post(f'{base}/f2/check', data=correct)
assert '10 / 10 正解' in r.text and f'href="{base}/f3"' in r.text
assert r.text.count('<table') == len(correct) and '正解の線結び' not in r.text
fresh_match = client.get(f'{base}/f2')
assert not fresh_match.context['saved_connections']
assert re.findall(r'id="input-[^"]+" value="([^"]+)"', fresh_match.text) == ['×'] * len(main.EXPRESSIONS)
assert not client.get(retry_url).context['saved_connections']

# Context mistakes return immediately to matching without a correct completed sentence.
page = client.get(f'{base}/f3')
questions = page.context['questions']
data = {}
for q in questions:
    data[f'opt_keys_{q["idx"]}'] = q['opt_keys']
    data[f'choice_{q["idx"]}'] = next(o['key'] for o in q['options'] if o['key'] != q['correct_key'])
r = client.post(f'{base}/f3/check', data=data, follow_redirects=False)
assert r.status_code == 303 and r.headers['location'].startswith(f'{base}/f2?review=')
review = client.get(r.headers['location'])
review_token = review.context['review_token']
assert '場面・文脈の問題から戻りました' in review.text
assert len(review.context['context_review']) == len(questions)
for q in questions:
    assert q['text'] in review.text
    completed = q['text'].replace('[ ？ ]', '〈' + main.EXPR_BY_KEY[q['correct_key']][main.FORM_COL[q['form']]] + '〉')
    assert completed not in review.text
assert not review.context['saved_connections']
for key in correct:
    assert f'id="input-{key}" value="×"' in review.text
# An incorrect matching answer can be edited within the current context-review flow.
wrong_match = client.post(f'{base}/f2/check', data={invalid['key']: '○', 'review_token': review_token})
assert '<th scope="col">' + invalid['label'] + 'の条件</th>' in wrong_match.text
repair = client.get('/a' + wrong_match.context['retry_url'])
assert repair.context['review_token'] == review_token
assert repair.context['saved_connections'] == [invalid['key']]
r = client.post(f'{base}/f2/check', data={**correct, 'review_token': review_token})
assert '文脈問題に戻る' in r.text
back = client.get('/a' + r.context['context_url'])
assert [q['opt_keys'] for q in back.context['questions']] == [q['opt_keys'] for q in questions]
for q in questions:
    selected = data[f'choice_{q["idx"]}']
    assert f'name="choice_{q["idx"]}" value="{selected}" checked' in back.text
right = {f'choice_{q["idx"]}': q['correct_key'] for q in questions}
r = client.post(f'{base}/f3/check', data=right)
assert '全問正解' in r.text and '/complete' in r.text
assert not client.get(f'{base}/f2').context['context_review']

# A completed or explicitly restarted learning flow cannot show its previous error notice.
assert notice not in client.get(f'{base}/f2?review={review_token}').text
client.get(f'{base}/f3')
failed = client.post(f'{base}/f3/check', data={}, follow_redirects=False)
old_return = failed.headers['location']
assert notice in client.get(old_return).text
assert notice not in client.get(f'{base}/f2').text
assert notice not in client.get(old_return).text

# Judging stays neutral in the answer area. Every selected form, correct or incorrect, has a comparison in feedback.
json_headers = {'Accept': 'application/json'}
one_valid = next(iter(correct))
response = client.post(f'{base}/f2/check', data={invalid['key']: '○', one_valid: '○'}, headers=json_headers)
assert response.status_code == 200
judgment = response.json()
assert set(judgment) == {'feedback_html'}
assert '<th scope="col">' + invalid['label'] + 'の条件</th>' in judgment['feedback_html']
assert '<th scope="col">' + main.EXPR_BY_KEY[one_valid]['label'] + 'の条件</th>' in judgment['feedback_html']
assert judgment['feedback_html'].count('<table') == 2
assert 'href="#step3Form"' in judgment['feedback_html']
missing_only = client.post(f'{base}/f2/check', data={}, headers=json_headers).json()
assert 'まだ結べていない形式があります' in missing_only['feedback_html'] and '<table' not in missing_only['feedback_html']
right = client.post(f'{base}/f2/check', data=correct, headers=json_headers).json()
assert '○ 正解です！' in right['feedback_html'] and right['feedback_html'].count('<table') == len(correct)
assert f'href="{base}/f3"' in right['feedback_html']
assert client.post('/b/word/iraira/f2/check', data=correct, headers=json_headers).status_code == 404
initial = client.get('/a/word/bikkuri/f2').text
assert 'markInvalid' not in initial and 'invalid-answer' not in initial and 'answer-condition' not in initial
assert 'showMatchingStatus(result.all_correct' not in initial and 'matchingNext' not in initial
assert '回答を受け付けました．フィードバックを確認してください．' in initial
for w in main.WORDS:
    cat = main.get_category(w)
    for connected in ([e for e in main.EXPRESSIONS], [next(e for e in main.EXPRESSIONS if main.expr_combines(cat, e))]):
        r = client.post(f'/a/word/{w["id"]}/f2/check', data={e['key']: '○' for e in connected}, headers=json_headers).json()
        assert r['feedback_html'].count('<table') == len(connected)
        for e in connected:
            assert f'「{w["word"]}」と「〜{e["label"]}」の比較' in r['feedback_html']
        for fkey in ['continuity', 'action', 'volition']:
            assert main.val_label(fkey, cat[fkey]) in r['feedback_html']

print('OK: 16 words, separately graded kind question, five example-free sound choices, continuity diagrams, kind-specific action/volition feedback, all-selected matching tables, neutral answers and group isolation')
