import json,time
import httpx,keyring
from pydantic import Field
from .models import Strict

class SearchArgs(Strict):
    query:str=Field(min_length=1,max_length=2000)
    count:int=Field(default=5,ge=1,le=10)

async def search(store,args):
    rows=store.rows("SELECT value FROM settings WHERE key='search'")
    if not rows:raise ValueError('未配置搜索 provider；请在扩展设置配置真实搜索 API')
    config=json.loads(rows[0]['value'])
    if not config.get('enabled',True):raise ValueError('搜索 provider 已禁用')
    headers={'Accept':'application/json'}
    if config.get('credential_ref'):
        secret=keyring.get_password('LocalAgent',config['credential_ref'])
        if not secret:raise ValueError('搜索凭据不存在')
        headers[config.get('header','Authorization')]=config.get('prefix','Bearer ')+secret
    async with httpx.AsyncClient(timeout=30) as client:
        r=await client.get(config['url'],params={config.get('query_parameter','q'):args['query'],'count':args['count']},headers=headers)
        r.raise_for_status();data=r.json()
    for key in config.get('results_path','results').split('.'):
        data=data[key]
    if not isinstance(data,list):raise ValueError('搜索 API 返回结果不是列表，请检查 results_path')
    items=[]
    for item in data[:args['count']]:
        items.append({'title':str(item.get(config.get('title_field','title'),'')),
                      'url':str(item[config.get('url_field','url')]),
                      'snippet':str(item.get(config.get('snippet_field','description'),'')),
                      'retrieved':time.time()})
    return {'output':items,'verification':'真实搜索 API 响应；回答引用必须指向相应 URL'}

class EmailArgs(Strict):
    to:list[str]=Field(min_length=1,max_length=10)
    subject:str=Field(min_length=1,max_length=200)
    body:str=Field(max_length=50000)

def send_email(store,args,transport=None):
    rows=store.rows("SELECT value FROM settings WHERE key='email'")
    if not rows or not json.loads(rows[0]['value']).get('enabled'):raise PermissionError('邮箱默认禁用；需用户明确启用并配置')
    config=json.loads(rows[0]['value'])
    from email.message import EmailMessage
    message=EmailMessage();message['From']=config['sender'];message['To']=', '.join(args['to']);message['Subject']=args['subject'];message.set_content(args['body'])
    if transport:
        transport(message);return {'output':'测试传输器已接收邮件；未发送到外部邮箱','test_only':True}
    import smtplib,ssl
    secret=keyring.get_password('LocalAgent',config['credential_ref'])
    if not secret:raise ValueError('邮箱凭据未配置')
    with smtplib.SMTP_SSL(config['host'],int(config.get('port',465)),timeout=30,context=ssl.create_default_context()) as smtp:
        smtp.login(config['username'],secret);rejected=smtp.send_message(message)
    if rejected:raise RuntimeError('部分收件人被拒绝；请人工审查，禁止自动重试发送')
    return {'output':'SMTP 服务器已接受邮件；不代表已送达收件箱','recipients':args['to']}
