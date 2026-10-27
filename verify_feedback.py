"""Retry thresholds, non-revealing feedback, review paths and answer preservation."""
import os
import re
import tempfile
from pathlib import Path
os.environ['STUDY_LOG_PATH'] = str(Path(tempfile.mkdtemp()) / 'feedback.db')
from fastapi.testclient import TestClient
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


# One or two errors show the submitted interpretation and its mismatch, no answer.
for count in (1, 2):
    r = submit(4, '高', attempt_id=f'dynamic-{count}')
    assert r.status_code == 200 and r.context['failures'] == count
    assert '場面と合わない点' in r.text and '選んだ答えの捉え方' in r.text
    assert '動作性（中）' not in r.text and 'act_mid.svg' not in r.text
    assert '正解：' not in r.text and '/f1/4/continue' not in r.text
    assert ('この問いをもう一度考える' in r.text) == (count == 2)
    assert (f'href="{base}/f1/4"' in r.text) == (count == 2)
    assert f'href="{base}/f1/3?review_for=4"' in r.text
    assert f'href="{base}/f1/5"' not in r.text
    # Refreshing a submitted form does not consume another attempt.
    repeat = submit(4, '高', attempt_id=f'dynamic-{count}')
    assert repeat.context['failures'] == count

# Early continue is rejected; this action does not reset the counter.
r = client.post(f'{base}/f1/4/continue', follow_redirects=False)
assert r.status_code == 303 and r.headers['location'] == f'{base}/f1/4'

# The review chain goes 4 -> 3 -> 2 -> 3 -> 4, preserving the original destination.
r = client.get(f'{base}/f1/3?review_for=4')
assert r.context['review_for'] == 4 and '継続性' in r.text and '動作性' in r.text
r = submit(3, 'ー', review_for=4)
assert f'href="{base}/f1/2?review_for=4"' in r.text
assert '正解：' not in r.text and 'cont_plus.svg' not in r.text
r = client.get(f'{base}/f1/2?review_for=4')
assert '音韻形態' in r.text and '継続性' in r.text
r = submit(2, 'repeat', review_for=4)
assert f'href="{base}/f1/3?review_for=4"' in r.text
r = submit(3, '＋', review_for=4)
assert f'href="{base}/f1/4"' in r.text

# Only the third failed answer reveals knowledge, and continuation requires a click.
r = submit(4, '高', attempt_id='dynamic-3')
assert r.context['reveal'] and '正解：動作性（中）' in r.text
assert 'この問いをもう一度' not in r.text
assert '知識を確認して継続性から見直す' in r.text
assert '意志性へ' not in r.text
assert f'action="{base}/f1/4/continue"' in r.text
r = client.post(f'{base}/f1/4/continue', follow_redirects=False)
assert r.headers['location'] == f'{base}/f1/3?review_for=4'
r = submit(4, '高')
assert r.context['failures'] == 1 and '正解：' not in r.text
r = submit(4, '中')
assert '正解です' in r.text
assert 'この問いをもう一度' not in r.text
r = submit(4, '高')
assert r.context['failures'] == 1

# Same POST token, changed answer (browser back) is a new, correctly graded submission.
r = submit(4, '中', attempt_id='changed-answer')
r = submit(4, '高', attempt_id='changed-answer')
assert not r.context['fb']['ok'] and r.context['failures'] == 1

# All stages and words hide the exact answer object and answer diagram on first error.
for word in main.WORDS:
    fresh = TestClient(main.app)
    for k in range(1, 6):
        cat = main.get_category(word)
        correct = {1: word['id'], 2: word['phon']}.get(k) or cat[{3:'continuity',4:'action',5:'volition'}[k]]
        choices = (list(main.WORD_BY_ID) if k == 1 else list(main.PHON_BY_KEY) if k == 2
                   else [o['value'] for o in main.feature_options({3:'continuity',4:'action',5:'volition'}[k])])
        for wrong in [v for v in choices if v != correct][:2]:
            response = fresh.post(f'/a/word/{word["id"]}/f1/{k}/check', data={'choice': wrong})
            assert response.status_code == 200 and not response.context['reveal']
            assert set(response.context['fb']) == {'ok', 'user'}
            assert '正解：' not in response.text
            assert ('この問いをもう一度考える' in response.text) == (response.context['failures'] == 2)
            assert 'から見直す' in response.text
        if k in (3, 4, 5):
            wrong = next(v for v in choices if v != correct)
            response = fresh.post(f'/a/word/{word["id"]}/f1/{k}/check', data={'choice': wrong})
            assert response.context['reveal']
            back = fresh.post(f'/a/word/{word["id"]}/f1/{k}/continue', follow_redirects=False)
            assert back.headers['location'] == f'/a/word/{word["id"]}/f1/{k - 1}?review_for={k}'

# Grammar knowledge is introductory content; phase 2 starts directly with matching.
intro = client.get('/a/reference')
assert '学習前の知識：素性と文法形式' in intro.text
assert 'id="grammar"' in intro.text and '判断の考え方（3ステップ）' in intro.text
assert len(intro.context['expr_cards']) == len(main.EXPRESSIONS)
assert 'フェーズ2' not in intro.text
assert 'フェーズ1で学んだ判断' not in intro.text
summary = client.get(f'{base}/f1/done')
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

# Invalid selected links get comparison tables; unselected correct forms stay undisclosed.
invalid = next(e for e in main.EXPRESSIONS if e['key'] not in correct)
submitted = {invalid['key']: '○'}
r = client.post(f'{base}/f2/check', data=submitted)
assert [e['key'] for e in r.context['extra_results']] == [invalid['key']]
assert r.text.count('<table') == 1 and 'condition-mismatch' in r.text
assert '条件と合わない' in r.text and 'が合わない理由' in r.text
assert 'まだ結べていない形式があります' in r.text
assert '正解の線結び' not in r.text
assert '<th>' + invalid['label'] + 'の条件</th>' in r.text
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
assert '<th>' + invalid['label'] + 'の条件</th>' in wrong_match.text
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
assert judgment['has_missing'] and not judgment['all_correct']
assert set(judgment) == {'all_correct', 'invalid_keys', 'has_missing', 'feedback_html', 'context_url'}
assert '<th>' + invalid['label'] + 'の条件</th>' in judgment['feedback_html']
assert 'invalid-expression' not in judgment['feedback_html']
assert 'href="#step3Form"' in judgment['feedback_html']
missing_only = client.post(f'{base}/f2/check', data={}, headers=json_headers).json()
assert missing_only['invalid_keys'] == [] and missing_only['has_missing']
assert '<table' not in missing_only['feedback_html']
right = client.post(f'{base}/f2/check', data=correct, headers=json_headers).json()
assert right['all_correct'] and not right['has_missing'] and right['invalid_keys'] == []
assert right['context_url'] == f'{base}/f3'
assert client.post('/b/word/iraira/f2/check', data=correct, headers=json_headers).status_code == 404

print('OK: 3-attempt reveal, duplicate submissions, review chain, all 16 words, non-revealing matching, preserved answers, context return and participant/group isolation')
