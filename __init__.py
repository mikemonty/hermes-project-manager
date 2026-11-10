"""Agent tools for the explicitly selected Portable Project Store v2 root."""
import json, re
from .bridge_store import Store
from .media_catalog import register as register_media_tools
from .block_api import inspect as blocks_inspect, save as blocks_save, insert as blocks_insert, move as blocks_move
ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')

def initialize(root, project_id):
    """Initialize metadata in an existing empty/uninitialized chosen folder, exclusively."""
    if not isinstance(project_id, str) or not ID.fullmatch(project_id): raise ValueError('invalid project_id')
    import os, secrets
    from pathlib import Path
    p=Path(root)
    if not p.is_absolute() or p.is_symlink() or not p.is_dir(): raise ValueError('existing absolute non-symlink folder required')
    data=json.dumps({'schema':1,'projectId':project_id},separators=(',',':')).encode()
    tmp='.hermespm-init-'+secrets.token_hex(12)
    with Store(root) as store:
        try:
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,dir_fd=store._dirfd)
            try:
                view=memoryview(data)
                while view:
                    n=os.write(fd,view)
                    if n<=0: raise OSError('short write')
                    view=view[n:]
                os.fsync(fd)
            finally: os.close(fd)
            os.link(tmp,'.hermespm-project.json',src_dir_fd=store._dirfd,dst_dir_fd=store._dirfd,follow_symlinks=False)
            return {'root':str(p.resolve()),'projectId':project_id,'initialized':True}
        except FileExistsError: raise StoreConflict('project metadata already exists; not overwritten')
        finally:
            try: os.unlink(tmp,dir_fd=store._dirfd)
            except FileNotFoundError: pass
class StoreConflict(Exception): pass

def create(root, unit_id, kind, payload):
    if not isinstance(unit_id,str) or not ID.fullmatch(unit_id) or not isinstance(kind,str) or kind not in ('source','draft','review','notes'): raise ValueError('invalid unit or kind')
    with Store(root) as store: return store.append(unit_id,0,'create-'+unit_id,kind,payload)
def organize(root, unit_id, kind, title, section_id=None, text=''):
    if not isinstance(unit_id,str) or not ID.fullmatch(unit_id) or not isinstance(title,str) or not title: raise ValueError('invalid unit or title')
    if kind=='section': payload={'type':'section','title':title}
    elif kind=='unit':
        if not isinstance(section_id,str) or not ID.fullmatch(section_id): raise ValueError('valid section_id required')
        if not isinstance(text,str): raise ValueError('text must be a string')
        payload={'type':'unit','title':title,'sectionId':section_id,'text':text}
    else: raise ValueError('kind must be section or unit')
    with Store(root) as store:
        rows=store.list()
        if kind=='unit' and not any(e['unitId']==section_id and e['kind']=='source' and isinstance(e['payload'],dict) and e['payload'].get('type')=='section' for e in rows): raise ValueError('section_id does not identify an existing section')
        return store.append(unit_id,0,'create-'+unit_id,'source',payload)
def list_units(root):
    with Store(root) as store: rows=store.list()
    sections=[]; units={}
    for e in rows:
        p=e['payload']; u=e['unitId']
        if e['kind']=='source' and isinstance(p,dict) and p.get('type')=='section':
            if not any(s['id']==u for s in sections): sections.append({'id':u,'title':p.get('title'),'units':[]})
            continue
        unit=units.setdefault(u,{'id':u,'title':u,'source':'','draft':'','review':'Not reviewed','notes':''})
        if e['kind']=='source' and isinstance(p,dict) and p.get('type')=='unit': unit.update(title=p.get('title',u),sectionId=p.get('sectionId'),source=p.get('text',''))
        elif e['kind']=='source': unit['source']=p if isinstance(p,str) else json.dumps(p,ensure_ascii=False)
        else: unit[e['kind']]=p
    for u in units.values():
        for s in sections:
            if s['id']==u.get('sectionId'): s['units'].append(u)
    return {'sections':sections,'units':units,'events':rows}
def read(root, unit_id):
    with Store(root) as store: rows=store.history(unit_id)
    if not rows: raise ValueError('unit not found')
    return {'unitId':unit_id,'version':len(rows),'history':rows,'state':list_units(root)}
def edit(root, unit_id, expected_version, kind, payload, event_id):
    with Store(root) as store: return store.append(unit_id, expected_version, event_id, kind, payload)
