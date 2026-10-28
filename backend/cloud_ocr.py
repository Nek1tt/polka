"""Google Vision OCR, explicit API mode only. No catalog and no silent fallback."""
import base64
import io
import json
import math
import os
import httpx
from PIL import Image

PROVIDER = 'Google Cloud Vision DOCUMENT_TEXT_DETECTION / RU+EN hints'
ENDPOINT = 'https://vision.googleapis.com/v1/images:annotate'


def configured():
    return bool(os.getenv('GOOGLE_VISION_API_KEY', '').strip())


def box(vertices, width, height):
    xs = [float(v.get('x', 0)) for v in vertices]
    ys = [float(v.get('y', 0)) for v in vertices]
    if not xs or not ys or not all(math.isfinite(v) for v in xs + ys):
        raise ValueError('INVALID_OCR_GEOMETRY')
    return [max(0., min(xs) / width), max(0., min(ys) / height),
            min(1., max(xs) / width), min(1., max(ys) / height)]


def parse_response(payload):
    responses = payload.get('responses', [])
    if len(responses) != 1 or responses[0].get('error'):
        raise RuntimeError('CLOUD_OCR_ERROR')
    lines = []
    for page in responses[0].get('fullTextAnnotation', {}).get('pages', []):
        width, height = page['width'], page['height']
        if width <= 0 or height <= 0:
            raise ValueError('INVALID_OCR_SIZE')
        def emit(words):
            if not words:
                return
            bounds = [w['bbox'] for w in words]
            confidence = min(w['confidence'] for w in words) / 100
            lines.append(dict(text=' '.join(w['text'] for w in words), confidence=confidence, words=words,
                              bbox=[min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds)]))
        for block in page.get('blocks', []):
            for paragraph in block.get('paragraphs', []):
                words = []
                for word in paragraph.get('words', []):
                    symbols = word.get('symbols', [])
                    text = ''.join(s.get('text', '') for s in symbols)
                    confidence = float(word.get('confidence', 0))
                    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                        raise ValueError('INVALID_OCR_SCORE')
                    bbox = box(word.get('boundingBox', {}).get('vertices', []), width, height)
                    if text.strip() and bbox[0] < bbox[2] and bbox[1] < bbox[3]:
                        words.append(dict(text=text, confidence=confidence * 100, bbox=bbox))
                    end = symbols[-1].get('property', {}).get('detectedBreak', {}).get('type') if symbols else None
                    if end in ('EOL_SURE_SPACE', 'LINE_BREAK', 'HYPHEN'):
                        emit(words)
                        words = []
                emit(words)
    return lines


def recognize(path):
    key = os.getenv('GOOGLE_VISION_API_KEY', '').strip()
    if not key:
        raise RuntimeError('CLOUD_NOT_CONFIGURED')
    with Image.open(path) as im:
        output = io.BytesIO()
        im.convert('RGB').save(output, format='JPEG', quality=95)
    if output.tell() > 8_000_000:
        raise ValueError('CLOUD_IMAGE_TOO_LARGE')
    request = {'requests': [{'image': {'content': base64.b64encode(output.getvalue()).decode('ascii')},
                            'features': [{'type': 'DOCUMENT_TEXT_DETECTION'}],
                            'imageContext': {'languageHints': ['ru', 'en']}}]}
    # Fixed host, no redirects/retries: prevent leaked keys and surprise paid calls.
    with httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False) as client:
        with client.stream('POST', ENDPOINT, headers={'X-Goog-Api-Key': key}, json=request) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 8_000_000:
                    raise ValueError('CLOUD_RESPONSE_TOO_LARGE')
    return parse_response(json.loads(data))
