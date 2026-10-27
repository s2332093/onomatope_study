"""Group isolation, meaning/context lessons and event collection."""
import re
import random
import json
import os
import tempfile
from pathlib import Path
os.environ['STUDY_LOG_PATH'] = str(Path(tempfile.mkdtemp()) / 'events.db')
from fastapi.testclient import TestClient
os.environ['STUDY_REQUIRE_NAME'] = '0'
import main
import study_logging
client = TestClient(main.app)
assert client.get('/', follow_redirects=False).headers['location'] == '/a/'
for group in ('a', 'b'):
    home = client.get('/' + group + '/')
    assert home.status_code == 200
    assert 'data-study-prefix="/' + group + '"' in home.text
assert '/a/reference' in client.get('/a/').text
control = re.sub(r'<style>.*?</style>', '', client.get('/b/').text, flags=re.S)
assert '素性' not in control and '前接条件' not in control
for w in main.WORDS:
    r = client.get('/b/word/' + w['id'])
    assert r.status_code == 200
    assert r.text.count('name="choice"') == 4
    assert 'value="' + w['id'] + '"' in r.text
    visible = re.sub(r'<style>.*?</style>', '', r.text, flags=re.S)
    assert '素性' not in visible and '前接条件' not in visible
    result = client.post('/b/word/' + w['id'] + '/meaning/check', data={'choice': w['id']})
    assert '正解です' in result.text and w['meaning'] in result.text
    assert f'href="/b/word/{w["id"]}/f3"' in result.text
    # Both groups use the same frames and option generator, including shuffling.
    random.seed(20261020)
    a = client.get(f'/a/word/{w["id"]}/f3')
    random.seed(20261020)
    b = client.get(f'/b/word/{w["id"]}/f3')
    assert b.status_code == 200
    assert re.findall(r'name="opt_keys_\d+" value="([^"]+)"', a.text) == re.findall(r'name="opt_keys_\d+" value="([^"]+)"', b.text)
    assert len(main.PRACTICE[w['id']]) == 2
    for q in main.PRACTICE[w['id']]:
        assert q['frame'] in a.text and q['frame'] in b.text
        assert b.text.count(f'name="choice_{q["ord"]}"') == 3
    assert 'フェーズ2：文脈練習' in b.text
    correct = {f'choice_{q["ord"]}': q['correct_key'] for q in main.PRACTICE[w['id']]}
    right = client.post(f'/b/word/{w["id"]}/f3/check', data=correct)
    wrong = client.post(f'/b/word/{w["id"]}/f3/check', data={k: 'not-an-option' for k in correct})
    assert '2／2 正解' in right.text and '0／2 正解' in wrong.text
    assert '（未選択）' in wrong.text
    assert f'href="/b/word/{w["id"]}/complete"' in right.text
    complete = client.get(f'/b/word/{w["id"]}/complete')
    for page in (result, b, right, wrong, complete):
        assert page.status_code == 200
        visible = re.sub(r'<style>.*?</style>', '', page.text, flags=re.S)
        for forbidden in ('素性', '前接条件', 'カテゴリー', '継続性', '動作性', '意志性', '/a/', '/f1/', '/f2', 'フェーズ3'):
            assert forbidden not in visible, (w['id'], forbidden)
        assert 'study_log.js' in page.text
    assert client.get(f'/b/word/{w["id"]}/f3/check').status_code == 405
assert '実施者の案内' in complete.text
assert client.get('/b/word/missing/f3', follow_redirects=False).headers['location'] == '/b/'
for suffix in ('reference', 'drill/features', 'drill/expressions', 'word/iraira/f1/1', 'word/iraira/f1/done', 'word/iraira/f2', 'word/iraira/f2/learn'):
    assert client.get('/b/' + suffix).status_code == 404
assert client.post('/b/word/iraira/f2/check', data={}).status_code == 404
for group in ('a', 'b'):
    events = [{'event_id':'test:1','page_id':'visit','client_time':'2026-10-19T00:00:00Z',
               'event_type':'click','elapsed_ms':1200,'detail':{'path':'/' + group + '/', 'click_count':1}}]
    for _ in range(2):
        assert client.post('/' + group + '/api/events', json={'events':events}).status_code == 200
assert client.post('/a/api/events', json={'events':[{'event_type':'unknown'}]}).status_code == 400
with study_logging.connect() as db:
    assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='click'").fetchone()[0] == 2
    answers = [json.loads(r[0]) for r in db.execute("SELECT detail FROM events WHERE event_type='answer_submission' AND study_group='control'")]
    meaning_answers = [r for r in answers if 'correct' in r]
    context_answers = [r for r in answers if 'correct_by_question' in r]
    assert len(meaning_answers) == 16 and all(r['correct'] for r in meaning_answers)
    assert len(context_answers) == 32
    assert sum(all(r['correct_by_question'].values()) for r in context_answers) == 16
    assert all(len(r['correct_by_question']) == 2 for r in context_answers)
# Legacy links preserve method, nested paths and query while redirecting to neutral URLs.
for old, new in (('experiment', 'a'), ('control', 'b')):
    for suffix in ('', '/', '/word/iraira'):
        r = client.get('/' + old + suffix + '?source=link', follow_redirects=False)
        assert r.status_code == 307
        assert r.headers['location'] == '/' + new + (suffix or '/') + '?source=link'
    r = client.post('/' + old + '/word/iraira/f2/check', data={}, follow_redirects=False)
    assert r.status_code == 307 and r.headers['location'] == '/' + new + '/word/iraira/f2/check'
for group in ('a', 'b'):
    page = client.get('/' + group + '/').text
    assert '学習システム' + group.upper() in page
    assert '/experiment' not in page and '/control' not in page
    assert '実験群' not in page and '統制群' not in page
blocked = client.get('/b/reference')
assert '統制群' not in blocked.text and '/b/' in blocked.text
# Answer submitted through middleware still reaches route; compare wrong and correct cases.
w=main.WORD_BY_ID['iraira']; cat=main.get_category(w)
correct={k:'○' for k in main.CAT_EXPRS[cat['id']]}
r=client.post('/a/word/iraira/f2/check', data=correct)
assert '10 / 10 正解' in r.text
assert '線結びを確認できました' in r.text
assert '正解の線結び' not in r.text and '<line ' not in r.text
r=client.post('/a/word/iraira/f2/check', data={})
assert '<line ' not in r.text and '<table' not in r.text
assert 'まだ結べていない形式があります' in r.text
# CSV exports are local commands, never HTTP resources.
import subprocess
subprocess.run([os.sys.executable, 'study_logging.py', str(study_logging.LOG_PATH.with_suffix('.csv'))], check=True)
subprocess.run([os.sys.executable, 'analyze_logs.py', str(study_logging.LOG_PATH.with_name('summary.csv'))], check=True)
assert study_logging.LOG_PATH.with_suffix('.csv').exists()
assert client.get('/b/study_logs.db').status_code == 404
print('OK: both groups, 16 meaning/context lessons, shared questions, correct/wrong answers, blocked curriculum, logs, feedback maps, CSV exports')
