"""Portable flat-file bridge; explicit root, fail-closed reads."""
import json, os, re, stat, secrets
from pathlib import Path
ID=re.compile(r'^[A-Za-z0-9_-]{1,80}$'); KINDS={'source','draft','review','notes'}; PREFIX='.pm-event-'; MAX=4*1024*1024; META_MAX=65536; MAX_ENTRIES=10000; MAX_VERSION=999999999999
class Conflict(Exception): pass
class Store:
 def __init__(self,root):
  root = os.fspath(root)
  if not isinstance(root,str) or not root or not Path(root).is_absolute(): raise ValueError('explicit absolute project root required')
  raw=Path(root)
  if raw.is_symlink(): raise ValueError('symlink root rejected')
  self.root=raw.resolve(strict=True)
  if not self.root.is_dir(): raise ValueError('existing project root required')
  self._dirfd=os.open(self.root,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
  self._closed=False
 def close(self):
  if not self._closed:
   os.close(self._dirfd); self._closed=True
 def __enter__(self):
  if self._closed: raise ValueError('store is closed')
  return self
 def __exit__(self, *_): self.close()
 def _read_name(self,name,limit=MAX):
  if not isinstance(name,str) or '/' in name or '\\' in name or name in ('.','..'): raise Conflict('invalid flat filename')
  try: fd=os.open(name,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0),dir_fd=self._dirfd)
  except OSError as e: raise Conflict('missing/unsafe file') from e
  try:
   st=os.fstat(fd)
   if not stat.S_ISREG(st.st_mode) or st.st_size>limit: raise Conflict('unsafe/oversized file')
   chunks=[]; total=0
   while True:
    b=os.read(fd,min(65536,limit+1-total))
    if not b: break
    total+=len(b)
    if total>limit: raise Conflict('file too large')
    chunks.append(b)
   return b''.join(chunks)
  finally: os.close(fd)
 def project(self):
  try:p=json.loads(self._read_name('.hermespm-project.json',META_MAX).decode('utf-8'))
  except Exception as e: raise Conflict('malformed/missing .hermespm-project.json') from e
  if not isinstance(p,dict) or set(p)!={'schema','projectId'} or type(p['schema']) is not int or p['schema']!=1 or not isinstance(p['projectId'],str) or not ID.fullmatch(p['projectId']): raise Conflict('invalid project schema')
  return p['projectId']
 def _entries(self):
  try: names=os.listdir(self._dirfd)
  except OSError as e: raise Conflict('directory listing failed') from e
  if len(names)>MAX_ENTRIES: raise Conflict('directory entry limit exceeded')
  return names
 def history(self,unit):
  if not isinstance(unit,str) or not ID.fullmatch(unit): raise ValueError('invalid unitId')
  pid=self.project(); pattern=re.compile(r'^'+re.escape(PREFIX+unit+'-')+r'(\d{12})\.json$'); rows=[]
  for name in self._entries():
   if not name.startswith(PREFIX): continue
   m=re.fullmatch(r'\.pm-event-([A-Za-z0-9_-]{1,80})-(\d{12})\.json',name)
   if not m: raise Conflict('malformed event filename')
   if m.group(1)!=unit: continue
   version=int(m.group(2))
   if version>MAX_VERSION: raise Conflict('version overflow')
   try:e=json.loads(self._read_name(name).decode('utf-8'))
   except Exception as ex: raise Conflict('malformed/unsafe event JSON') from ex
   if not isinstance(e,dict) or set(e)!={'schema','projectId','unitId','version','eventId','kind','payload'} or type(e.get('schema')) is not int or e['schema']!=1 or e.get('projectId')!=pid or e.get('unitId')!=unit or type(e.get('version')) is not int or e['version']!=version or not isinstance(e.get('eventId'),str) or not ID.fullmatch(e['eventId']) or not isinstance(e.get('kind'),str) or e['kind'] not in KINDS: raise Conflict('invalid event')
   rows.append(e)
  rows.sort(key=lambda e:e['version'])
  if [e['version'] for e in rows]!=list(range(1,len(rows)+1)) or len({e['eventId'] for e in rows})!=len(rows): raise Conflict('history conflict')
  return rows
 def list(self):
  ids=set()
  for name in self._entries():
   if name.startswith(PREFIX):
    m=re.fullmatch(r'\.pm-event-([A-Za-z0-9_-]{1,80})-(\d{12})\.json',name)
    if not m or int(m.group(2))>MAX_VERSION: raise Conflict('malformed event filename')
    ids.add(m.group(1))
  return [e for u in sorted(ids) for e in self.history(u)]
 def append(self,unit,expected,event_id,kind,payload):
  if not isinstance(event_id,str) or not ID.fullmatch(event_id) or not isinstance(kind,str) or kind not in KINDS: raise ValueError('invalid event fields')
  rows=self.history(unit)
  if type(expected) is not int or len(rows)!=expected or expected>=MAX_VERSION: raise Conflict('version conflict')
  e={'schema':1,'projectId':self.project(),'unitId':unit,'version':expected+1,'eventId':event_id,'kind':kind,'payload':payload}
  data=json.dumps(e,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
  if len(data)>MAX: raise ValueError('event too large')
  target=f'{PREFIX}{unit}-{expected+1:012d}.json'; tmp=f'.hermespm-tmp-{secrets.token_hex(12)}'
  try:
   fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,dir_fd=self._dirfd)
   try:
    view=memoryview(data)
    while view:
     n=os.write(fd,view)
     if n<=0: raise OSError('short write')
     view=view[n:]
    os.fsync(fd)
   finally: os.close(fd)
   # link() atomically publishes without replacing an existing version.
   os.link(tmp,target,src_dir_fd=self._dirfd,dst_dir_fd=self._dirfd,follow_symlinks=False)
   os.unlink(tmp,dir_fd=self._dirfd)
   return e
  except FileExistsError as ex: raise Conflict('version conflict') from ex
  except OSError as ex: raise Conflict('exclusive publication failed') from ex
  finally:
   try: os.unlink(tmp,dir_fd=self._dirfd)
   except FileNotFoundError: pass
