"""Persistent lesson outcomes and FSRS recall. No model output is executed as code."""
import json
import re
import uuid
from datetime import datetime, timezone, timedelta, date
from fsrs import Card, Rating, Scheduler


def now():
    return datetime.now(timezone.utc)


def parse_pack(text, allowed):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError()
        summary = value['summary']
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 12000:
            raise ValueError()
        cards = value['cards']
        if not isinstance(cards, list) or not 1 <= len(cards) <= 10:
            raise ValueError()
        clean = []
        for card in cards:
            if card.get('kind') not in ('recall', 'exercise'):
                raise ValueError()
            if not all(isinstance(card.get(k), str) and 1 <= len(card[k].strip()) <= 4000 for k in ('question', 'answer')):
                raise ValueError()
            ids = card.get('source_ids')
            if not isinstance(ids, list) or not ids or any(i not in allowed for i in ids):
                raise ValueError()
            clean.append({k: card[k] for k in ('kind', 'question', 'answer', 'source_ids')})
        if not {'recall', 'exercise'} <= {c['kind'] for c in clean}:
            raise ValueError()
        summary = re.sub(r'\[([a-f0-9]{10}-\d+)\]', lambda m: m[0] if m[1] in allowed else '[来源未核实]', summary)
        return {'summary': summary, 'cards': clean}
    except (KeyError, TypeError, ValueError):
        raise ValueError('AI 整理格式或教材引用不完整，未保存，请重试。')


