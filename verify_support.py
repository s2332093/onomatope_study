"""Independent answer fixtures for the ten grammar prerequisites."""

CONDITIONS = {
    'surutokoroda': ('none', 'high', 'plus'),
    'shiyoutosuru': ('none', 'high', 'plus'),
    'shihajimeru': ('plus', 'mid high', 'none'),
    'shidasu': ('plus', 'mid high', 'none'),
    'shitekuru': ('plus', 'mid', 'none'),
    'shiteiku': ('plus', 'low', 'none'),
    'shitsuzukeru': ('plus', 'high', 'none'),
    'shiteirutokoroda': ('plus result', 'none', 'none'),
    'shitatokoroda': ('result', 'mid', 'none'),
    'shiteshimau': ('none', 'none', 'none'),
}


def condition_answers():
    values = {'none': '制限なし', 'plus': '＋', 'result': '変化結果の＋', 'minus': 'ー',
              'high': '高', 'mid': '中', 'low': '低'}
    return {f'condition_{expression}_{feature}_{code}': values[code]
            for expression, requirements in CONDITIONS.items()
            for feature, codes in zip(('continuity', 'action', 'volition'), requirements)
            for code in codes.split()}


def ready_for_practice(client):
    """Start an isolated phase-2 fixture after the course's new prerequisites.

    Course-order enforcement is exercised separately by verify_staged_learning.py.
    """
    from types import SimpleNamespace
    import main
    import learning_state
    client.get('/a/')
    pid = main.research.identity(SimpleNamespace(cookies=client.cookies)) if main.research.REQUIRE_NAME else client.cookies['study_participant']
    if not pid:
        raise AssertionError('Register the test participant before preparing course state')
    learning_state.update(pid, 'experiment', '__course__', lambda s: s.update(features_known=True, grammar_known=True))
    for word in main.WORDS:
        learning_state.update(pid, 'experiment', word['id'], lambda s: s.update(feature_confirmed={k: True for k in learning_state.PHASE1_STEPS}))
    return client


def checked_matching_answers(client, word_id, page=None):
    """Use the actual individual checks before testing whole matching judgments."""
    from types import SimpleNamespace
    import main
    page = page if page is not None else client.get(f'/a/word/{word_id}/f2')
    assert page.status_code == 200
    pid = main.research.identity(SimpleNamespace(cookies=client.cookies)) if main.research.REQUIRE_NAME else client.cookies['study_participant']
    data = {**condition_answers(), '_study_matching_session': page.context['matching_session'], '_study_participant': pid}
    for expression in main.EXPRESSIONS:
        response = client.post(f"/a/word/{word_id}/f2/conditions/{expression['key']}/check", data=data)
        assert response.status_code == 200 and response.json()['all_correct']
    return data
