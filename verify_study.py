"""Group isolation, meaning-only curriculum and durable event collection."""
import re
import json
import os
import tempfile
from pathlib import Path
os.environ['STUDY_LOG_PATH'] = str(Path(tempfile.mkdtemp()) / 'events.db')
from fastapi.testclient import TestClient
import main
import study_logging
client = TestClient(main.app)
assert client.get('/', follow_redirects=False).headers['location'] == '/experiment/'
for group in ('experiment', 'control'):
    home = client.get('/' + group + '/')
    assert home.status_code == 200
    assert 'data-study-prefix="/' + group + '"' in home.text
assert '/experiment/reference' in client.get('/experiment/').text
control = re.sub(r'<style>.*?</style>', '', client.get('/control/').text, flags=re.S)
assert '素性' not in control and '前接条件' not in control
for w in main.WORDS:
    r = client.get('/control/word/' + w['id'])
    assert r.status_code == 200
    assert r.text.count('name="choice"') == 4
    assert 'value="' + w['id'] + '"' in r.text
    visible = re.sub(r'<style>.*?</style>', '', r.text, flags=re.S)
    assert '素性' not in visible and '前接条件' not in visible
    result = client.post('/control/word/' + w['id'] + '/meaning/check', data={'choice': w['id']})
    assert '正解です' in result.text and w['meaning'] in result.text
for suffix in ('reference', 'drill/features', 'word/iraira/f1/1', 'word/iraira/f2', 'word/iraira/f3'):
    assert client.get('/control/' + suffix).status_code == 404
for group in ('experiment', 'control'):
    events = [{'event_id':'test:1','page_id':'visit','client_time':'2026-10-19T00:00:00Z',
               'event_type':'click','elapsed_ms':1200,'detail':{'path':'/' + group + '/', 'click_count':1}}]
    for _ in range(2):
        assert client.post('/' + group + '/api/events', json={'events':events}).status_code == 200
assert client.post('/experiment/api/events', json={'events':[{'event_type':'unknown'}]}).status_code == 400
with study_logging.connect() as db:
    assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='click'").fetchone()[0] == 2
    answers = [json.loads(r[0]) for r in db.execute("SELECT detail FROM events WHERE event_type='answer_submission' AND study_group='control'")]
    assert len(answers) == 16 and all(r['correct'] for r in answers)
# Answer submitted through middleware still reaches route; compare wrong and correct cases.
w=main.WORD_BY_ID['iraira']; cat=main.get_category(w)
correct={k:'○' for k in main.CAT_EXPRS[cat['id']]}
r=client.post('/experiment/word/iraira/f2/check', data=correct)
assert '10 / 10 正解' in r.text
assert 'あなたの線結び' in r.text and '正解の線結び' in r.text
assert r.text.count('<line ') == len(correct) * 2
assert r.text.count('この形式の前接条件') == 10
r=client.post('/experiment/word/iraira/f2/check', data={})
assert r.text.count('<line ') == len(correct)
assert '線が足りません' in r.text
# CSV exports are local commands, never HTTP resources.
import subprocess
subprocess.run([os.sys.executable, 'study_logging.py', str(study_logging.LOG_PATH.with_suffix('.csv'))], check=True)
subprocess.run([os.sys.executable, 'analyze_logs.py', str(study_logging.LOG_PATH.with_name('summary.csv'))], check=True)
assert study_logging.LOG_PATH.with_suffix('.csv').exists()
assert client.get('/control/study_logs.db').status_code == 404
print('OK: both groups, all 16 meaning lessons, blocked curriculum, answers, event deduplication, feedback maps, CSV exports')
