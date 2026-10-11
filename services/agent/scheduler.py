import asyncio,json,time
from zoneinfo import ZoneInfo
from .store import uid,dump
from .models import Strict,TaskSpec
from pydantic import Field
from typing import Literal

class Schedule(Strict):
    name: str
    session_id: str
    spec: TaskSpec
    next_run: float
    timezone: str = 'Asia/Shanghai'
    interval_seconds: int | None = Field(default=None,ge=60)
    missed: Literal['skip','once'] = 'skip'
    authorized_until: float
    enabled: bool = True

class Scheduler:
    def __init__(self,store,engine):self.store=store;self.engine=engine;self.worker=None
    def start(self):self.worker=asyncio.create_task(self.work())
    async def close(self):
        if self.worker:self.worker.cancel();await asyncio.gather(self.worker,return_exceptions=True)
    async def work(self):
        while True:
            await self.tick();await asyncio.sleep(2)
    async def tick(self,now=None):
        now=now or time.time()
        for row in self.store.rows('SELECT * FROM schedules WHERE enabled=1 AND next_run<=?',(now,)):
            config=Schedule.model_validate_json(row['config']);ZoneInfo(config.timezone)
            if config.authorized_until<=now:
                self.store.run('UPDATE schedules SET enabled=0 WHERE id=?',(row['id'],));continue
            # Persist advancing the trigger before enqueuing: crash may skip but never replay a side effect.
            next_run=now+config.interval_seconds if config.interval_seconds else row['next_run']
            self.store.run('UPDATE schedules SET next_run=?,enabled=? WHERE id=?',(next_run,int(config.interval_seconds is not None),row['id']))
            if config.missed=='skip' and now-row['next_run']>60:continue
            task_id=uid()
            self.store.run('INSERT INTO tasks VALUES(?,?,?,?,?,?)',(task_id,config.session_id,'planned',dump(config.spec.model_dump()),now,now))
            self.store.event(task_id,'scheduled',{'schedule_id':row['id'],'name':config.name,'timezone':config.timezone,'detail':'调度授权只允许入队；实际工具仍按任务策略逐次校验。'})
            await self.engine.enqueue(task_id)
