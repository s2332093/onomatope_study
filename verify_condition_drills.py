"""Per-form prerequisite grading, non-revealing responses and buffered records."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.update(STUDY_REQUIRE_NAME='0',STUDY_LOG_PATH=str(Path(tempfile.mkdtemp())/'conditions.db'))
from fastapi.testclient import TestClient
import main
import study_logging
from verify_support import condition_answers

c = TestClient(main.app)
c.get('/a/')
answers = condition_answers()
receipts = []
with patch.object(study_logging, 'connect', side_effect=AssertionError('analytics access during a drill')):
    for expression in main.EXPRESSIONS:
        key = expression['key']
        path = f'/a/word/iraira/f2/conditions/{key}/check'
        response = c.post(path, data=answers, headers={'Accept':'application/json'})
        assert response.json() == {'all_correct':True,'correct_by_feature':{'continuity':True,'action':True,'volition':True}}
        receipt = response.headers['x-study-receipt']
        receipts.append(receipt)
        detail = main.deferred_logging.open_receipt(receipt,c.cookies['study_participant'],'experiment')['detail']
        assert set(detail['correct_by_condition']) == {key+'_'+feature for feature in main.FEATURE_NAME}
        assert 'correct_by_expression' not in detail and detail['grading_scope'] == 'conditions:'+key
        assert c.post(path.replace('/a/','/b/'),data=answers).status_code == 404
    wrong = {k:v for k,v in answers.items() if not k.startswith('condition_shihajimeru_action_')}
    wrong['condition_shihajimeru_action_low'] = '低'
    response = c.post('/a/word/iraira/f2/conditions/shihajimeru/check',data=wrong)
    assert response.json() == {'all_correct':False,'correct_by_feature':{'continuity':True,'action':False,'volition':True}}
    # The response names only correctness, not the missing permitted values.
    assert '高' not in response.text and '中' not in response.text and 'selected' not in response.text
    receipts.append(response.headers['x-study-receipt'])
    empty = c.post('/a/word/iraira/f2/conditions/shidasu/check',data={}).json()
    assert not empty['all_correct'] and not any(empty['correct_by_feature'].values())
    assert c.post('/a/word/iraira/f2/conditions/missing/check',data={}).status_code == 404
    assert c.post('/a/word/missing/f2/conditions/shidasu/check',data={}).status_code == 404
with study_logging.connect() as db:
    assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
assert c.post('/a/api/finish',json={'participant_id':c.cookies['study_participant'],'events':[],'receipts':receipts}).status_code == 200
report = main.research.report(c.cookies['study_participant'])
assert len(report['attempts']) == 11
assert [r['correct'] for r in report['attempts']] == [True]*10+[False]
assert report['people'][0]['items'] == 33
for group in ('a','b'):
    home = c.get('/'+group+'/').text
    assert 'home-word-list::before' not in home and 'outline:3px' not in home
print('OK: ten individual grammar drills, three-feature grading, wrong-only result, A/B isolation, private receipts and finish-only saving')
