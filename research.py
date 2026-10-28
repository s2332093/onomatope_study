"""Name registration, signed learner sessions, and private researcher reports."""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urlsplit
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
import study_logging

REQUIRE_NAME = os.environ.get('STUDY_REQUIRE_NAME', '1') != '0'
ADMIN_USER = os.environ.get('STUDY_ADMIN_USER', 'researcher')
ADMIN_PASSWORD = os.environ.get('STUDY_ADMIN_PASSWORD', '')
SECRET = os.environ.get('STUDY_SESSION_SECRET') or ADMIN_PASSWORD or secrets.token_hex(32)
COOKIE = 'study_session'
ADMIN_COOKIE = 'study_research_login'
_login_attempts = {}


def sign(participant):
    return participant + '.' + hmac.new(SECRET.encode(), participant.encode(), hashlib.sha256).hexdigest()


def identity(request):
    token = request.cookies.get(COOKIE, '')
    participant, _, signature = token.partition('.')
    return participant if signature and hmac.compare_digest(sign(participant), token) else None


def safe_next(value, prefix):
    return value if value.startswith(prefix + '/') and not value.startswith('//') and '\\' not in value and not any(ord(c)<32 for c in value) else prefix + '/'


def same_origin(request):
    origin=request.headers.get('origin')
    if not origin:
        return True
    parsed=urlsplit(origin)
    # A trusted hosting proxy may terminate HTTPS before the ASGI server.
    return parsed.scheme in ('http','https') and parsed.netloc==request.url.netloc and parsed.path in ('','/')


def secure_cookie(request):
    return request.url.scheme=='https' or request.headers.get('x-forwarded-proto','').split(',')[0].strip()=='https'


def private(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def allowed(request):
    if not ADMIN_PASSWORD:
        return private(HTMLResponse('研究者画面は未設定です。保存先と閲覧用パスワードを設定してください。', status_code=503))
    token = request.cookies.get(ADMIN_COOKIE,'')
    expires, _, signature = token.partition('.')
    expected = hmac.new(SECRET.encode(), ('research:' + expires).encode(), hashlib.sha256).hexdigest()
    if expires.isdigit() and int(expires)>time.time() and hmac.compare_digest(signature,expected):
        return None
    try:
        user, password = base64.b64decode(request.headers.get('authorization', '').split(' ',1)[1], validate=True).decode().split(':',1)
    except (ValueError, IndexError, UnicodeError):
        user = password = ''
    if not (hmac.compare_digest(user.encode(), ADMIN_USER.encode()) and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())):
        return private(HTMLResponse('研究者用の認証が必要です。<a href="'+request.scope.get('study_prefix','/a')+'/research/login">ログインへ</a>',status_code=401))
    return None


def jst(value):
    try:
        return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=9))).strftime('%Y/%m/%d %H:%M:%S')
    except (ValueError, AttributeError):
        return value


def empty():
    return dict(active_ms=0, visits=0, attempts=0, correct=0, incorrect=0,
                items=0, item_correct=0, item_wrong=0, clicks=0, last='')


def score(detail):
    if isinstance(detail.get('correct'), bool):
        return [detail['correct']]
    for field in ('correct_by_expression','correct_by_question'):
        if isinstance(detail.get(field), dict):
            return [v for v in detail[field].values() if isinstance(v,bool)]
    return []


def page_label(path):
    # Resolve teaching labels only while serving reports, after main has loaded.
    import main
    parts = path.strip('/').split('/')
    if parts and parts[0] in ('a','b'):
        parts = parts[1:]
    if not parts or parts==['']:
        return 'ホーム：語の選択'
    if parts[0]=='registration':
        return '名前の登録'
    if parts[0]=='reference':
        return '学習前の知識'
    if parts[0]=='drill':
        return ('素性ドリル' if len(parts)>1 and parts[1]=='features' else '前接条件ドリル') + ('：フィードバック' if parts[-1]=='check' else '')
    if parts[0]=='word' and len(parts)>1:
        word=main.WORD_BY_ID.get(parts[1],{}).get('word',parts[1])
        suffix='学習マップ'
        if len(parts)>2:
            stage=parts[2]
            if stage=='f1' and len(parts)>3:
                suffix = '素性学習のまとめ' if parts[3]=='done' else {'1':'意味','2':'音の形','3':'継続性','4':'動作性','5':'意志性'}.get(parts[3],'素性学習')
            else:
                suffix={'meaning':'意味','f2':'線結び','f3':'文脈練習','complete':'学習完了'}.get(stage,stage)
        return word+'：'+suffix+('：フィードバック' if parts[-1]=='check' else '')
    return path


