"""Explicit setup only. Download known open weights and verify SHA256."""
import hashlib
from pathlib import Path
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.local_ocr import MODEL_DIR, MODELS

BASE = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx'


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(180, connect=15), follow_redirects=True) as client:
        for task, (filename, checksum) in MODELS.items():
            path = MODEL_DIR / filename
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
                print(f'Verified: {filename}')
                continue
            version = 'PP-OCRv4' if task == 'cls' else 'PP-OCRv5'
            tmp = path.with_suffix('.part')
            try:
                with client.stream('GET', f'{BASE}/{version}/{task}/{filename}') as response:
                    response.raise_for_status()
                    with tmp.open('wb') as output:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                            if output.tell() > 100_000_000:
                                raise RuntimeError('MODEL_TOO_LARGE')
                if hashlib.sha256(tmp.read_bytes()).hexdigest() != checksum:
                    raise RuntimeError(f'Model checksum mismatch: {filename}')
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
            print(f'Verified: {filename} ({path.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
