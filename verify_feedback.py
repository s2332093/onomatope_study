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


# No answer reveal after any number of errors. Only the selected figure is shown.
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
                assert main.FEATURE_FIGS[fkey][wrong] in r.text and main.FEATURE_FIGS[fkey][correct] not in r.text
                if k == 5:
                    assert f'href="/a/word/{word["id"]}/f1/5"' in r.text
                    assert '動作性から見直す' not in r.text
                    assert main.feature_reason(word, 'volition').replace('、','，').replace('。','．') in r.text
                else:
                    assert f'href="/a/word/{word["id"]}/f1/{k-1}?review_for={k}"' in r.text
            elif k==1: assert '近いオノマトペは「'+main.WORD_BY_ID[wrong]['word']+'」' in r.text
            else:
                assert main.PHON_FIGS[wrong] in r.text and main.PHON_FIGS[correct] not in r.text
                assert main.PHON_BY_KEY[wrong]['label']+'の並びと「'+word['word']+'」の並びは一致しません。' in r.text
            repeat=fresh.post(f'/a/word/{word["id"]}/f1/{k}/check',data=data)
            assert repeat.context['failures']==attempt+1
r=submit(1,'bikkuri')
assert '「突然のことに驚く」に近いオノマトペは「びっくり」です。もう一度選んでみましょう。' in r.text
r=submit(2,'nri')
assert '「ん＋り」型の並びと「いらいら」の並びは一致しません。' in r.text
assert client.post(f'{base}/f1/4/continue',follow_redirects=False).headers['location']==f'{base}/f1/4'
r=submit(4,'高');assert 'act_high.svg' in r.text and 'act_mid.svg' not in r.text
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
assert not r.context['extra_results'] and '<table' not in r.text
assert '正解の線結び' not in r.text and '/f3"' not in r.text

# Invalid selected links show only their prerequisites; correct forms stay undisclosed.
invalid = next(e for e in main.EXPRESSIONS if e['key'] not in correct)
submitted = {invalid['key']: '○'}
r = client.post(f'{base}/f2/check', data=submitted)
assert [e['key'] for e in r.context['extra_results']] == [invalid['key']]
assert r.text.count('<table') == 1
assert 'が合わない理由' not in r.text
assert '<th scope="col">「いらいら」の素性</th>' in r.text
assert '× 合わない' in r.text and 'var(--red-soft)' in r.text
for c in r.context['extra_results'][0]['checks']: assert c['req'] in r.text
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
assert '<table' not in r.text and '正解の線結び' not in r.text
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

# In-place judging returns only invalid submitted links; it never returns missing identities.
json_headers = {'Accept': 'application/json'}
one_valid = next(iter(correct))
response = client.post(f'{base}/f2/check', data={invalid['key']: '○', one_valid: '○'}, headers=json_headers)
assert response.status_code == 200
judgment = response.json()
assert judgment['invalid_keys'] == [invalid['key']]
assert judgment['invalid_conditions'] == {invalid['key']:invalid['cond_text']}
assert judgment['has_missing'] and not judgment['all_correct']
assert set(judgment) == {'all_correct', 'invalid_keys', 'invalid_conditions', 'has_missing', 'feedback_html', 'context_url'}
assert '<th scope="col">' + invalid['label'] + 'の条件</th>' in judgment['feedback_html']
assert 'invalid-expression' not in judgment['feedback_html']
assert 'href="#step3Form"' in judgment['feedback_html']
missing_only = client.post(f'{base}/f2/check', data={}, headers=json_headers).json()
assert missing_only['invalid_keys'] == [] and missing_only['invalid_conditions'] == {} and missing_only['has_missing']
assert '<table' not in missing_only['feedback_html']
right = client.post(f'{base}/f2/check', data=correct, headers=json_headers).json()
assert right['all_correct'] and not right['has_missing'] and right['invalid_keys'] == [] and right['invalid_conditions'] == {}
assert right['context_url'] == f'{base}/f3'
assert client.post('/b/word/iraira/f2/check', data=correct, headers=json_headers).status_code == 404

# Conditions are sent only for invalid connected forms; comparison matches all 3 features.
initial=client.get('/a/word/bikkuri/f2').text
assert 'id="btnCond"' not in initial and 'hint-cond' not in initial
assert initial.count('class="answer-condition small" hidden></div>')==len(main.EXPRESSIONS)
for w in main.WORDS:
    cat=main.get_category(w)
    good=next(e for e in main.EXPRESSIONS if main.expr_combines(cat,e))
    for e in main.EXPRESSIONS:
        if main.expr_combines(cat,e): continue
        r=client.post(f'/a/word/{w["id"]}/f2/check',data={e['key']:'○',good['key']:'○'},headers=json_headers).json()
        assert r['invalid_conditions']=={e['key']:e['cond_text']}
        assert r['feedback_html'].count('<table')==1
        assert f'「{w["word"]}」と「〜{e["label"]}」の比較' in r['feedback_html']
        assert '× 合わない' in r['feedback_html']
        for fkey in ['continuity','action','volition']:
            assert main.val_label(fkey,cat[fkey]) in r['feedback_html']
        assert '「〜'+good['label']+'」の比較' not in r['feedback_html']
bikkuri=client.post('/a/word/bikkuri/f2/check',data={'shidasu':'○'},headers=json_headers).json()
assert bikkuri['invalid_conditions']=={'shidasu':'＋継続性・動作性（中・高）・意志的でないこと'}

print('OK: no reveal at any count, all 16 words and selected diagrams, concise feedback, no phase-1 hints, invalid-card-only conditions, accurate three-feature comparisons, preserved review flow and group isolation')
