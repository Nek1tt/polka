"""Local-only private photo check. Report contains counts, never photo/text."""
import argparse
import json
from pathlib import Path
import sys
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.inference import Providers
from backend.ocr_review import ocr_review

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('photo',type=Path)
    parser.add_argument('--report',type=Path,default=ROOT/'docs/v2.2-real-label-check.json')
    args=parser.parse_args()
    with Image.open(args.photo) as image:width,height=image.size
    card=Providers().analyze([dict(photo_id='local-test',url='',width=width,height=height,quality='uncertain')],[args.photo],{'ocr_mode':'local'},lambda _:None)
    review=ocr_review(card)
    report=dict(image_size=[width,height],counts=review['counts'],suggested_fields=[f['field_id'] for f in card['fields'] if f['value']],
                title_candidates=sum(l['group']=='useful' and l['field_id'] is None for l in review['lines']),
                state=card['readiness']['state'],provider=card['ocr']['provider'],
                note='One real photograph, no independent accuracy estimate. Filtering counts are not CER. No photograph/transcript included.')
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