STR={'type':'string','minLength':1}; ROOT={'type':'string','description':'Existing absolute project folder; never inferred.'}
SCHEMAS={
'project_initialize':{'type':'object','properties':{'root':ROOT,'project_id':STR},'required':['root','project_id'],'additionalProperties':False},
'project_create':{'type':'object','properties':{'root':ROOT,'unit_id':STR,'kind':{'type':'string','enum':['source','draft','review','notes']},'payload':{'description':'JSON value; source section/unit use shared editor payload format.'}},'required':['root','unit_id','kind','payload'],'additionalProperties':False},
'project_organize':{'type':'object','properties':{'root':ROOT,'unit_id':STR,'kind':{'type':'string','enum':['section','unit']},'title':STR,'section_id':STR,'text':{'type':'string'}},'required':['root','unit_id','kind','title'],'additionalProperties':False},
'project_list':{'type':'object','properties':{'root':ROOT},'required':['root'],'additionalProperties':False},
'project_read':{'type':'object','properties':{'root':ROOT,'unit_id':STR},'required':['root','unit_id'],'additionalProperties':False},
'project_edit':{'type':'object','properties':{'root':ROOT,'unit_id':STR,'expected_version':{'type':'integer','minimum':0},'kind':{'type':'string','enum':['source','draft','review','notes']},'payload':{},'event_id':STR},'required':['root','unit_id','expected_version','kind','payload','event_id'],'additionalProperties':False}}
BLOCK_ROOT={'type':'string','description':'Explicit absolute path to an existing project folder; never inferred.'}
BLOCK_I={'type':'integer','minimum':0}
for _n,_props,_req in [
 ('project_blocks_inspect',{'root':BLOCK_ROOT,'unit_id':STR},['root','unit_id']),
 ('project_blocks_save',{'root':BLOCK_ROOT,'unit_id':STR,'expected_version':BLOCK_I,'expected_legacy_version':BLOCK_I,'op':{'type':'string','enum':['put','delete','replace']},'block_id':STR,'after_block_id':{'type':['string','null']},'text':{'type':'string'},'event_id':STR},['root','unit_id','expected_version','expected_legacy_version','op','block_id','after_block_id','text','event_id']),
 ('project_blocks_insert',{'root':BLOCK_ROOT,'unit_id':STR,'expected_version':BLOCK_I,'expected_legacy_version':BLOCK_I,'block_id':STR,'after_block_id':{'type':['string','null']},'text':{'type':'string'},'event_id':STR},['root','unit_id','expected_version','expected_legacy_version','block_id','after_block_id','text','event_id']),
 ('project_blocks_move',{'root':BLOCK_ROOT,'unit_id':STR,'expected_version':BLOCK_I,'expected_legacy_version':BLOCK_I,'block_id':STR,'after_block_id':{'type':['string','null']},'event_id':STR},['root','unit_id','expected_version','expected_legacy_version','block_id','after_block_id','event_id'])]:
 SCHEMAS[_n]={'type':'object','properties':_props,'required':_req,'additionalProperties':False}
OPS={'project_initialize':initialize,'project_create':create,'project_organize':organize,'project_list':list_units,'project_read':read,'project_edit':edit,'project_blocks_inspect':blocks_inspect,'project_blocks_save':blocks_save,'project_blocks_insert':blocks_insert,'project_blocks_move':blocks_move}
DESCRIPTIONS={'project_initialize':'Initialize metadata only in a caller-chosen existing absolute folder; fails without overwrite if metadata exists. Does not register a Hermes project.','project_create':'Append the initial event for a unit; use source payload {type:unit,title,sectionId,text} for shared-editor units.','project_organize':'Create a shared-editor section (source {type:section,title}) or unit (source {type:unit,title,sectionId,text}).','project_list':'Replay all events into shared editor state: sections, units and immutable events.','project_read':'Read one unit complete version history and current replayed state.','project_edit':'Append source/draft/review/notes event only at exact expected version; stale writes conflict without overwrite.',
'project_blocks_inspect':'Inspect block sidecar events and replayed blocks.', 'project_blocks_save':'Save, replace, or delete a block at exact expected versions.', 'project_blocks_insert':'Insert a block at exact expected versions.', 'project_blocks_move':'Move a block using a replacement snapshot.'}
def _handler(fn):
 def handle(args, **kw):
  try:return json.dumps({'result':fn(**dict(args))},ensure_ascii=False)
  except Exception as e:return json.dumps({'error':f'{type(e).__name__}: {e}'},ensure_ascii=False)
 return handle
def register(ctx):
 for name,fn in OPS.items():
  desc=DESCRIPTIONS[name]
  ctx.register_tool(name=name,toolset='project_content',schema={'name':name,'description':desc,'parameters':SCHEMAS[name]},handler=_handler(fn),description=desc)
 register_media_tools(ctx)
