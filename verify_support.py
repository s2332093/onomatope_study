"""Independent answer fixtures for the ten grammar prerequisites."""

CONDITIONS = {
    'surutokoroda': ('none', 'high', 'plus'),
    'shiyoutosuru': ('none', 'high', 'plus'),
    'shihajimeru': ('plus', 'mid high', 'none'),
    'shidasu': ('plus', 'mid high', 'minus unrelated'),
    'shitekuru': ('plus', 'mid', 'none'),
    'shiteiku': ('plus', 'low', 'minus'),
    'shitsuzukeru': ('plus', 'high', 'none'),
    'shiteirutokoroda': ('plus result', 'none', 'none'),
    'shitatokoroda': ('result', 'mid', 'none'),
    'shiteshimau': ('none', 'none', 'none'),
}


def condition_answers():
    values = {'none': '制限なし', 'plus': '＋', 'result': '変化結果の＋', 'minus': 'ー',
              'high': '高', 'mid': '中', 'low': '低', 'unrelated': '関与しない'}
    return {f'condition_{expression}_{feature}_{code}': values[code]
            for expression, requirements in CONDITIONS.items()
            for feature, codes in zip(('continuity', 'action', 'volition'), requirements)
            for code in codes.split()}
