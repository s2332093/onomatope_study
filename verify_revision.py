"""Completion identity, failed B navigation and prerequisite grading regressions."""
import os
import re
import tempfile
from pathlib import Path
os.environ.update(STUDY_REQUIRE_NAME='0', STUDY_LOG_PATH=str(Path(tempfile.mkdtemp())/'revision.db'))
from fastapi.testclient import TestClient
import main
from verify_support import condition_answers

c = TestClient(main.app)
for group in ('a', 'b'):
    path = f'/{group}/word/iraira'
    assert not c.get(f'/{group}/').context['completed_words']
    assert c.get(path+'/complete', follow_redirects=False).headers['location'] == path+'/f3'
    assert not c.get(f'/{group}/').context['completed_words']
    right = {f'choice_{q["ord"]}':q['correct_key'] for q in main.PRACTICE['iraira']}
    c.post(path+'/f3/check',data=right)
    assert not c.get(f'/{group}/').context['completed_words']
    c.get(path+'/complete')
    home = c.get(f'/{group}/')
    assert home.context['completed_words'] == {'iraira'}
    assert len(re.findall(r'class="card home-word-card is-completed"',home.text)) == 1
    assert '✓ 学習済み' in home.text
    assert TestClient(main.app).get(f'/{group}/').context['completed_words'] == set()
    if group == 'a':
        assert not c.get('/b/').context['completed_words']
    knowledge = c.get('/a/reference' if group == 'a' else '/b/knowledge').text
    assert 'ホーム画面に戻る' in knowledge

for suffix, data in [('meaning/check', {'choice':'bikkuri'}), ('f3/check', {})]:
    result = c.post('/b/word/iraira/'+suffix,data=data)
    assert result.context['hide_learning_navigation']
    assert 'もう一度選ぶ' in result.text
    assert 'ホーム（語を選ぶ）' not in result.text
    assert 'href="/b/word/iraira/complete"' not in result.text
    assert c.get('/b/word/iraira/complete',follow_redirects=False).status_code == 303 if suffix == 'f3/check' else True

answer = condition_answers()
assert len(main.grade_conditions(answer)[1]) == 30
assert all(r['ok'] for r in main.grade_conditions(answer)[1])
# Partial multi-selection is insufficient; unrestricted cannot coexist with a value.
wrong = dict(answer)
del wrong['condition_shihajimeru_action_high']
wrong['condition_shiteshimau_action_high'] = '高'
errors = [r['id'] for r in main.grade_conditions(wrong)[1] if not r['ok']]
assert errors == ['shihajimeru_action','shiteshimau_action']
lines = {key:'○' for key in main.CAT_EXPRS['emo_cont']}
result = c.post('/a/word/iraira/f2/check',data={**lines,**wrong},headers={'Accept':'application/json'}).json()
assert not result['all_correct'] and result['has_condition_errors'] and not result['has_missing']
feedback = c.get(result['feedback_url'])
assert len(feedback.context['condition_errors']) == 2
retry = c.get('/a'+feedback.context['retry_url'])
assert retry.context['saved_conditions']['shihajimeru_action'] == ['中']
assert retry.context['saved_conditions']['shiteshimau_action'] == ['高','制限なし']
assert set(retry.context['saved_connections']) == set(lines)
assert 'id="step3Form"' not in feedback.text
assert '正解の線結び' not in feedback.text
assert 'correct_by_condition' in main.deferred_logging.open_receipt(
    c.post('/a/word/iraira/f2/check',data={**lines,**answer},headers={'Accept':'application/json'}).headers['x-study-receipt'],
    c.cookies['study_participant'],'experiment')['detail']
assert c.get(result['feedback_url'],follow_redirects=False).status_code == 303
assert c.get('/a/word/iraira/f2').context['saved_conditions'] == {}
print('OK: completion/identity isolation, failed B retry, 30 prerequisites, partial/mixed values, feedback privacy, receipts and retry restoration')
