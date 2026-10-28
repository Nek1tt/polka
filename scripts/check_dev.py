"""Small explicit rule check; not an OCR or product accuracy benchmark."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.inference import classify_line
cases=[('Brand: Example',('brand','Example')),('Материал: хлопок',('material','хлопок')),('100ml 330ml',(None,None))]
for text,expected in cases:
    assert classify_line(text)==expected,text
print('RU/EN explicit rule smoke: 3 passed. Not an accuracy benchmark.')
