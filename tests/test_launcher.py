import os
from pathlib import Path
import socket
import subprocess
import sys
import pytest
from backend.version import API_VERSION

ROOT=Path(__file__).resolve().parents[1]

def test_selected_local_port_is_allowed_despite_old_dotenv_origin(monkeypatch):
    from launch import configure_local_origins
    monkeypatch.setenv('ALLOWED_ORIGINS','http://localhost:8005,https://demo.example')
    configure_local_origins(8012)
    origins=set(os.environ['ALLOWED_ORIGINS'].split(','))
    assert {'http://localhost:8012','http://127.0.0.1:8012','https://demo.example'}<=origins
    assert '*' not in origins

def run_check(port):
    return subprocess.run([sys.executable,str(ROOT/'launch.py'),'--check','--port',str(port)],
                          capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'},timeout=5)

def test_check_identifies_checkout_and_version_without_starting_server():
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1',0));port=candidate.getsockname()[1]
    result=run_check(port)
    assert result.returncode==0,result.stderr
    assert API_VERSION in result.stdout and str(ROOT) in result.stdout
    assert 'сервер не запускался' in result.stdout
    with socket.socket() as still_free:
        still_free.bind(('127.0.0.1',port))

def test_occupied_port_cannot_silently_serve_a_previous_process():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',0));port=occupied.getsockname()[1]
        result=run_check(port)
    assert result.returncode==2
    assert 'Новый сервер НЕ запущен' in result.stderr

def test_windows_batch_is_ascii_crlf_without_bom():
    data=(ROOT/'start.cmd').read_bytes()
    data.decode('ascii')
    assert b'\n' not in data.replace(b'\r\n',b'')
    assert data.startswith(b'@echo off\r\n')

@pytest.mark.skipif(sys.platform!='win32',reason='Windows cmd.exe integration')
def test_real_cmd_executes_launcher_help_without_bootstrap_or_broken_commands():
    result=subprocess.run(['cmd.exe','/d','/c','start.cmd','--help'],cwd=ROOT,
                          capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert '--port' in result.stdout and '--check' in result.stdout
    assert 'not recognized' not in (result.stdout+result.stderr)
