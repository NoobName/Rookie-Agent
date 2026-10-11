from pathlib import Path
from .policy import inside

async def perform_check(tools,task,check,emit):
    kind=check['kind']
    if kind=='manual':return {'status':'manual_required','output':'此项需要用户人工验收，系统未标记通过'}
    if kind=='command':return await tools.command(task['id'],check['argv'],task['spec']['workspace'],check['timeout'],emit)
    path=inside(task['spec']['workspace'],check['path'])
    if not path.is_file():return {'status':'failed','error':'验收文件不存在','path':check['path']}
    if kind=='text_contains':
        if path.stat().st_size>1_000_000:raise ValueError('验收文本超过 1 MB')
        if check['contains'] not in path.read_text('utf-8'):return {'status':'failed','error':'文件中缺少要求的内容','path':check['path']}
    import hashlib
    with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'status':'succeeded','output':'实际文件验收通过','path':check['path'],'sha256':checksum}
