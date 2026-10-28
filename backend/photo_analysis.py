"""Read-only photo diagnostics from the latest matching, successful OCR job."""
import copy
import json

from .domain import moderate, now
from .recommendations import recommendations

PHOTO_RULES = {'unreadable_photos', 'poor_photo', 'low_resolution'}


def card_recommendations(card, owner, storage):
    response = recommendations(card)
    response['photo_analysis'] = None
    photo_ids = [p['photo_id'] for p in card['photos']]
    if not photo_ids:
        return response
    # Restrict every object to the same owner and TTL, including intermediate jobs.
    with storage.LOCK, storage.db() as conn:
        rows = conn.execute('SELECT id, kind, body FROM objects WHERE session=? AND expires>?',
                            (owner, now())).fetchall()
    objects = {row['id']: (row['kind'], json.loads(row['body'])) for row in rows}
    if any(objects.get(pid, (None,))[0] != 'photo' for pid in photo_ids):
        return response
    candidates = []
    for key, (kind, binding) in objects.items():
        if kind != 'ocr_binding' or binding['base_card_id'] != card['card_id']:
            continue
        bound = binding['photo_ids']
        # Adding/replacing a photo invalidates an older whole-card assessment.
        if len(bound) != len(photo_ids) or set(bound) != set(photo_ids):
            continue
        job_kind, job = objects.get(key.removesuffix('-binding'), (None, {}))
        result_kind, result = objects.get(job.get('result_card_id'), (None, {}))
        if job_kind == 'job' and job.get('status') == 'succeeded' and result_kind == 'card':
            if len(result['photos']) == len(bound) and len(set(bound)) == len(bound):
                candidates.append((job, binding, result))
    if not candidates:
        return response
    job, binding, result = max(candidates, key=lambda item: (item[0]['created_at'], item[0]['job_id']))
    analysis = copy.deepcopy(result)
    mapping = dict(zip([p['photo_id'] for p in analysis['photos']], binding['photo_ids'], strict=True))
    originals = {p['photo_id']: p for p in card['photos']}
    for photo in analysis['photos']:
        mapped = mapping[photo['photo_id']]
        photo.update(photo_id=mapped, url=originals[mapped]['url'])
    for source in analysis['sources']:
        if source['photo_id'] in mapping:
            source['photo_id'] = mapping[source['photo_id']]
    moderate(analysis)
    projected = recommendations(analysis)
    issues = [copy.deepcopy(i) for i in analysis['issues'] if i['rule_id'] in PHOTO_RULES]
    issue_ids = {}
    for issue in issues:
        old_id = issue['issue_id']
        issue['issue_id'] = f"photo-analysis:{job['job_id']}:{old_id}"
        issue_ids[old_id] = issue['issue_id']
        if not issue['photo_ids']:
            issue['photo_ids'] = photo_ids[:]
    response['photo_analysis'] = dict(job_id=job['job_id'], requested_at=job['created_at'],
                                      photos=analysis['photos'], issues=issues)
    response['recommendations'] = [r for r in response['recommendations'] if r['rule_id'] not in PHOTO_RULES]
    for item in projected['recommendations']:
        if item['rule_id'] not in PHOTO_RULES:
            continue
        item.update(card_revision=card['revision'], source_ids=[],
                    recommendation_id=f"photo-analysis:{job['job_id']}:{item['recommendation_id']}",
                    issue_ids=[issue_ids[i] for i in item['issue_ids']])
        response['recommendations'].append(item)
    response['recommendations'].sort(key=lambda item: item['priority'] != 'blocker')
    return response
