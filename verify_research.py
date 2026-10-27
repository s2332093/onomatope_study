"""Research integration: names, private access, exact counts, timing, retry dedup and CSV."""
import os
import tempfile
from pathlib import Path
os.environ['STUDY_REQUIRE_NAME']='1'
os.environ['STUDY_ADMIN_PASSWORD']='test-only-secret-password'
os.environ['STUDY_SESSION_SECRET']='test-only-signed-session-secret'
os.environ['STUDY_LOG_PATH']=str(Path(tempfile.mkdtemp())/'research.db')
from fastapi.testclient import TestClient
import main
import research
import study_logging
client=TestClient(main.app)
auth=('researcher','test-only-secret-password')
assert client.get('/a/',follow_redirects=False).headers['location'].startswith('/a/registration?')
assert client.post('/a/api/events',json={'events':[]}).status_code==401
assert client.get('/a/research').status_code==401
assert client.get('/a/research/export/people').status_code==401
assert client.get('/a/research',auth=('researcher','wrong')).status_code==401
assert client.get('/b/research',auth=auth).status_code==404
assert client.post('/a/registration',data={'name':' '}).status_code==400
assert client.post('/a/registration',data={'name':'A'},headers={'Origin':'https://other.example'}).status_code==403
r=client.post('/a/registration',data={'name':'検証用 A','next':'https://outside.example'},follow_redirects=False)
assert r.status_code==303 and r.headers['location']=='/a/'
assert 'HttpOnly' in r.headers['set-cookie']
pid=research.identity(type('R',(),{'cookies':client.cookies})())
assert pid and study_logging.participant_name(pid)=='検証用 A'
assert '検証用 A' in client.get('/a/').text
assert '氏名は入力しません' not in client.get('/a/').text
# One visible visit: cumulative heartbeats 1s, 2s, page_leave 2.5s = 2.5s, not 5.5s.
events=[dict(event_id=f'visit:{i}',page_id='visit',client_time='2026-10-27T00:00:00Z',elapsed_ms=elapsed,
    event_type=kind,detail={'path':'/a/word/iraira/f1/1','active_ms':active,'click_count':2})
    for i,(kind,elapsed,active) in enumerate([('page_view',0,0),('heartbeat',1500,1000),('heartbeat',6000,2000),('page_leave',7000,2500)])]
for _ in range(2):
    assert client.post('/a/api/events',json={'events':events}).status_code==200
# Score must be authoritative on server; duplicate POST refresh counts once.
meta=dict(_study_path='/a/word/iraira/f1/1',_study_page_id='visit',_study_elapsed_ms='6500',_study_active_ms='2300')
wrong=dict(meta,choice='wrong',attempt_id='wrong-1')
for _ in range(2):
    assert client.post('/a/word/iraira/f1/1/check',data=wrong).status_code==200
assert client.post('/a/word/iraira/f1/1/check',data=dict(meta,choice='iraira',attempt_id='right-1')).status_code==200
stats=research.report(pid)
p=stats['people'][0]
assert p['seconds']==2.5,p
assert (p['visits'],p['attempts'],p['correct'],p['incorrect'],p['rate'],p['item_wrong'])==(1,2,1,1,50.0,1),p
assert len(stats['pages'])==2  # registration and source page
assert all(not row['path'].endswith('/check') for row in stats['pages'])
# Matching inline JSON and context redirect both generate scored attempts linked to source.
cat=main.get_category(main.WORD_BY_ID['iraira'])
connections={key:'○' for key in main.CAT_EXPRS[cat['id']]}
r=client.post('/a/word/iraira/f2/check',data=dict(connections,attempt_id='matching-right',_study_path='/a/word/iraira/f2'),headers={'Accept':'application/json'})
assert r.json()['all_correct']
choices={f'choice_{q["ord"]}':q['correct_key'] for q in main.PRACTICE['iraira']}
choices['choice_1']='wrong'
r=client.post('/a/word/iraira/f3/check',data=dict(choices,attempt_id='context-wrong'),follow_redirects=False)
assert r.status_code==303
stats=research.report(pid)
p=stats['people'][0]
assert (p['attempts'],p['correct'],p['incorrect'],p['items'],p['item_wrong'])==(4,2,2,14,2),p
html=client.get('/a/research?participant='+pid,auth=auth)
assert html.status_code==200 and '検証用 A' in html.text and 'ページごとの時間' in html.text
assert html.headers['cache-control']=='no-store'
assert 'data-study-prefix=""' in html.text  # researcher browsing is not learner time
for kind in ['people','pages','attempts','events']:
    r=client.get('/a/research/export/'+kind,auth=auth)
    assert r.status_code==200 and r.content.startswith(b'\xef\xbb\xbf')
    assert r.headers['cache-control']=='no-store'
# Same name does not merge different participants; changing user rotates identity.
client.post('/b/registration',data={'name':'検証用 A'})
pid2=research.identity(type('R',(),{'cookies':client.cookies})())
assert pid!=pid2 and 'data-study-prefix="/b"' in client.get('/b/').text
assert len(research.report()['people'])==2
assert len(research.report(pid)['people'])==1
assert len(research.report(group='control')['people'])==1
# Tampered cookies and raw legacy UUIDs cannot access a named session.
client.cookies.clear()
client.cookies.set(research.COOKIE,pid+'.forged')
assert client.get('/a/',follow_redirects=False).status_code==303
# User names remain escaped in dashboard and formula-safe in exports.
client.post('/a/registration',data={'name':'=1+1<script>'})
r=client.get('/a/research',auth=auth)
assert '&lt;script&gt;' in r.text and '=1+1<script>' not in r.text
r=client.get('/a/research/export/people',auth=auth)
assert "'=1+1<script>" in r.text
admin=TestClient(main.app)
assert admin.post('/a/research/login',data={'password':'wrong'}).status_code==401
assert admin.post('/a/research/login',data={'password':'test-only-secret-password'}).status_code==200
assert admin.get('/a/research').status_code==200
assert admin.get('/a/research/export/people').status_code==200
assert admin.post('/a/research/logout').status_code==200
assert admin.get('/a/research').status_code==401
# New storage connection/process sees committed data (no in-memory-only recording).
with study_logging.connect() as db:
    assert db.execute('SELECT COUNT(*) FROM participants').fetchone()[0]==3
    assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='answer_submission'").fetchone()[0]==4
print('OK: name gate, signed sessions, private reports, A/B isolation, visible time, duplicate suppression, JSON/redirect grading, CSV safety and stored records')
