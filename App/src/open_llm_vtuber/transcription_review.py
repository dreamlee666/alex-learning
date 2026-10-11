"""One-use, expiring review tickets. Approval is separate from ASR and inference."""
import secrets
import time


class TranscriptionReview:
    def __init__(self):
        self.pending = {}

    def offer(self, client, text):
        ticket = secrets.token_urlsafe(18)
        self.pending[client] = (ticket, time.monotonic() + 1800)
        return {'type': 'transcription-review', 'request_id': ticket, 'text': text}

    def accept(self, client, ticket, text, cancel=False):
        pending = self.pending.get(client)
        if not pending or not secrets.compare_digest(str(ticket), pending[0]) or pending[1] < time.monotonic():
            raise ValueError('转写确认已失效，请重新录音。')
        if cancel:
            self.pending.pop(client, None)
            return None
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ValueError('请填写 1–8000 字符的转写内容。')
        self.pending.pop(client, None)
        return text.strip()

    def clear(self, client):
        self.pending.pop(client, None)
