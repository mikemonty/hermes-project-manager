"""Agent access to the Desktop project media sidecar format."""
import hashlib, json, os, re, stat
from .bridge_store import Store, Conflict, MAX_VERSION
from pathlib import Path
PREFIX='.media-catalog-event-'; ID=re.compile(r'^[A-Za-z0-9_-]{1,80}$')

def safe_path(path):
    if not isinstance(path,str) or not path or path.startswith('/') or '\\' in path or any(x in ('','.','..') for x in path.split('/')) or ':' in path.split('/')[0]: raise ValueError('unsafe project-relative POSIX path')
    return path

def media_id(pid,path): return 'media_'+hashlib.sha256((pid+'\0'+path).encode()).hexdigest()[:40]
def external_media_id(pid,folder_id,path): return 'media_'+hashlib.sha256((pid+'\0'+folder_id+'\0'+path).encode()).hexdigest()[:40]
def _validate_external_reference(md,pid):
    if (set(md)!={'id','folderId','relativePath','title','size','mimeType'} or not isinstance(md['folderId'],str) or not ID.fullmatch(md['folderId']) or safe_path(md['relativePath'])!=md['relativePath'] or md['id']!=external_media_id(pid,md['folderId'],md['relativePath']) or type(md['size']) is not int or md['size']<0 or not isinstance(md['title'],str) or not isinstance(md['mimeType'],str)): raise ValueError('invalid external media reference')
    return md
def root_info(root):
    p=Path(root)
    if not p.is_absolute() or p.is_symlink() or not p.is_dir(): raise ValueError('explicit existing absolute non-symlink project root required')
    p=p.resolve(strict=True); m=p/'.hermespm-project.json'
    if m.is_symlink() or not m.is_file() or m.stat().st_size>65536: raise ValueError('project authorization metadata unavailable')
    d=json.loads(m.read_text()); pid=d.get('projectId') if isinstance(d,dict) else None
    if set(d)!={'schema','projectId'} or type(d['schema']) is not int or d['schema']!=1 or not isinstance(pid,str) or not ID.fullmatch(pid): raise ValueError('invalid project authorization metadata')
    return p,pid
def events(root,pid):
    names=os.listdir(root)
    if len(names)>10000: raise ValueError('project directory entry limit exceeded')
    rows=[]
    for n in names:
        if not n.startswith(PREFIX): continue
        m=re.fullmatch(r'\.media-catalog-event-(\d{12})\.json',n)
        if not m: raise ValueError('malformed media event filename')
        f=root/n
        if f.is_symlink() or not f.is_file() or f.stat().st_size>1048576: raise ValueError('unsafe media event')
        e=json.loads(f.read_text()); md=e.get('metadata') if isinstance(e,dict) else None
        if set(e)!={'schema','projectId','version','kind','metadata'} or type(e['schema']) is not int or e['schema']!=1 or e['projectId']!=pid or type(e['version']) is not int or e['version']!=int(m.group(1)) or not isinstance(md,dict): raise ValueError('invalid media event')
        if e['kind']=='media-reference':
            if set(md)!={'id','mimeType','path','size','title'} or safe_path(md['path'])!=md['path'] or md['id']!=media_id(pid,md['path']) or type(md['size']) is not int or md['size']<0 or not isinstance(md['title'],str) or not isinstance(md['mimeType'],str): raise ValueError('invalid media reference')
        elif e['kind']=='media-external-reference': _validate_external_reference(md,pid)
        elif e['kind']=='media-external-reconnect':
            if set(md)!={'id','folderId','relativePath','size'} or not isinstance(md['folderId'],str) or not ID.fullmatch(md['folderId']) or safe_path(md['relativePath'])!=md['relativePath'] or type(md['size']) is not int or md['size']<0 or not isinstance(md['id'],str): raise ValueError('invalid media reconnect')
        elif e['kind']=='media-metadata-update':
            if set(md)!={'media_id','patch'} or not isinstance(md['media_id'],str): raise ValueError('invalid metadata update')
            _validate_patch(md['patch'])
        else: raise ValueError('invalid media event kind')
        rows.append(e)
    rows.sort(key=lambda x:x['version'])
    if any(x['version']!=i+1 for i,x in enumerate(rows)) or len({x['metadata']['path'] for x in rows if x['kind']=='media-reference'})!=sum(x['kind']=='media-reference' for x in rows): raise ValueError('catalog history conflict')
    return rows
