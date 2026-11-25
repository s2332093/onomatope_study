"""Optional home knowledge pages and per-word phases, with iraira-only progression."""
import os
import tempfile
from pathlib import Path

os.environ.update(STUDY_REQUIRE_NAME='0', STUDY_LOG_PATH=str(Path(tempfile.mkdtemp()) / 'stages.db'))
from fastapi.testclient import TestClient
import main
import learning_state
from verify_support import condition_answers

c = TestClient(main.app)
home = c.get('/a/')
pid = c.cookies['study_participant']
assert not home.context['course']['features_known']
assert '学習の流れ' not in home.text and '学習前の知識を見る' not in home.text
assert 'href="/a/reference">オノマトペの知識</a>' in home.text
assert 'href="/a/reference/grammar">文法形式の知識</a>' in home.text
assert c.get('/a/word/iraira/f1/1', follow_redirects=False).status_code == 200
assert c.get('/a/reference/grammar', follow_redirects=False).status_code == 200
# Each button opens its own content, including a grammar-first visit.
grammar_first = TestClient(main.app)
grammar_first.get('/a/')
other_pid = grammar_first.cookies['study_participant']
assert grammar_first.get('/a/reference/grammar').status_code == 200
assert grammar_first.post('/a/reference/grammar/complete', data={'_study_participant': 'other'}).status_code == 409
assert grammar_first.post('/a/reference/grammar/complete', data={'_study_participant': other_pid}, follow_redirects=False).headers['location'] == '/a/'
assert grammar_first.get('/a/word/iraira', follow_redirects=False).status_code == 200
assert 'ホーム画面に戻る' in grammar_first.get('/a/reference').text
assert grammar_first.post('/a/reference/complete', data={'_study_participant': other_pid}, follow_redirects=False).headers['location'] == '/a/'
assert grammar_first.get('/a/word/iraira').status_code == 200
intro = c.get('/a/reference')
assert '素性（10分）' in intro.text
assert '文法形式の前接条件（全' not in intro.text
assert '文法形式の条件と照合する' not in intro.text
assert '前接条件の知識学習へ →' in intro.text and '全6語のフェーズ1' not in intro.text
assert c.post('/a/reference/complete', data={'_study_participant': 'other'}).status_code == 409
assert c.post('/a/reference/complete', data={'_study_participant': pid}, follow_redirects=False).headers['location'] == '/a/reference/grammar'
assert c.get('/a/').context['course']['phase1_words'] == set()
for path in ('', '/f1/1'):
    lesson = c.get('/a/word/iraira' + path, follow_redirects=False)
    assert lesson.status_code == 200
    assert 'href="/a/reference' not in lesson.text
for path in ('/f2', '/f3'):
    assert c.get('/a/word/iraira' + path, follow_redirects=False).headers['location'] == '/a/word/iraira/f1/1'
grammar = c.get('/a/reference/grammar')
assert '前接条件（5分）' in grammar.text and '文法形式の前接条件（全10形式）' in grammar.text
assert '全6語の素性の学習が終わりました' not in grammar.text
assert c.post('/a/reference/grammar/complete', data={'_study_participant': 'other'}).status_code == 409
assert c.post('/a/reference/grammar/complete', data={'_study_participant': pid}, follow_redirects=False).headers['location'] == '/a/'
assert c.get('/a/').context['course']['grammar_known']
assert 'フェーズ1を始める →' in c.get('/a/word/iraira').text
assert c.get('/a/word/iraira/f1/done', follow_redirects=False).status_code == 303
assert c.get('/a/word/iraira/f2', follow_redirects=False).headers['location'] == '/a/word/iraira/f1/1'

for index, word in enumerate(main.WORDS):
    wid = word['id']
    cat = main.get_category(word)
    for k in range(1, 6):
        correct = {1: wid, 2: word['phon']}.get(k) or cat[{3: 'continuity', 4: 'action', 5: 'volition'}[k]]
        if wid == 'iraira':
            choice = {1: 'bikkuri', 2: 'q', 3: 'ー', 4: '高', 5: '＋'}[k]
        else:
            choice = correct
        if k == 4:
            kind = c.post(f'/a/word/{wid}/f1/4/kind/check', data={'choice': '動作' if wid == 'iraira' else cat['kind']})
            assert ('次へ：動作性' in kind.text)
        response = c.post(f'/a/word/{wid}/f1/{k}/check', data={'choice': choice})
        if wid == 'iraira':
            assert not response.context['fb']['ok'] and response.context['demo_can_continue']
            receipt = main.deferred_logging.open_receipt(response.headers['x-study-receipt'], pid, 'experiment')
            assert receipt['detail']['correct'] is False and receipt['detail']['demo_word'] is True
    summary = c.get(f'/a/word/{wid}/f1/done')
    assert summary.status_code == 200
    assert len(summary.context['course']['phase1_words']) == index + 1
    assert 'フェーズ2へ進む' in summary.text and '6語のフェーズ1を学習しましょう' not in summary.text
    # This word can continue before the other five phase-1 lessons have finished.
    assert c.get(f'/a/word/{wid}/f2').status_code == 200
    assert c.post(f'/a/word/{wid}/f2/check', data={}, headers={'Accept': 'application/json'}).status_code == 200
    if index < len(main.WORDS) - 1:
        other = main.WORDS[index + 1]['id']
        assert c.get(f'/a/word/{other}/f2', follow_redirects=False).headers['location'] == f'/a/word/{other}/f1/1'

