"""Agent-facing API for the Desktop candidate's v1 block sidecar."""
from __future__ import annotations
import json, re
from pathlib import Path
try:
    from .bridge_store import Store, Conflict
except ImportError:
    from bridge_store import Store, Conflict
ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
PREFIX = '.pm-block-event-v1-'
KEYS = {'schema','projectId','unitId','version','eventId','op','blockId','afterBlockId','text','baseLegacyVersion'}

def _text(v):
    if not isinstance(v,str): raise ValueError('text must be a string')
    if len(v.encode('utf-8')) > 4*1024*1024: raise ValueError('block text too large')
    return v

def _history(root, unit):
    if not isinstance(unit,str) or not ID.fullmatch(unit): raise ValueError('invalid unitId')
    root=Path(root)
    try: pid=json.loads((root/'.hermespm-project.json').read_text('utf-8'))['projectId']
    except Exception as e: raise Conflict('invalid project metadata') from e
    rows=[]
    for p in root.iterdir():
        if not p.name.startswith(PREFIX): continue
        m=re.fullmatch(re.escape(PREFIX)+r'([A-Za-z0-9_-]{1,80})-(\d{12})\.json',p.name)
        if not m: raise Conflict('malformed block filename')
        if m.group(1)!=unit: continue
        if p.is_symlink() or not p.is_file() or p.stat().st_size>4*1024*1024: raise Conflict('unsafe/oversized block event')
        try: e=json.loads(p.read_text('utf-8'))
        except Exception as ex: raise Conflict('malformed block JSON') from ex
        if not isinstance(e,dict) or set(e)!=KEYS or type(e['schema']) is not int or e['schema']!=1 or e['projectId']!=pid or e['unitId']!=unit or type(e['version']) is not int or e['version']!=int(m[2]) or not isinstance(e['eventId'],str) or not ID.fullmatch(e['eventId']) or not isinstance(e['blockId'],str) or not ID.fullmatch(e['blockId']) or not (e['afterBlockId'] is None or isinstance(e['afterBlockId'],str) and ID.fullmatch(e['afterBlockId'])) or type(e['baseLegacyVersion']) is not int or e['baseLegacyVersion']<0 or not isinstance(e['text'],str) or e['op'] not in ('put','delete','replace') or (e['op']=='delete' and e['text']!=''):
            raise Conflict('invalid block event')
        rows.append(e)
    rows.sort(key=lambda x:x['version'])
    if [e['version'] for e in rows]!=list(range(1,len(rows)+1)) or len({e['eventId'] for e in rows})!=len(rows): raise Conflict('corrupt block history')
    return rows

def replay(events):
    state={}
    for e in events:
        if e['op']=='replace':
            try: snap=json.loads(e['text'])
            except Exception as ex: raise Conflict('invalid snapshot') from ex
            if not isinstance(snap,list): raise Conflict('invalid snapshot')
            state={}
            for b in snap:
                if not isinstance(b,dict) or set(b)!={'blockId','afterBlockId','text'} or not isinstance(b['blockId'],str) or not ID.fullmatch(b['blockId']) or not (b['afterBlockId'] is None or isinstance(b['afterBlockId'],str) and ID.fullmatch(b['afterBlockId'])) or not isinstance(b['text'],str) or b['blockId'] in state: raise Conflict('invalid snapshot block')
                state[b['blockId']]={**e,**b}
        elif e['op']=='delete': state.pop(e['blockId'],None)
        else: state[e['blockId']]=e
    by={k:v for k,v in state.items()}; children={}
    for b in by.values():
        a=b['afterBlockId']
        if a is not None and a not in by: raise Conflict('missing block anchor')
        children.setdefault(a,[]).append(b)
    for a in children: children[a].sort(key=lambda x:x['version'])
    out=[]; seen=set()
    def walk(a):
        for b in children.get(a,[]):
            if b['blockId'] in seen: raise Conflict('block ordering cycle')
            seen.add(b['blockId']); out.append({'blockId':b['blockId'],'text':b['text']}); walk(b['blockId'])
    walk(None)
    if len(seen)!=len(by): raise Conflict('block ordering cycle')
    return out