def resolve_project(root,project_id):
    """Use caller-selected folder and its marker; no OS sandbox is implied."""
    if not isinstance(project_id,str) or not ID.fullmatch(project_id): raise ValueError('valid project_id required')
    p,pid=root_info(root)
    if pid!=project_id: raise ValueError('project metadata ID mismatch')
    return p,pid

def list_media(root,project_id,query=''):
    p,pid=resolve_project(root,project_id)
    if not isinstance(query,str): raise ValueError('query must be a string')
    return [e['metadata'] for e in events(p,pid) if query.casefold() in (e['metadata']['title']+' '+e['metadata']['path']+' '+e['metadata']['mimeType']).casefold()]
def register_media(root,project_id,path,expected_version,title=''):
    p,pid=resolve_project(root,project_id)
    marker=p/'.hermespm-project.json'
    if marker.is_symlink() or not marker.is_file(): raise ValueError('project metadata unavailable')
    mdroot, marker_id=root_info(p)
    if marker_id!=pid: raise ValueError('registered project metadata ID mismatch')
    path=safe_path(path)
    if type(expected_version) is not int or expected_version<0 or not isinstance(title,str): raise ValueError('invalid expected_version/title')
    f=p/path
    if f.is_symlink(): raise ValueError('media symlink rejected')
    resolved=f.resolve(strict=True)
    if not resolved.is_relative_to(p) or not resolved.is_file(): raise ValueError('media must be an existing project file')
    rows=events(p,pid)
    if len(rows)!=expected_version: raise ValueError('version conflict')
    for e in rows:
        if e['metadata']['path']==path: return e['metadata']
    md={'id':media_id(pid,path),'path':path,'title':title or path.split('/')[-1],'mimeType':{'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','gif':'image/gif','webp':'image/webp'}.get(path.rsplit('.',1)[-1].lower(),'application/octet-stream'),'size':resolved.stat().st_size}
    e={'schema':1,'projectId':pid,'version':expected_version+1,'kind':'media-reference','metadata':md}; data=json.dumps(e,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    dest=p/(PREFIX+f'{expected_version+1:012d}.json'); tmp=p/('.media-catalog-tmp-'+os.urandom(12).hex())
    try:
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
        os.link(tmp,dest,follow_symlinks=False)
    except FileExistsError as ex: raise ValueError('version conflict') from ex
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass
    return md

# Metadata updates are append-only events; schema-1 media-reference events remain replayable.
MEDIA_FIELDS = {'title', 'description', 'tags', 'association', 'captions', 'attribution', 'original_derived', 'status'}
STATUSES = {'active', 'archived', 'deleted'}

def _validate_patch(patch):
    if not isinstance(patch, dict) or not patch or set(patch) - MEDIA_FIELDS:
        raise ValueError('invalid metadata patch fields')
    for key, value in patch.items():
        if key in {'title','description','association','captions','attribution'} and not isinstance(value, str):
            raise ValueError(f'{key} must be a string')
        if key == 'tags' and (not isinstance(value, list) or any(not isinstance(x,str) for x in value)):
            raise ValueError('tags must be a list of strings')
        if key == 'original_derived' and (not isinstance(value, str) or value not in {'original','derived'}):
            raise ValueError('original_derived must be original or derived')
        if key == 'status' and (not isinstance(value, str) or value not in STATUSES):
            raise ValueError('invalid status')
    return patch

def replay_media(root, project_id):
    p,pid=resolve_project(root,project_id); rows=events(p,pid); state={}
    for e in rows:
        md=e['metadata']
        if e['kind']=='media-reference':
            if md['id'] in state: raise ValueError('duplicate media reference')
            state[md['id']]=dict(md, description='', tags=[], association='', captions='', attribution='', original_derived='original', status='active')
        elif e['kind']=='media-external-reference':
            if md['id'] in state: raise ValueError('duplicate media reference')
            state[md['id']]=dict(md, description='', tags=[], association='', captions='', attribution='', original_derived='original', status='active')
        elif e['kind']=='media-external-reconnect':
            if md['id'] not in state: raise ValueError('reconnect references unknown media')
            prior=state[md['id']]
            if 'folderId' not in prior: raise ValueError('reconnect target is not external media')
            prior.update({'folderId':md['folderId'],'relativePath':md['relativePath'],'size':md['size']})
        elif e['kind']=='media-metadata-update':
            target=md.get('media_id'); patch=_validate_patch(md.get('patch'))
            if target not in state: raise ValueError('update references unknown media')
            state[target].update(patch)
        else: raise ValueError('unknown media event kind')
    return list(state.values())

def reconnect_media(root, project_id, media_id_value, folder_id, relative_path, observed_size, expected_version):
    relative_path=safe_path(relative_path)
    if not isinstance(folder_id,str) or not ID.fullmatch(folder_id) or type(observed_size) is not int or observed_size<0: raise ValueError('invalid reconnect grant or size')
    with Store(root) as store:
        pid=store.project()
        if pid!=project_id: raise ValueError('project metadata ID mismatch')
        rows=events_fd(store,pid)
        if expected_version!=len(rows): raise ValueError('version conflict')
        state=replay_rows(rows); target=state.get(media_id_value)
        if not target or 'folderId' not in target: raise ValueError('unknown external media target')
        if target['folderId']==folder_id and target['relativePath']==relative_path: raise ValueError('duplicate reconnect')
        target_path=f'{PREFIX}{expected_version+1:012d}.json'
        event={'schema':1,'projectId':pid,'version':expected_version+1,'kind':'media-external-reconnect','metadata':{'id':media_id_value,'folderId':folder_id,'relativePath':relative_path,'size':observed_size}}
        data=json.dumps(event,separators=(',',':'),ensure_ascii=False).encode(); tmp='.media-catalog-tmp-'+os.urandom(12).hex()
        try:
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,dir_fd=store._dirfd)
            with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
            os.link(tmp,target_path,src_dir_fd=store._dirfd,dst_dir_fd=store._dirfd,follow_symlinks=False); os.fsync(store._dirfd)
        except FileExistsError as ex: raise ValueError('version conflict') from ex
        finally:
            try: os.unlink(tmp,dir_fd=store._dirfd)
            except FileNotFoundError: pass
        return replay_rows(rows+[event])[media_id_value]

