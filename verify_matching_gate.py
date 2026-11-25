"""Matching can be graded only after all ten current prerequisites were checked."""
import os
import tempfile
from pathlib import Path
os.environ.update(STUDY_REQUIRE_NAME='0', STUDY_LOG_PATH=str(Path(tempfile.mkdtemp()) / 'gate.db'))
from fastapi.testclient import TestClient
import main
import learning_state
from verify_support import condition_answers, ready_for_practice

c = ready_for_practice(TestClient(main.app))
page = c.get('/a/word/iraira/f2')
session = page.context['matching_session']
answers = {**condition_answers(), '_study_matching_session':session}
lines = {key:'○' for key in main.CAT_EXPRS['emo_cont']}

def blocked(data, remaining):
    response = c.post('/a/word/iraira/f2/check', data=data, headers={'Accept':'application/json'})
    assert response.status_code == 422
    assert response.json()['error'] == 'conditions_incomplete' and response.json()['remaining'] == remaining
    assert not {'all_correct','feedback_url','context_url'} & response.json().keys()
    assert 'x-study-receipt' not in response.headers
    assert not learning_state.read(c.cookies['study_participant'], 'experiment', 'iraira').get('matching_feedback')

# Even all-correct selections or a bulk fill do not substitute for individual judgments.
blocked({**answers, **lines, 'demo_autofill_used':'1'}, 10)
for expression in main.EXPRESSIONS[:-1]:
    result = c.post(f"/a/word/iraira/f2/conditions/{expression['key']}/check", data=answers)
    assert result.status_code == 200 and result.json()['all_correct']
blocked({**answers, **lines}, 1)
last = main.EXPRESSIONS[-1]['key']
wrong = {**answers, f'condition_{last}_volition_plus':'＋'}
assert not c.post(f'/a/word/iraira/f2/conditions/{last}/check',data=wrong).json()['all_correct']
blocked({**answers, **lines}, 1)
assert c.post(f'/a/word/iraira/f2/conditions/{last}/check',data=answers).json()['all_correct']

# Changing one prerequisite after its correct check invalidates the whole judgment.
changed = {**answers, 'condition_shiteiku_action_high':'高'}
blocked({**changed, **lines}, 1)
correct = c.post('/a/word/iraira/f2/check',data={**answers, **lines},headers={'Accept':'application/json'})
assert correct.status_code == 200 and correct.json()['all_correct']

# Ordinary matching feedback remains available once the prerequisite gate is satisfied.
failed = c.post('/a/word/iraira/f2/check',data={**answers, 'surutokoroda':'○'},headers={'Accept':'application/json'}).json()
feedback = c.get(failed['feedback_url'])
retry = c.get('/a' + feedback.context['retry_url'])
assert retry.context['matching_session'] == session
assert len(retry.context['checked_expressions']) == 10
assert 'data-conditions-passed="1"' in retry.text

# New exercise pages and other learners cannot reuse previous confirmations.
restarted = c.get('/a/word/iraira/f2')
assert restarted.context['matching_session'] != session
assert not restarted.context['checked_expressions']
blocked({**answers, **lines}, 10)
assert c.post(f'/a/word/iraira/f2/conditions/{last}/check',data=answers).status_code == 409
other = ready_for_practice(TestClient(main.app))
other_page = other.get('/a/word/iraira/f2')
assert other_page.context['matching_session'] != restarted.context['matching_session']
assert other.post('/a/word/iraira/f2/check',data={**answers,**lines},headers={'Accept':'application/json'}).status_code == 422
html = c.post('/a/word/iraira/f2/check',data=answers)
assert html.status_code == 422 and '前接条件の判定がまだ終わっていません' in html.text
assert 'フィードバックを見る' not in html.text and 'data-study-receipt=""' in html.text
assert c.post('/b/word/iraira/f2/check',data=answers).status_code == 404
print('OK: no unchecked/incorrect/stale matching judgments or feedback; checked retries and learner isolation preserved')
