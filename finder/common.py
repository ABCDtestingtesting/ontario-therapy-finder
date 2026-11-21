"""Shared facilities. No implicit success and no silent zero-filling."""
from __future__ import annotations
import json, os, re, tempfile, time, threading, hashlib
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('THERAPY_DATA_HOME',str(ROOT/'data')))
LOGS=DATA.parent/'logs' if 'THERAPY_DATA_HOME' in os.environ else ROOT/'logs'
OUTPUT=DATA.parent/'output' if 'THERAPY_DATA_HOME' in os.environ else ROOT/'output'
BIN=ROOT/'bin'
for p in (DATA,LOGS,OUTPUT,BIN):p.mkdir(parents=True,exist_ok=True)
FSA_RE=re.compile(r'^[KLMNP][0-9][A-Z]$')
class Incomplete(RuntimeError):pass
class SourceUnavailable(Incomplete):pass
class InvalidEvidence(Incomplete):pass

def valid_fsa(code):return bool(FSA_RE.fullmatch(str(code).upper()))
def utc():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def write_json(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as fh:
        json.dump(obj,fh,indent=2,ensure_ascii=False,allow_nan=False); temp=fh.name
        fh.flush();os.fsync(fh.fileno())
    os.replace(temp,path)
def read_json(path, default=None):
    try:
        with open(path,encoding='utf8') as fh:return json.load(fh)
    except FileNotFoundError:
        return default if default is not None else {}
def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def safe_name(code):
    if not valid_fsa(code):raise ValueError('Invalid Ontario postal area')
    return code.upper()
