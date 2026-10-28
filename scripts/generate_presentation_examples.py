"""Clearly marked contract fixtures, not inference results or public cards."""
import sys,json
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.catalog import list_templates,category_profile
from backend.preview import preview
from backend.recommendations import recommendations
from backend.domain import moderate, template
from backend.photo_analysis import PHOTO_RULES

out=ROOT/'contracts/presentation-examples';out.mkdir(exist_ok=True)
# Keep current synthetic contract examples aligned with the product's rules.
for path in (ROOT/'contracts/examples').glob('*.json'):
    card=json.loads(path.read_text(encoding='utf-8'))
    if 'card_id' not in card: continue
    card['ruleset_version']='2.4.1'
    if path.stem=='needs_information':
        title=next(f for f in card['fields'] if f['field_id']=='product_name')
        title.update(value=None,reviewed=False,status='missing',source_ids=[],confidence=None,candidates=[])
    if card['description']['mode']=='template':
        reviewed=card['description']['reviewed'];card['description']=template(card);card['description']['reviewed']=reviewed
    moderate(card)
    path.write_text(json.dumps(card,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def fixture(name):return json.loads((ROOT/f'contracts/examples/{name}.json').read_text(encoding='utf-8'))
def write(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
write('templates.json',{'templates':list_templates(),'category_profiles':[category_profile('unknown')]})
write('preview-incomplete.json',preview(fixture('needs_information'),'market_v1',1))
write('preview-confirmed.json',preview(fixture('confirmed'),'market_v1',1))
write('recommendations-conflict.json',recommendations(fixture('needs_review_conflict')))
base=fixture('needs_information')
analysis=deepcopy(base)
for photo in analysis['photos']: photo['quality']='unreadable'
moderate(analysis)
value=recommendations(base)
value['photo_analysis']=dict(job_id='fixture-photo-job', requested_at=base['created_at'],
                             photos=analysis['photos'], issues=[i for i in analysis['issues'] if i['rule_id'] in PHOTO_RULES])
value['recommendations']=[r for r in value['recommendations'] if r['rule_id'] not in PHOTO_RULES]
for item in recommendations(analysis)['recommendations']:
    if item['rule_id'] in PHOTO_RULES:
        item.update(card_revision=base['revision'],source_ids=[])
        value['recommendations'].append(item)
write('recommendations-photo-analysis.json',value)
print('Generated 5 contract fixtures; provider_mode=fixture for card projections.')
