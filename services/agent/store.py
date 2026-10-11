import json, sqlite3, time, uuid
from pathlib import Path
from .models import STATES

def uid(): return uuid.uuid4().hex
def dump(value): return json.dumps(value, ensure_ascii=False)

class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / 'agent.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(Path(__file__).with_name('migration.sql').read_text())
        self.db.commit()

    def run(self, sql, args=()):
        cur = self.db.execute(sql, args)
        self.db.commit()
        return cur

    def rows(self, sql, args=()): return [dict(x) for x in self.db.execute(sql, args)]
    def one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        if row is None: raise KeyError('记录不存在')
        return dict(row)

    def event(self, task, kind, payload):
        return self.run('INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)',
                        (task, kind, dump(payload), time.time())).lastrowid

    def task(self, task_id):
        row = self.one('SELECT * FROM tasks WHERE id=?', (task_id,))
        row['spec'] = json.loads(row['spec'])
        runtime=self.runtime(task_id)
        row['revision']=runtime['revision']
        row['verification']=json.loads(runtime['verification']) if runtime['verification'] else None
        row['needs_recovery']=bool(self.rows("SELECT c.id FROM calls c LEFT JOIN recovery r ON r.call_id=c.id WHERE c.task_id=? AND c.status='interrupted' AND r.call_id IS NULL",(task_id,)))
        return row

    def runtime(self,task_id):
        self.run('INSERT OR IGNORE INTO task_runtime(task_id) VALUES(?)',(task_id,))
        return self.one('SELECT * FROM task_runtime WHERE task_id=?',(task_id,))

    def revise(self,task_id):
        self.runtime(task_id)
        self.run('UPDATE task_runtime SET revision=revision+1,verified_revision=NULL,verification=NULL WHERE task_id=?',(task_id,))
        return self.runtime(task_id)['revision']

    def transition(self, task_id, state, detail=''):
        current = self.task(task_id)['state']
        if state not in STATES[current]: raise ValueError(f'非法状态转换 {current} → {state}')
        self.run('UPDATE tasks SET state=?,updated=? WHERE id=?', (state,time.time(),task_id))
        self.event(task_id,'state',{'state':state,'detail':detail})

    def recover(self):
        for t in self.rows("SELECT id FROM tasks WHERE state IN ('running','verifying','awaiting_approval','waiting_for_user')"):
            self.run("UPDATE tasks SET state='paused' WHERE id=?", (t['id'],))
            self.event(t['id'],'interrupted',{'detail':'服务中断。请审查调用日志后继续；未完成动作不会自动重放。'})
        self.run("UPDATE calls SET status='not_executed',result=? WHERE status='pending'",(dump({'status':'not_executed','error':'服务中断前尚未派发，可以重新请求授权'}),))
        self.run("UPDATE calls SET status='interrupted',result=? WHERE status='running'",(dump({'status':'interrupted','error':'副作用结果不确定，必须审查后选择跳过或明确重试'}),))
        self.run('UPDATE grants SET revoked=1 WHERE scope=?', ('once',))
        self.run("UPDATE model_requests SET status='interrupted' WHERE status='running'")

    def message(self, session, role, content):
        self.run('INSERT INTO messages VALUES(?,?,?,?,?)',(uid(),session,role,content,time.time()))

    def memory(self, scope, content, kind='explicit', source='user', memory_id=None):
        memory_id = memory_id or uid()
        now=time.time()
        old=self.rows('SELECT * FROM memories WHERE id=?',(memory_id,))
        with self.db:
            if old:self.db.execute('INSERT INTO memory_history(memory_id,snapshot,created) VALUES(?,?,?)',(memory_id,dump(old[0]),now))
            self.db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content,scope=excluded.scope,kind=excluded.kind,source=excluded.source,updated=excluded.updated',
                     (memory_id,scope,content,kind,source,now,now))
            self.db.execute('DELETE FROM memory_fts WHERE id=?',(memory_id,))
            self.db.execute('INSERT INTO memory_fts VALUES(?,?)',(memory_id,content))
        return memory_id

    def search_memories(self,q='',scopes=None,limit=50):
        filters=[];args=[]
        if scopes:
            filters.append('scope IN ('+','.join('?' for _ in scopes)+')');args.extend(scopes)
        if q.strip():
            # Quoted literal FTS query, with substring fallback for Chinese token boundaries.
            query='"'+q.strip().replace('"','""')+'"'
            filters.append('(id IN (SELECT id FROM memory_fts WHERE memory_fts MATCH ?) OR instr(lower(content),lower(?))>0)');args.extend([query,q.strip()])
        return self.rows('SELECT * FROM memories'+(' WHERE '+' AND '.join(filters) if filters else '')+' ORDER BY updated DESC LIMIT ?',[*args,limit])
