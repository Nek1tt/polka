"""Pinned PP-OCRv5 mobile RU/EN inference, CPU only, no runtime downloads."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.getenv('LOCAL_OCR_CACHE', str(ROOT / 'model-cache' / 'ppocrv5')))
MODELS = {
    'det': ('ch_PP-OCRv5_det_mobile.onnx', '4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae'),
    'cls': ('ch_ppocr_mobile_v2.0_cls_mobile.onnx', 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c'),
    'rec': ('eslav_PP-OCRv5_rec_mobile.onnx', '08705d6721849b1347d26187f15a5e362c431963a2a62bfff4feac578c489aab'),
}
PROVIDER = 'PP-OCRv5 mobile / eslav RU+EN / RapidOCR 3.10.0 / ONNX Runtime CPU'


def settings():
    from rapidocr import EngineType, LangRec, ModelType, OCRVersion
    params = {'Global.text_score': 0.0, 'Global.log_level': 'error',
              'EngineConfig.onnxruntime.intra_op_num_threads': max(1, min(8, int(os.getenv('OCR_CPU_THREADS', '4')))),
              'EngineConfig.onnxruntime.inter_op_num_threads': 1}
    for task in ('Det', 'Cls', 'Rec'):
        params.update({f'{task}.engine_type': EngineType.ONNXRUNTIME,
                       f'{task}.model_type': ModelType.MOBILE,
                       f'{task}.ocr_version': OCRVersion.PPOCRV4 if task == 'Cls' else OCRVersion.PPOCRV5,
                       f'{task}.model_path': str(MODEL_DIR / MODELS[task.lower()][0])})
    params['Rec.lang_type'] = LangRec.ESLAV
    return params


def create_engine():
    import hashlib
    from rapidocr import RapidOCR
    for filename, checksum in MODELS.values():
        path = MODEL_DIR / filename
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('LOCAL_MODEL_MISSING_OR_INVALID')
    return RapidOCR(params=settings())


def recognize(engine, path):
    from PIL import Image
    with Image.open(path) as im:
        width, height = im.size
    result = engine(str(path))
    lines = []
    if result.txts is None:
        return lines
    for text, confidence, polygon in zip(result.txts, result.scores, result.boxes):
        xs, ys = polygon[:, 0], polygon[:, 1]
        bbox = [max(0., float(min(xs)) / width), max(0., float(min(ys)) / height),
                min(1., float(max(xs)) / width), min(1., float(max(ys)) / height)]
        if text.strip() and bbox[0] < bbox[2] and bbox[1] < bbox[3]:
            lines.append(dict(text=text.strip(), confidence=float(confidence), bbox=bbox, words=[]))
    return lines
