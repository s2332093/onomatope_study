"""Choices stay fixed across groups, reloads, retries and participant sessions."""
import os
import re
import tempfile
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.update(STUDY_REQUIRE_NAME='0',
                  STUDY_LOG_PATH=str(Path(tempfile.mkdtemp()) / 'fixed-options.db'))
from fastapi.testclient import TestClient
import main
from verify_support import ready_for_practice


def radio_choices(response):
    return re.findall(r'<input[^>]*type="radio"[^>]*name="([^"]+)"[^>]*value="([^"]+)"', response.text)


meaning_positions = Counter()
context_positions = Counter()
with ExitStack() as stack:
    # Displaying the active curriculum must never draw or rearrange random choices.
    for method in ('sample', 'shuffle', 'choice'):
        stack.enter_context(patch.object(main.random, method,
                            side_effect=AssertionError('randomized learner choices')))
    for word in main.WORDS:
        base = '/a/word/' + word['id']
        learner = ready_for_practice(TestClient(main.app))
        other = ready_for_practice(TestClient(main.app))
        for stage in range(1, 6):
            first = learner.get(f'{base}/f1/{stage}')
            again = learner.get(f'{base}/f1/{stage}')
            fresh = other.get(f'{base}/f1/{stage}')
            assert first.status_code == again.status_code == fresh.status_code == 200
            assert radio_choices(first) == radio_choices(again) == radio_choices(fresh)
        meaning = learner.get(base + '/f1/1')
        control = learner.get('/b/word/' + word['id'])
        assert radio_choices(meaning) == radio_choices(control)
        meanings = meaning.context['q']['meaning_opts']
        assert len(meanings) == len({o['src'] for o in meanings}) == 4
        meaning_positions[[o['src'] for o in meanings].index(word['id'])] += 1
        wrong = next(o['src'] for o in meanings if o['src'] != word['id'])
        learner.post('/b/word/' + word['id'] + '/meaning/check', data={'choice': wrong})
        assert radio_choices(learner.get('/b/word/' + word['id'])) == radio_choices(control)

        match = learner.get(base + '/f2')
        expected = [e['key'] for e in main.EXPRESSIONS]
        actual = [e['key'] for g in match.context['expr_groups'] for e in g['exprs']]
        assert actual == expected
        assert learner.get(base + '/f2').context['expr_groups'] == match.context['expr_groups']
        assert other.get(base + '/f2').context['condition_options'] == match.context['condition_options']

        a = learner.get(base + '/f3')
        b = learner.get('/b/word/' + word['id'] + '/f3')
        questions = a.context['questions']
        for response in (b, learner.get(base + '/f3'), other.get(base + '/f3')):
            assert response.context['questions'] == questions
            assert radio_choices(response) == radio_choices(a)
        for question in questions:
            keys = [o['key'] for o in question['options']]
            assert len(keys) == len(set(keys)) == 3
            assert keys.count(question['correct_key']) == 1
            assert all(k == question['correct_key'] or
                       k not in main.CAT_EXPRS[word['category_id']] for k in keys)
            context_positions[keys.index(question['correct_key'])] += 1
        saved = {str(q['idx']): [o['key'] for o in reversed(q['options'])] for q in questions}
        assert main.step4_build(word, saved_options=saved) == questions
        answers = {f'choice_{q["idx"]}': q['correct_key'] for q in questions}
        bad = next(o['key'] for o in questions[0]['options']
                   if o['key'] != questions[0]['correct_key'])
        answers['choice_' + str(questions[0]['idx'])] = bad
        failed = learner.post(base + '/f3/check', data=answers, follow_redirects=False)
        if word['id'] == 'iraira':
            assert failed.status_code == 200 and not failed.context['all_correct']
            assert learner.get(base + '/f3').context['questions'] == questions
        else:
            review = learner.get(failed.headers['location'])
            token = review.context['review_token']
            back = learner.get(base + '/f3?review=' + token)
            assert back.context['questions'] == questions
            assert back.context['saved_choices'][str(questions[0]['idx'])] == bad
        learner.post('/b/word/' + word['id'] + '/f3/check', data=answers)
        assert learner.get('/b/word/' + word['id'] + '/f3').context['questions'] == questions

assert set(meaning_positions) == {0, 1, 2, 3}
assert max(meaning_positions.values()) - min(meaning_positions.values()) <= 1
assert context_positions == {0: 4, 1: 4, 2: 4}
print('OK: fixed choices for all six words, A/B parity, fresh sessions, retries, '
      'matching and prerequisites; correct positions distributed across all slots')