def update_media_metadata(root, project_id, media_id_value, expected_version, patch):
    _validate_patch(patch)
    if not isinstance(media_id_value, str): raise ValueError('invalid media id')
    if type(expected_version) is not int: raise ValueError('expected_version must be an integer')
    with Store(root) as store:
        pid=store.project()
        if pid != project_id: raise ValueError('project metadata ID mismatch')
        rows=events_fd(store,pid)
        if expected_version != len(rows) or expected_version >= MAX_VERSION: raise ValueError('version conflict')
        state=replay_rows(rows)
        if media_id_value not in state: raise ValueError('unknown media id')
        version=expected_version+1
        event={'schema':1,'projectId':pid,'version':version,'kind':'media-metadata-update','metadata':{'media_id':media_id_value,'patch':patch}}
        data=json.dumps(event,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
        target=f'{PREFIX}{version:012d}.json'; tmp='.media-catalog-tmp-'+os.urandom(12).hex()
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
            os.link(tmp,target,src_dir_fd=store._dirfd,dst_dir_fd=store._dirfd,follow_symlinks=False)
            os.fsync(store._dirfd)
        except FileExistsError as ex: raise ValueError('version conflict') from ex
        except OSError as ex: raise Conflict('exclusive publication failed') from ex
        finally:
            try: os.unlink(tmp,dir_fd=store._dirfd)
            except FileNotFoundError: pass
        state[media_id_value].update(patch)
        return state[media_id_value]

def events_fd(store,pid):
    names=store._entries(); rows=[]
    for n in names:
        if not n.startswith(PREFIX): continue
        m=re.fullmatch(r'\.media-catalog-event-(\d{12})\.json',n)
        if not m: raise ValueError('malformed media event filename')
        try: e=json.loads(store._read_name(n,1048576).decode('utf-8'))
        except Exception as ex: raise ValueError('unsafe or invalid media event') from ex
        md=e.get('metadata') if isinstance(e,dict) else None
        if set(e)!={'schema','projectId','version','kind','metadata'} or type(e['schema']) is not int or e['schema']!=1 or e['projectId']!=pid or type(e['version']) is not int or e['version']!=int(m.group(1)) or not isinstance(md,dict): raise ValueError('invalid media event')
        if e['kind']=='media-reference':
            if set(md)!={'id','mimeType','path','size','title'} or safe_path(md['path'])!=md['path'] or md['id']!=media_id(pid,md['path']) or type(md['size']) is not int or md['size']<0 or not isinstance(md['title'],str) or not isinstance(md['mimeType'],str): raise ValueError('invalid media reference')
        elif e['kind']=='media-external-reference': _validate_external_reference(md,pid)
        elif e['kind']=='media-external-reconnect':
            if set(md)!={'id','folderId','relativePath','size'} or not isinstance(md['folderId'],str) or not ID.fullmatch(md['folderId']) or safe_path(md['relativePath'])!=md['relativePath'] or type(md['size']) is not int or md['size']<0 or not isinstance(md['id'],str): raise ValueError('invalid media reconnect')
        elif e['kind']=='media-metadata-update':
            if set(md)!={'media_id','patch'} or not isinstance(md['media_id'],str): raise ValueError('invalid metadata update')
            _validate_patch(md['patch'])
        else: raise ValueError('invalid media event kind')
        rows.append(e)
    rows.sort(key=lambda x:x['version'])
    if any(x['version']!=i+1 for i,x in enumerate(rows)): raise ValueError('catalog history conflict')
    return rows

def replay_rows(rows):
    state={}
    for e in rows:
        md=e['metadata']
        if e['kind'] in ('media-reference','media-external-reference'):
            if md['id'] in state: raise ValueError('duplicate media reference')
            state[md['id']]=dict(md,description='',tags=[],association='',captions='',attribution='',original_derived='original',status='active')
        elif e['kind']=='media-external-reconnect':
            if md['id'] not in state: raise ValueError('reconnect references unknown media')
            if 'folderId' not in state[md['id']]: raise ValueError('reconnect target is not external media')
            state[md['id']].update({'folderId':md['folderId'],'relativePath':md['relativePath'],'size':md['size']})
        elif e['kind']=='media-metadata-update':
            if md['media_id'] not in state: raise ValueError('update references unknown media')
            state[md['media_id']].update(md['patch'])
        else: raise ValueError('unknown media event kind')
    return state

def validate_media_history(root, project_id):
    replay_media(root, project_id); return {'valid':True,'version':len(events(resolve_project(root,project_id)[0], project_id))}

def register(ctx):
    def wrap(fn):
        def call(args,**kw):
            try:return json.dumps({'result':fn(**dict(args))},ensure_ascii=False)
            except Exception as ex:return json.dumps({'error':f'{type(ex).__name__}: {ex}'},ensure_ascii=False)
        return call
    for name,fn,props,required,desc in [('project_media_list',list_media,{'root':{'type':'string','description':'Explicit existing absolute project folder'},'project_id':{'type':'string'},'query':{'type':'string'}},['root','project_id'],'List/search media for an explicitly selected project folder whose marker matches project_id. No separate OS sandbox is provided.'),('project_media_register',register_media,{'root':{'type':'string','description':'Explicit existing absolute project folder'},'project_id':{'type':'string'},'path':{'type':'string'},'expected_version':{'type':'integer','minimum':0},'title':{'type':'string'}},['root','project_id','path','expected_version'],'Register media for an explicitly selected project folder whose marker matches project_id.'),('project_media_update_metadata',update_media_metadata,{'root':{'type':'string','description':'Explicit existing absolute project folder'},'project_id':{'type':'string'},'media_id_value':{'type':'string'},'expected_version':{'type':'integer','minimum':0},'patch':{'type':'object'}},['root','project_id','media_id_value','expected_version','patch'],'Append a validated metadata patch at the exact catalog version.')]:
        schema={'type':'object','properties':props,'required':required,'additionalProperties':False}
        ctx.register_tool(name=name,toolset='project_content',schema={'name':name,'description':desc,'parameters':schema},handler=wrap(fn),description=desc)
