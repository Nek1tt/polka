"""Bounded local subprocess keeps native inference out of the web worker."""
import contextlib
import json
import sys
from .local_ocr import create_engine, recognize


def main():
    # Third-party loggers must never corrupt the JSON transport.
    with contextlib.redirect_stdout(sys.stderr):
        engine = create_engine()
        results = [] if sys.argv[1:] == ['--check'] else [recognize(engine, p) for p in sys.argv[1:]]
    print(json.dumps(results, ensure_ascii=True))


if __name__ == '__main__':
    main()
