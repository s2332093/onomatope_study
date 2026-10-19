"""Export per-participant/group/page aggregates; no public export endpoint."""
import argparse
import csv
import json
from collections import defaultdict
from study_logging import connect

parser = argparse.ArgumentParser()
parser.add_argument('output', help='summary CSV output path')
args = parser.parse_args()
pages = defaultdict(lambda: {'clicks': 0, 'active_ms': 0, 'elapsed_ms': 0, 'line_add': 0, 'line_remove': 0, 'submissions': 0})
with connect() as con:
    for participant, group, page, path, kind, elapsed, detail in con.execute(
        'SELECT participant_id,study_group,page_id,path,event_type,elapsed_ms,detail FROM events'):
        if not page:
            continue
        row = pages[(participant, group, page, path)]
        data = json.loads(detail)
        row['clicks'] = max(row['clicks'], int(data.get('click_count', 0)))
        row['active_ms'] = max(row['active_ms'], float(data.get('active_ms', 0)))
        row['elapsed_ms'] = max(row['elapsed_ms'], elapsed or 0)
        if kind in ('line_add', 'line_remove'):
            row[kind] += 1
        if kind == 'submit':
            row['submissions'] += 1
with open(args.output, 'w', newline='', encoding='utf-8-sig') as out:
    writer = csv.writer(out)
    writer.writerow(['participant_id', 'study_group', 'page_id', 'path', 'click_count',
                     'active_ms', 'elapsed_ms', 'line_add', 'line_remove', 'submissions'])
    for key, values in sorted(pages.items()):
        writer.writerow([*key, *values.values()])
print(f'Exported {len(pages)} page visits')
