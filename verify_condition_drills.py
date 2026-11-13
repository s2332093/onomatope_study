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

# The requested prerequisite matrix is shared by the knowledge table and grading.
from verify_support import CONDITIONS
display_values = {'none':'制限なし','plus':'＋','result':'変化結果＋',
                  'minus':'ー','mid':'中','high':'高','low':'低'}
knowledge = c.get('/a/reference')
assert '関与しない' not in knowledge.text and 'vol_na.svg' not in knowledge.text
assert set(dict(main.CONDITION_OPTIONS['volition'])) == {'plus','none'}
assert [o['value'] for o in main.feature_options('volition')] == ['＋','ー']
assert len(main.KNOWLEDGE['volition']) == 2
for card in knowledge.context['expr_cards']:
    expected = CONDITIONS[card['expr']['key']]
    assert list(card['conditions'].values()) == [
        '・'.join(display_values[v] for v in codes.split()) for codes in expected]
    row = '<th scope="row">〜'+card['expr']['label']
    assert row in knowledge.text
    for value in card['conditions'].values():
        assert '<td>'+value+'</td>' in knowledge.text
for word in main.WORDS:
    for suffix in ('f1/5','f1/done','f2'):
        page = c.get(f'/a/word/{word["id"]}/{suffix}').text
        assert '関与しない' not in page and 'vol_na.svg' not in page

# A former answer is now wrong, and an intentional word can match shidasu.
old = {k:v for k,v in answers.items() if k != 'condition_shidasu_volition_none'}
old.update(condition_shidasu_volition_minus='ー',condition_shidasu_volition_unrelated='関与しない')
response = c.post('/a/word/burabura/f2/conditions/shidasu/check',data=old).json()
assert response == {'all_correct':False,'correct_by_feature':{'continuity':True,'action':True,'volition':False}}
right_lines = {key:'○' for key in ('surutokoroda','shiyoutosuru','shihajimeru','shidasu',
                                 'shitsuzukeru','shiteirutokoroda','shiteshimau')}
assert set(main.CAT_EXPRS['act_high_vol']) == set(right_lines)
result = c.post('/a/word/burabura/f2/check',data={**answers,**right_lines},headers={'Accept':'application/json'}).json()
assert result['all_correct'] and not result['has_missing']
del right_lines['shidasu']
result = c.post('/a/word/burabura/f2/check',data={**answers,**right_lines},headers={'Accept':'application/json'}).json()
assert not result['all_correct'] and result['has_missing'] and not result['has_condition_errors']
lesson = next(x for x in c.get('/b/knowledge').context['lessons'] if x['word']['id'] == 'burabura')
assert 'shidasu' in {e['key'] for e in lesson['expressions']}

# Shiteiku accepts unrestricted volition, rather than requiring non-volitional words.
old_shiteiku = {k:v for k,v in answers.items() if k != 'condition_shiteiku_volition_none'}
old_shiteiku['condition_shiteiku_volition_minus'] = 'ー'
response = c.post('/a/word/ukauka/f2/conditions/shiteiku/check', data=old_shiteiku).json()
assert response == {'all_correct':False,'correct_by_feature':{'continuity':True,'action':True,'volition':False}}
assert main.EXPR_BY_KEY['shiteiku']['req_vol'] == ''
assert '意志的な行為（＋意志性）とは結びつきません' not in knowledge.text
assert 'shiteiku' in main.CAT_EXPRS['act_low_vol']
assert set(main.CAT_EXPRS['act_low_vol']) == set(main.CAT_EXPRS['act_low_novol'])
print('OK: ten individual grammar drills, three-feature grading, wrong-only result, A/B isolation, private receipts and finish-only saving')