def answer_label(answers,path):
    import main
    result=[]
    for key,value in answers.items():
        if key.startswith(('opt_keys_','spec_')):
            continue
        label = '解答' if key=='choice' else ('問'+key[7:] if key.startswith('choice_') else main.EXPR_BY_KEY.get(key,{}).get('label',key))
        if value in main.WORD_BY_ID:
            item=main.WORD_BY_ID[value]
            value=item['meaning'] if '/f1/1' in path or '/meaning' in path else item['word']
        elif value in main.EXPR_BY_KEY:
            value=main.EXPR_BY_KEY[value]['label']
        elif value in main.PHON_BY_KEY:
            value=main.PHON_BY_KEY[value]['label']
        result.append(label+'：'+str(value))
    return ' ／ '.join(result)


def report(participant=None, group=None):
    with study_logging.connect() as db:
        names = {r[0]:dict(name=r[1], started=r[2]) for r in db.execute('SELECT * FROM participants')}
        query = 'SELECT * FROM events'
        conditions, params = [], []
        if participant:
            conditions.append('participant_id=?'); params.append(participant)
        if group:
            conditions.append('study_group=?'); params.append(group)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        events = list(db.execute(query + ' ORDER BY server_time', params))
    people, pages, visits, attempts = {}, {}, {}, []
    for event in events:
        eid, pid, grp, server, client, page_id, path, kind, elapsed, raw = event
        data = json.loads(raw)
        key = (pid, grp)
        person = people.setdefault(key, dict(participant_id=pid, group=grp, name=names.get(pid,{}).get('name','（名前登録前）'), **empty()))
        person['last'] = server
        # Answer POSTs belong to their source page, not the feedback/redirect URL.
        source = data.get('source_path') if kind == 'answer_submission' else path
        source = source or path
        page = pages.setdefault((pid, grp, source), dict(participant_id=pid, group=grp, name=person['name'], path=source, page_label=page_label(source), **empty()))
        page['last'] = server
        if page_id:
            visit = visits.setdefault((pid,grp,page_id,source), dict(active_ms=0,clicks=0))
            try:
                active = max(0, min(float(data.get('active_ms',0)), float(elapsed or 0)))
                visit['active_ms'] = max(visit['active_ms'], active)
                visit['clicks'] = max(visit['clicks'], int(data.get('click_count',0)))
            except (TypeError,ValueError):
                pass
        values = score(data) if kind == 'answer_submission' else []
        if values:
            for target in (person,page):
                target['attempts'] += 1
                target['correct'] += int(all(values))
                target['incorrect'] += int(not all(values))
                target['items'] += len(values)
                target['item_correct'] += sum(values)
                target['item_wrong'] += len(values)-sum(values)
            attempts.append(dict(event_id=eid,participant_id=pid,name=person['name'],group=grp,
                time=jst(server),path=source,page_label=page_label(source),answer_label=answer_label(data.get('answers',{}),source),correct=all(values),correct_items=sum(values),
                wrong_items=len(values)-sum(values),answers=json.dumps(data.get('answers',{}),ensure_ascii=False),
                details=json.dumps({k:v for k,v in data.items() if k.startswith('correct')},ensure_ascii=False)))
    for (pid,grp,page_id,path), value in visits.items():
        for target in (people[(pid,grp)],pages[(pid,grp,path)]):
            target['visits'] += 1
            target['active_ms'] += value['active_ms']
            target['clicks'] += value['clicks']
    for row in [*people.values(),*pages.values()]:
        row['seconds'] = round(row['active_ms']/1000,1)
        row['rate'] = round(100*row['correct']/row['attempts'],1) if row['attempts'] else None
        row['wrong_rate'] = round(100*row['incorrect']/row['attempts'],1) if row['attempts'] else None
        row['item_rate'] = round(100*row['item_correct']/row['items'],1) if row['items'] else None
        row['last_jst'] = jst(row['last'])
    return dict(people=list(people.values()),pages=list(pages.values()),attempts=attempts,events=events)


