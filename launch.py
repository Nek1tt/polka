"""Local launcher: identify this checkout and reserve its port before app startup."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
from urllib.request import urlopen
from backend.version import API_VERSION

ROOT = Path(__file__).resolve().parent

def configure_local_origins(port):
    configured=[value.strip() for value in os.getenv('ALLOWED_ORIGINS','').split(',') if value.strip()]
    os.environ['ALLOWED_ORIGINS']=','.join(dict.fromkeys([*configured,f'http://localhost:{port}',f'http://127.0.0.1:{port}']))

def main(argv=None):
    parser = argparse.ArgumentParser(description='Запуск Полки из этой папки')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--check', action='store_true', help='Показать версию/папку и проверить порт без запуска')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535: parser.error('Порт должен быть от 1 до 65535')
    print(f'Полка — API {API_VERSION}', flush=True)
    print(f'Папка проекта: {ROOT}', flush=True)
    print(f'Адрес: http://127.0.0.1:{args.port}', flush=True)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', args.port))
    except OSError:
        listener.close()
        print(f'Порт {args.port} уже занят или недоступен. Новый сервер НЕ запущен.', file=sys.stderr)
        try:
            with urlopen(f'http://127.0.0.1:{args.port}/openapi.json', timeout=1) as response:
                info = json.loads(response.read(1_000_000))['info']
            print(f'На этом порту отвечает API {info["version"]}.', file=sys.stderr)
        except Exception:
            pass
        print('Остановите прежний сервер в его терминале (Ctrl+C) или запустите start.cmd --port 8002.', file=sys.stderr)
        return 2
    if args.check:
        listener.close()
        print('Порт свободен. Это проверка; сервер не запускался.')
        return 0
    os.chdir(ROOT)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    configure_local_origins(args.port)
    try:
        import uvicorn
        listener.listen(2048)
        print('Версия работающего процесса: /api/v1/version. Остановка: Ctrl+C.', flush=True)
        uvicorn.Server(uvicorn.Config('backend.main:app', host='127.0.0.1', port=args.port)).run(sockets=[listener])
    finally:
        listener.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
