"""Encrypted grading receipts and one transactional upload at study completion."""
import base64
import hashlib
import json
import math
import uuid
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import research
import study_logging
import learning_state

_cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256((research.SECRET+':study-log-v3').encode()).digest()))
MAX_BYTES = 8*1024*1024
MAX_RECORDS = 25000
ALLOWED = {'page_view','click','answer_change','submit','page_hidden','page_visible','page_leave',
           'heartbeat','page_snapshot','line_add','line_remove','conditions_toggle','study_finished'}


def receipt(participant, group, path, detail, event_id, page_id, elapsed):
    data = dict(participant_id=participant,study_group=group,path=path,detail=detail,
                event_id=event_id,page_id=page_id,elapsed_ms=elapsed,server_time=study_logging.now())
    return _cipher.encrypt(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()).decode()


def open_receipt(token, participant, group):
    data=json.loads(_cipher.decrypt(token.encode()))
    if data['participant_id']!=participant or data['study_group']!=group:
        raise ValueError('wrong learner/group')
    return data


def batch_records(payload, participant, group, prefix):
    events, receipts=payload.get('events',[]),payload.get('receipts',[])
    if not isinstance(events,list) or not isinstance(receipts,list) or len(events)+len(receipts)>MAX_RECORDS:
        raise ValueError('invalid batch')
    rows=[]
    for event in events:
        if not isinstance(event,dict) or event.get('event_type') not in ALLOWED:
            raise ValueError('invalid event')
        elapsed=float(event.get('elapsed_ms',0))
        detail=event.get('detail',{})
        if not math.isfinite(elapsed) or elapsed<0 or not isinstance(detail,dict):
            raise ValueError('invalid event')
        path=str(detail.get('path',''))[:300]
        if not path.startswith(prefix+'/'):
            raise ValueError('invalid path')
        active=float(detail.get('active_ms',0))
        if not math.isfinite(active) or active<0:
            raise ValueError('invalid time')
        rows.append((participant+':'+group+':'+str(event['event_id'])[:120],participant,group,
                     study_logging.now(),str(event.get('client_time',''))[:40],str(event.get('page_id',''))[:80],
                     path,event['event_type'],elapsed,json.dumps(detail,ensure_ascii=False)))
    for token in receipts:
        if not isinstance(token,str) or len(token)>16000:
            raise ValueError('invalid receipt')
        r=open_receipt(token,participant,group)
        rows.append((r['event_id'],participant,group,r['server_time'],None,r['page_id'],r['path'],
                     'answer_submission',r['elapsed_ms'],json.dumps(r['detail'],ensure_ascii=False)))
    return rows


def install(app, templates):
    @app.get('/finish')
    async def finish_page(request: Request):
        return templates.TemplateResponse(request,'finish.html',{})

    @app.post('/api/events')
    async def old_events(request: Request):
        # Never accept periodic uploads from a previously opened version.
        return JSONResponse({'error':'finish required','message':'学習画面を読み込み直してください。終了時にまとめて保存します。'},status_code=409)

    @app.post('/api/finish')
    async def finish_save(request: Request):
        if not research.same_origin(request):
            return JSONResponse({'error':'invalid origin'},status_code=403)
        raw=await request.body()
        if len(raw)>MAX_BYTES:
            return JSONResponse({'error':'batch too large'},status_code=413)
        try:
            payload=json.loads(raw)
            if payload.get('participant_id')!=request.state.participant:
                return JSONResponse({'error':'participant changed'},status_code=409)
            rows=batch_records(payload,request.state.participant,request.state.study_group,request.scope['study_prefix'])
        except (ValueError,KeyError,TypeError,AttributeError,InvalidToken):
            return JSONResponse({'error':'invalid batch'},status_code=400)
        try:
            await run_in_threadpool(study_logging.save_batch,rows)
        except Exception:
            # Keep browser records intact and allow a retry with identical event IDs.
            return JSONResponse({'error':'save unavailable'},status_code=503)
        return {'saved':len(rows),'completed':True}
