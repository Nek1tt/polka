"""Tesseract TSV is literal TSV, not CSV with quoted multiline cells."""
import math
import re

def parse_words(tsv, width, height):
    words = []
    for line in tsv.splitlines():
        columns = line.split('\t', 11)
        if len(columns) != 12 or columns[0] != '5' or not columns[11].strip():
            continue
        try:
            hierarchy = tuple(int(v) for v in columns[1:6])
            x, y, w, h = (int(v) for v in columns[6:10])
            confidence = float(columns[10])
        except ValueError:
            continue
        if not math.isfinite(confidence) or not -1 <= confidence <= 100 or w <= 0 or h <= 0:
            continue
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x0 >= x1 or y0 >= y1:
            continue
        words.append(dict(text=columns[11].strip(), confidence=confidence,
                          group=hierarchy[:4], bbox=[x0/width,y0/height,x1/width,y1/height]))
    return words

def meaningful_word(word):
    # An engineering heuristic, not a calibrated probability of text presence.
    letters = re.findall(r'[A-Za-zА-Яа-яЁё]', word['text'])
    return (word['confidence'] >= 60 and len(letters) >= 3
            and len(letters) / max(1, len(word['text'])) >= .7)

def text_quality(words, width, height):
    useful = [w for w in words if meaningful_word(w)]
    letters = sum(len(re.findall(r'[A-Za-zА-Яа-яЁё]', w['text'])) for w in useful)
    # A few isolated high-scoring symbols must not turn a photograph into an OCR label.
    if len(useful) >= 3 and letters >= 15:
        return 'readable' if min(width, height) >= 300 else 'uncertain'
    return 'uncertain' if useful else 'unreadable'
