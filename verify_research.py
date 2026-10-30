"""No analytics database access during lessons; authentic receipts and transactional finish."""
import os,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.update(STUDY_REQUIRE_NAME='1',STUDY_ADMIN_PASSWORD='test-only-secret-password',STUDY_SESSION_SECRET='test-only-session-secret',STUDY_LOG_PATH=str(Path(tempfile.mkdtemp())/'research.db'))
from fastapi.testclient import TestClient
import main,research,study_logging
client=TestClient(main.app);auth=('researcher','test-only-secret-password')
assert client.get('/a/',follow_redirects=False).status_code==303
assert client.post('/a/api/finish',json={}).status_code==401
assert client.get('/a/research').status_code==401
assert client.get('/b/research',auth=auth).status_code==404
assert client.post('/a/registration',data={'name':' '}).status_code==400
assert client.post('/a/registration',data={'name':'A'},headers={'Origin':'https://other.example'}).status_code==403
client.post('/a/registration',data={'name':'検証用 A','next':'https://outside.example'})
pid=research.identity(type('R',(),{'cookies':client.cookies})())
assert '検証用 A' in client.get('/a/').text
receipts=[]
def capture(r):
    token=r.headers.get('x-study-receipt');assert token;receipts.append(token);return r
meta=dict(_study_participant=pid,_study_path='/a/word/iraira/f1/1',_study_page_id='visit',_study_elapsed_ms='6500',_study_active_ms='2300')
wrong=dict(meta,choice='wrong',attempt_id='wrong-1')
with patch.object(study_logging,'connect',side_effect=AssertionError('analytics database accessed during lesson')):
    assert client.get('/a/word/iraira/f1/1').status_code==200
    for _ in range(2):
        r=capture(client.post('/a/word/iraira/f1/1/check',data=wrong));assert r.status_code==200
        assert f'data-study-receipt="{receipts[-1]}"' in r.text
    capture(client.post('/a/word/iraira/f1/1/check',data=dict(meta,choice='iraira',attempt_id='right-1')))
    cat=main.get_category(main.WORD_BY_ID['iraira'])
    connections={key:'○' for key in main.CAT_EXPRS[cat['id']]}
    r=capture(client.post('/a/word/iraira/f2/check',data=dict(connections,_study_participant=pid,attempt_id='matching-right',_study_path='/a/word/iraira/f2'),headers={'Accept':'application/json'}));assert '○ 正解です！' in r.json()['feedback_html']
    choices={f'choice_{q["ord"]}':q['correct_key'] for q in main.PRACTICE['iraira']};choices['choice_1']='wrong'
    r=capture(client.post('/a/word/iraira/f3/check',data=dict(choices,_study_participant=pid,attempt_id='context-wrong'),follow_redirects=False));assert r.status_code==303
    assert f'data-study-receipt="{receipts[-1]}"' in client.get(r.headers['location']).text
    assert client.get('/a/finish').status_code==200
with study_logging.connect() as db:assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0
assert research.report(pid)['people']==[]
events=[dict(event_id=f'visit:{i}',page_id='visit',elapsed_ms=e,event_type=k,detail={'path':'/a/word/iraira/f1/1','active_ms':a}) for i,(k,e,a) in enumerate([('page_view',0,0),('page_snapshot',6000,2000),('page_leave',7000,2500)])]
payload=dict(participant_id=pid,events=events,receipts=receipts)
assert client.post('/a/api/events',json=payload).status_code==409
assert client.post('/a/api/finish',json=dict(payload,participant_id='other')).status_code==409
assert client.post('/a/api/finish',json=dict(payload,receipts=[receipts[0][:-8]+'badtoken'])).status_code==400
assert client.post('/a/api/finish',json=dict(payload,events=[dict(events[0],event_type='answer_submission')])).status_code==400
with study_logging.connect() as db:assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0
with patch.object(study_logging,'save_batch',side_effect=RuntimeError('offline')):assert client.post('/a/api/finish',json=payload).status_code==503
for _ in range(2):assert client.post('/a/api/finish',json=payload).status_code==200
p=research.report(pid)['people'][0]
assert (p['attempts'],p['correct'],p['incorrect'],p['rate'],p['items'],p['item_wrong'],p['seconds'])==(4,2,2,50.0,14,2,2.5),p
for kind in ['people','pages','attempts','events']:
    r=client.get('/a/research/export/'+kind,auth=auth);assert r.status_code==200 and r.content.startswith(b'\xef\xbb\xbf') and r.headers['cache-control']=='no-store'
client.post('/b/registration',data={'name':'=1+1<script>'})
pid2=research.identity(type('R',(),{'cookies':client.cookies})())
assert pid!=pid2 and client.get('/b/finish').status_code==200
assert client.post('/b/api/finish',json=dict(payload,participant_id=pid2)).status_code==400
assert client.post('/a/api/finish',json=payload).status_code==409
assert client.post('/a/word/iraira/f1/1/check',data=wrong).status_code==409
client.post('/b/api/finish',json={'participant_id':pid2,'events':[dict(events[0],detail={'path':'/b/'})]})
assert "'=1+1<script>" in client.get('/a/research/export/people',auth=auth).text
assert '&lt;script&gt;' in client.get('/a/research',auth=auth).text
admin=TestClient(main.app)
assert admin.post('/a/research/login',data={'password':'wrong'}).status_code==401
assert admin.post('/a/research/login',data={'password':'test-only-secret-password'}).status_code==200
assert admin.get('/a/research').status_code==200
assert admin.post('/a/research/logout').status_code==200
assert admin.get('/a/research').status_code==401
with study_logging.connect() as db:assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='answer_submission'").fetchone()[0]==4
kind_client = TestClient(main.app)
kind_client.post('/a/registration', data={'name': '種類の回答確認_除外'})
kind_pid = research.identity(type('R', (), {'cookies': kind_client.cookies})())
kind_receipts = []
with patch.object(study_logging, 'connect', side_effect=AssertionError('analytics write before finish')):
    for choice in ('動作', '感情・感覚'):
        r = kind_client.post('/a/word/iraira/f1/2/kind/check', data={'choice': choice, 'attempt_id': choice, '_study_participant': kind_pid})
        kind_receipts.append(r.headers['x-study-receipt'])
assert kind_client.post('/a/api/finish', json={'participant_id': kind_pid, 'receipts': kind_receipts}).status_code == 200
kind_report = research.report(kind_pid)
assert [r['correct'] for r in kind_report['attempts']] == [False, True]
assert all(r['page_label'] == 'いらいら：オノマトペの種類' for r in kind_report['attempts'])
assert [r['answer_label'] for r in kind_report['attempts']] == ['解答：動作', '解答：感情・感覚']
print('OK: zero analytics DB access during lessons, encrypted receipts, JSON/redirect delivery, finish-only persistence, safe retry, A/B isolation and private reports')