def csv_response(rows, columns, filename):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow([title for key,title in columns])
    def safe(value):
        # Prevent user-entered names/form values from executing as spreadsheet formulas.
        value = '' if value is None else str(value)
        return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
    for row in rows:
        writer.writerow([safe(row.get(key,'')) for key,title in columns])
    return private(Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition':f'attachment; filename="{filename}"'}))

SUMMARY = [('participant_id','参加ID'),('name','名前'),('group','群'),('seconds','使用時間（秒・表示中のみ）'),
    ('visits','ページ訪問数'),('attempts','回答回数'),('correct','全問正解の回答回数'),('incorrect','誤答した回答回数'),
    ('rate','回答単位の正解率（%）'),('wrong_rate','回答単位の不正解率（%）'),('items','項目判断数'),
    ('item_correct','正解項目数'),('item_wrong','誤答項目数'),('item_rate','項目正解率（%）'),('clicks','クリック数'),('last_jst','最終記録（日本時間）')]


def install(app, templates):
    @app.get('/registration', response_class=HTMLResponse)
    async def registration(request: Request):
        prefix = request.scope['study_prefix']
        return private(templates.TemplateResponse(request,'registration.html',dict(
            next=safe_next(request.query_params.get('next',''),prefix), error=None)))

    @app.post('/registration')
    async def registration_save(request: Request):
        import uuid
        prefix = request.scope['study_prefix']
        if not same_origin(request):
            return Response(status_code=403)
        form = await request.form()
        name = ' '.join(str(form.get('name','')).split())
        target = safe_next(str(form.get('next','')),prefix)
        if not name or len(name)>80:
            return private(templates.TemplateResponse(request,'registration.html',dict(next=target,error='名前を1〜80文字で入力してください。'),status_code=400))
        pid = str(uuid.uuid4())
        study_logging.register(pid,name)
        response = private(RedirectResponse(target,status_code=303))
        response.set_cookie(COOKIE,sign(pid),httponly=True,samesite='lax',secure=secure_cookie(request),max_age=60*60*24*30)
        return response

    @app.get('/research/login',response_class=HTMLResponse)
    async def research_login(request: Request):
        return private(templates.TemplateResponse(request,'research_login.html',dict(error=None)))

    @app.post('/research/login')
    async def research_login_save(request: Request):
        prefix = request.scope['study_prefix']
        if not same_origin(request):
            return Response(status_code=403)
        if not ADMIN_PASSWORD:
            return private(HTMLResponse('研究者画面のパスワードが未設定です。',status_code=503))
        address = request.client.host if request.client else 'unknown'
        recent = [t for t in _login_attempts.get(address,[]) if t>time.time()-900]
        if len(recent)>=20:
            return private(HTMLResponse('試行回数が多いため、15分後にもう一度お試しください。',status_code=429))
        form = await request.form()
        if not hmac.compare_digest(str(form.get('password','')).encode(),ADMIN_PASSWORD.encode()):
            _login_attempts[address] = recent + [time.time()]
            return private(templates.TemplateResponse(request,'research_login.html',dict(error='パスワードを確認してください。'),status_code=401))
        _login_attempts.pop(address,None)
        expires = str(int(time.time()+8*60*60))
        token = expires + '.' + hmac.new(SECRET.encode(),('research:'+expires).encode(),hashlib.sha256).hexdigest()
        response = private(RedirectResponse(prefix+'/research',status_code=303))
        response.set_cookie(ADMIN_COOKIE,token,httponly=True,samesite='strict',secure=secure_cookie(request),max_age=8*60*60,path=prefix+'/research')
        return response

    @app.post('/research/logout')
    async def research_logout(request: Request):
        prefix = request.scope['study_prefix']
        response = private(RedirectResponse(prefix+'/research/login',status_code=303))
        response.delete_cookie(ADMIN_COOKIE,path=prefix+'/research')
        return response

    @app.get('/research',response_class=HTMLResponse)
    async def research_dashboard(request: Request):
        denied = allowed(request)
        if denied is not None:
            return denied
        pid = request.query_params.get('participant') or None
        group = request.query_params.get('group') or None
        data = report(pid, group)
        data.update(selected=pid,group=group,remote=bool(study_logging.DATABASE_URL),
                    query=urlencode({k:v for k,v in [('participant',pid),('group',group)] if v}))
        return private(templates.TemplateResponse(request,'research.html',data))

    @app.get('/research/export/{kind}')
    async def research_export(request: Request, kind: str):
        denied = allowed(request)
        if denied is not None:
            return denied
        data = report(request.query_params.get('participant') or None,request.query_params.get('group') or None)
        if kind in ('people','pages'):
            columns = SUMMARY + ([('page_label','ページ名'),('path','ページURL')] if kind=='pages' else [])
            return csv_response(data[kind], columns, 'study_'+kind+'.csv')
        if kind=='attempts':
            return csv_response(data[kind],[(k,v) for k,v in [('event_id','回答ID'),('participant_id','参加ID'),('name','名前'),('group','群'),('time','提出時刻（日本時間）'),('page_label','ページ名'),('path','ページURL'),('correct','全問正解'),('correct_items','正解項目数'),('wrong_items','誤答項目数'),('answers','解答'),('details','項目別正誤')]],'study_attempts.csv')
        if kind=='events':
            keys=['event_id','participant_id','study_group','server_time','client_time','page_id','path','event_type','elapsed_ms','detail']
            return csv_response([dict(zip(keys,row)) for row in data['events']],[(k,k) for k in keys],'study_events.csv')
        return Response(status_code=404)