class LearningMixin:
    def init_learning(self):
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS lesson_turns(id TEXT PRIMARY KEY,task_id TEXT,role TEXT,text TEXT,created TEXT);
            CREATE INDEX IF NOT EXISTS turns_task ON lesson_turns(task_id);
            CREATE TABLE IF NOT EXISTS lesson_packs(task_id TEXT PRIMARY KEY,summary TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS recall_cards(id TEXT PRIMARY KEY,task_id TEXT,plan_id TEXT,kind TEXT,
              question TEXT,answer TEXT,source_ids TEXT,fsrs TEXT,due TEXT,reviews INTEGER DEFAULT 0,last_rating INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS cards_plan_due ON recall_cards(plan_id,due);
            CREATE TABLE IF NOT EXISTS recall_reviews(id TEXT PRIMARY KEY,card_id TEXT,plan_id TEXT,answer TEXT,
              rating INTEGER,feedback TEXT,created TEXT,fsrs_log TEXT);
            ''')

    def record_turn(self, tid, role, text):
        self.task(tid)
        if role not in ('user', 'assistant') or not text.strip():
            return
        with self.connect() as c:
            c.execute('INSERT INTO lesson_turns VALUES(?,?,?,?,?)', (uuid.uuid4().hex, tid, role, text[:12000], now().isoformat()))

    def lesson_result(self, tid):
        self.task(tid)
        with self.connect() as c:
            pack = c.execute('SELECT * FROM lesson_packs WHERE task_id=?', (tid,)).fetchone()
            turns = list(c.execute('SELECT role,text,created FROM lesson_turns WHERE task_id=? ORDER BY rowid DESC LIMIT 60', (tid,)))
            cards = list(c.execute('SELECT id,kind,question FROM recall_cards WHERE task_id=? ORDER BY rowid', (tid,)))
        return {'pack': dict(pack) if pack else None, 'turns': [dict(r) for r in reversed(turns)], 'cards': [dict(r) for r in cards]}

    def save_pack(self, tid, pack, update_summary=False):
        task = self.task(tid)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM lesson_packs WHERE task_id=?', (tid,)).fetchone():
                if update_summary:
                    c.execute('UPDATE lesson_packs SET summary=?,created=? WHERE task_id=?', (pack['summary'], now().isoformat(), tid))
                return False
            c.execute('INSERT INTO lesson_packs VALUES(?,?,?)', (tid, pack['summary'], now().isoformat()))
            for item in pack['cards']:
                card = Card(card_id=uuid.uuid4().int >> 64)
                c.execute('INSERT INTO recall_cards(id,task_id,plan_id,kind,question,answer,source_ids,fsrs,due) VALUES(?,?,?,?,?,?,?,?,?)',
                          (uuid.uuid4().hex, tid, task['plan_id'], item['kind'], item['question'], item['answer'], json.dumps(item['source_ids']), card.to_json(), card.due.isoformat()))
        return True

    def cards(self, pid, scope='due'):
        with self.connect() as c:
            condition = ' AND r.due<=?' if scope == 'due' else ' AND r.last_rating IN (1,2)' if scope == 'weak' else ''
            args = [pid, now().isoformat()] if scope == 'due' else [pid]
            rows = c.execute('SELECT r.id,r.task_id,r.kind,r.question,r.due,r.reviews,r.last_rating,t.title FROM recall_cards r JOIN tasks t ON t.id=r.task_id WHERE r.plan_id=?' + condition + ' ORDER BY r.due,r.rowid LIMIT 100', args)
            return [dict(r) for r in rows]

    def card(self, cid):
        with self.connect() as c:
            row = c.execute('SELECT * FROM recall_cards WHERE id=?', (cid,)).fetchone()
        if not row:
            raise ValueError('复习卡片不存在。')
        card = dict(row)
        card['source_ids'] = json.loads(card['source_ids'])
        return card

    def review_card(self, cid, rating, answer, feedback='', expected_due=None):
        if type(rating) is not int or rating not in (1, 2, 3, 4):
            raise ValueError('请评价本次回忆：忘记、困难、记得或轻松。')
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 8000:
            raise ValueError('先写下自己的答案；想不起来也可以如实填写。')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM recall_cards WHERE id=?', (cid,)).fetchone()
            if not row:
                raise ValueError('复习卡片不存在。')
            if not expected_due or row['due'] != expected_due:
                raise ValueError('此卡片已更新，请刷新复习列表，避免重复记录。')
            updated, log = Scheduler(enable_fuzzing=False).review_card(Card.from_json(row['fsrs']), Rating(rating))
            c.execute('UPDATE recall_cards SET fsrs=?,due=?,reviews=reviews+1,last_rating=? WHERE id=?', (updated.to_json(), updated.due.isoformat(), rating, cid))
            c.execute('INSERT INTO recall_reviews VALUES(?,?,?,?,?,?,?,?)', (uuid.uuid4().hex, cid, row['plan_id'], answer.strip(), rating, feedback[:12000], now().isoformat(), log.to_json()))
        return {'due': updated.due.isoformat()}

    def progress(self, pid):
        plan = self.plan(pid) if pid else None
        if not plan:
            return None
        tasks = plan['tasks']
        lessons = [t for t in tasks if t['kind'] == 'lesson']
        with self.connect() as c:
            cards = list(c.execute('SELECT reviews,last_rating,due FROM recall_cards WHERE plan_id=?', (pid,)))
            logs = [dict(r) for r in c.execute('SELECT r.*,c.question,t.title FROM recall_reviews r JOIN recall_cards c ON c.id=r.card_id JOIN tasks t ON t.id=c.task_id WHERE r.plan_id=? ORDER BY r.rowid DESC', (pid,))]
            packs = c.execute('SELECT count(*) FROM lesson_packs p JOIN tasks t ON p.task_id=t.id WHERE t.plan_id=?', (pid,)).fetchone()[0]
        today = date.today()
        activity = {}
        for task in tasks:
            if task['status'] == 'done':
                activity[task['completed']] = activity.get(task['completed'], 0) + 1
        for log in logs:
            day = datetime.fromisoformat(log['created']).astimezone().date().isoformat()
            activity[day] = activity.get(day, 0) + 1
        streak, cursor = 0, today if today.isoformat() in activity else today - timedelta(days=1)
        while cursor.isoformat() in activity:
            streak += 1
            cursor -= timedelta(days=1)
        recent = [log for log in logs if datetime.fromisoformat(log['created']) >= now()-timedelta(days=7)]
        return {'lessons_total': len(lessons), 'lessons_done': sum(t['status']=='done' for t in lessons),
                'packs': packs, 'cards_total': len(cards), 'cards_due': sum(r['due']<=now().isoformat() for r in cards),
                'weak': sum(r['last_rating'] in (1,2) for r in cards), 'unreviewed': sum(r['reviews']==0 for r in cards),
                'recent_recall_rate': round(100*sum(r['rating']>=3 for r in recent)/len(recent)) if recent else None,
                'recent_reviews': len(recent), 'streak': streak,
                'days': [{'date': (today-timedelta(days=i)).isoformat(), 'count': activity.get((today-timedelta(days=i)).isoformat(),0)} for i in reversed(range(14))],
                'history': logs[:30]}

    def learning_export(self, pid):
        plan = self.plan(pid)
        if not plan:
            raise ValueError('课程不存在。')
        parts = ['# '+plan['config']['subject'], 'AI 生成内容与参考答案请结合所列教材核对。']
        for task in plan['tasks']:
            result = self.lesson_result(task['id'])
            if result['pack']:
                parts += ['## '+task['title'], result['pack']['summary']]
        with self.connect() as c:
            all_cards = list(c.execute('SELECT id FROM recall_cards WHERE plan_id=? ORDER BY rowid', (pid,)))
        for item in all_cards:
            card = self.card(item['id'])
            parts += ['### '+card['question'], card['answer'], '来源：'+', '.join(card['source_ids'])]
        with self.connect() as c:
            notes = list(c.execute('SELECT n.text,t.title FROM notes n JOIN tasks t ON n.task_id=t.id WHERE t.plan_id=? ORDER BY n.rowid', (pid,)))
        for note in notes:
            parts += ['## 笔记 · '+note['title'], note['text']]
        with self.connect() as c:
            all_logs = list(c.execute('SELECT r.*,c.question FROM recall_reviews r JOIN recall_cards c ON c.id=r.card_id WHERE r.plan_id=? ORDER BY r.rowid', (pid,)))
        for log in all_logs:
            parts += ['### 我的作答 · '+log['question'], log['answer'], log['feedback'], '回忆自评：'+str(log['rating'])+' / 4 · '+log['created']]
        return '\n\n'.join(parts)