def inspect(root, unit_id):
    rows=_history(root,unit_id)
    return {'unitId':unit_id,'version':len(rows),'events':rows,'blocks':replay(rows)}

def save(root, unit_id, expected_version, expected_legacy_version, op, block_id, after_block_id, text, event_id):
    if type(expected_version) is not int or expected_version<0: raise ValueError('expected_version must be a nonnegative integer')
    if type(expected_legacy_version) is not int or expected_legacy_version<0: raise ValueError('expected_legacy_version must be a nonnegative integer')
    if op not in ('put','delete','replace') or not isinstance(block_id,str) or not ID.fullmatch(block_id) or not (after_block_id is None or isinstance(after_block_id,str) and ID.fullmatch(after_block_id)) or not isinstance(event_id,str) or not ID.fullmatch(event_id): raise ValueError('invalid block operation fields')
    text=_text(text)
    if op=='delete' and text!='': raise ValueError('delete text must be empty')
    if op=='replace' and (block_id!='snapshot' or after_block_id is not None or not isinstance(json.loads(text),list)): raise ValueError('replace requires snapshot block and JSON array')
    rows=_history(root,unit_id)
    if expected_version!=len(rows): raise Conflict('version conflict')
    pid=json.loads((Path(root)/'.hermespm-project.json').read_text('utf-8'))['projectId']
    event={'schema':1,'projectId':pid,'unitId':unit_id,'version':len(rows)+1,'eventId':event_id,'op':op,'blockId':block_id,'afterBlockId':after_block_id,'text':text,'baseLegacyVersion':expected_legacy_version}
    if any(row['eventId']==event_id for row in rows): raise Conflict('duplicate eventId')
    replay(rows+[event])
    with Store(root) as s:
        # Store's exclusive publication and directory-relative no-follow write discipline.
        data=json.dumps(event,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
        name=f'{PREFIX}{unit_id}-{event["version"]:012d}.json'
        tmp=f'.hermespm-tmp-block-{event_id}'
        fd=None
        try:
            import os
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,dir_fd=s._dirfd)
            view=memoryview(data)
            while view:
                n=os.write(fd,view)
                if n<=0: raise OSError('short write')
                view=view[n:]
            os.fsync(fd); os.close(fd); fd=None
            os.link(tmp,name,src_dir_fd=s._dirfd,dst_dir_fd=s._dirfd,follow_symlinks=False)
        except FileExistsError as e: raise Conflict('version conflict') from e
        except OSError as e: raise Conflict('exclusive publication failed') from e
        finally:
            import os
            if fd is not None: os.close(fd)
            try: os.unlink(tmp,dir_fd=s._dirfd)
            except FileNotFoundError: pass
    return event

def insert(root, unit_id, expected_version, expected_legacy_version, block_id, after_block_id, text, event_id):
    return save(root,unit_id,expected_version,expected_legacy_version,'put',block_id,after_block_id,text,event_id)

def move(root, unit_id, expected_version, expected_legacy_version, block_id, after_block_id, event_id):
    current=inspect(root,unit_id); block=next((b for b in current['blocks'] if b['blockId']==block_id),None)
    if block is None: raise ValueError('unknown blockId')
    if block_id==after_block_id: raise ValueError('block cannot anchor itself')
    ordered=current['blocks']
    if after_block_id is not None and not any(b['blockId']==after_block_id for b in ordered): raise ValueError('unknown anchor blockId')
    remaining=[b for b in ordered if b['blockId']!=block_id]
    item={'blockId':block_id,'text':block['text']}
    if after_block_id is None: remaining.insert(0,item)
    else:
        index=next(i for i,b in enumerate(remaining) if b['blockId']==after_block_id)
        remaining.insert(index+1,item)
    snapshot=[]
    for i,b in enumerate(remaining): snapshot.append({'blockId':b['blockId'],'afterBlockId':remaining[i-1]['blockId'] if i else None,'text':b['text']})
    return save(root,unit_id,expected_version,expected_legacy_version,'replace','snapshot',None,json.dumps(snapshot,separators=(',',':'),ensure_ascii=False),event_id)