home = c.get('/a/')
assert len(home.context['course']['phase1_words']) == 6
assert '全6語のフェーズ1' not in home.text and '✓ フェーズ1終了' not in home.text
for wid in main.WORD_BY_ID:
    matching = c.get(f'/a/word/{wid}/f2')
    assert matching.status_code == 200
    assert 'href="/a/reference' not in matching.text

# Incorrect matching remains incorrect, with a next step only for the demonstration word.
for wid in main.WORD_BY_ID:
    verdict = c.post(f'/a/word/{wid}/f2/check', data={}, headers={'Accept': 'application/json'}).json()
    assert not verdict['all_correct']
    assert bool(verdict['context_url']) == (wid == 'iraira')
    feedback = c.get(verdict['feedback_url'])
    assert 'href="/a/reference' not in feedback.text
    assert (f'href="/a/word/{wid}/f3"' in feedback.text) == (wid == 'iraira')

for group in ('a', 'b'):
    for wid in ('iraira', 'zukizuki'):
        answers = {f'choice_{q["ord"]}': next(e['key'] for e in main.EXPRESSIONS if e['key'] != q['correct_key']) for q in main.PRACTICE[wid]}
        response = c.post(f'/{group}/word/{wid}/f3/check', data=answers, follow_redirects=False)
        state = learning_state.read(pid, main.STUDY_GROUPS['/' + group], wid)
        assert not state['context_passed']
        if wid == 'iraira':
            assert response.status_code == 200 and f'href="/{group}/word/{wid}/complete"' in response.text
            completed = c.get(f'/{group}/word/{wid}/complete')
            assert completed.status_code == 200
            assert learning_state.read(pid, main.STUDY_GROUPS['/' + group], wid)['completed_via_demo']
        else:
            assert f'href="/{group}/word/{wid}/complete"' not in response.text
            assert c.get(f'/{group}/word/{wid}/complete', follow_redirects=False).status_code == 303
    meaning = c.post(f'/b/word/iraira/meaning/check', data={'choice': 'bikkuri'})
    assert not meaning.context['feedback']['ok'] and '/b/word/iraira/f3' in meaning.text

for path in ('/b/reference', '/b/reference/grammar'):
    assert c.get(path).status_code == 404
assert c.post('/b/reference/grammar/complete', data={'_study_participant': pid}).status_code == 404
assert TestClient(main.app).get('/a/').context['course']['phase1_words'] == set()
# A new participant can study every word without confirming either knowledge page.
fresh = TestClient(main.app)
for word in main.WORDS:
    for suffix in ('', '/f1/1'):
        response = fresh.get('/a/word/' + word['id'] + suffix, follow_redirects=False)
        assert response.status_code == 200
        assert 'href="/a/reference' not in response.text
assert not fresh.get('/a/').context['course']['features_known']
assert not fresh.get('/a/').context['course']['grammar_known']
assert 'href="/b/knowledge"' not in fresh.get('/b/word/iraira').text
print('OK: optional home knowledge; no knowledge links or redirects during word lessons; per-word progression and honest grading preserved')

# The demonstration bypass must retain the error → matching → same context review route.
c.get('/a/word/iraira/f3')
wrong = {f'choice_{q["ord"]}': next(e['key'] for e in main.EXPRESSIONS if e['key'] != q['correct_key']) for q in main.PRACTICE['iraira']}
response = c.post('/a/word/iraira/f3/check', data=wrong, follow_redirects=False)
assert response.status_code == 200 and not response.context['all_correct']
assert '線結びに戻って見直す' in response.text
review_url = '/a' + response.context['matching_review_url']
assert 'href="' + review_url + '"' in response.text
assert 'href="/a/word/iraira/complete"' in response.text
matching = c.get(review_url)
assert len(matching.context['context_review']) == 2
assert matching.context['review_token']
assert '線結びを確認して文脈問題へ' in matching.text
submitted = {**condition_answers(), **{e['key']: '○' if e['key'] in {'shihajimeru','shidasu','shitekuru','shiteirutokoroda','shiteshimau'} else '×' for e in main.EXPRESSIONS}, 'review_token': matching.context['review_token']}
checked = c.post('/a/word/iraira/f2/check',data=submitted,headers={'Accept':'application/json'}).json()
assert checked['all_correct'] and '?review=' in checked['context_url']
returned = c.get(checked['context_url'])
assert returned.context['returning']
assert returned.context['saved_choices'] == {k.removeprefix('choice_'):v for k,v in wrong.items()}
correct = {f'choice_{q["ord"]}': q['correct_key'] for q in main.PRACTICE['iraira']}
passed = c.post('/a/word/iraira/f3/check',data=correct)
assert passed.context['all_correct'] and not passed.context['matching_review_url']
assert '線結びに戻って見直す' not in passed.text
print('OK: incorrect iraira context retains matching review, restored context answers and optional next')
