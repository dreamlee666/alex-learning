"""Ordered language runs for bilingual vocabulary pronunciation."""
import re


def speech_runs(text):
    # Match Latin phrases as a whole, including contractions and hyphens.
    # CJK surroundings go to the Chinese voice; a bold English word always
    # goes to the English voice, even inside a Chinese sentence.
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    latin = r"[A-Za-z][A-Za-z0-9]*(?:['’\-][A-Za-z0-9]+)*(?:[ \t]+[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*)*"
    for sentence in re.split(r'(?<=[.!?。！？；;])\s*', text):
        if not re.search(r'[\u3400-\u9fff]', sentence):
            if any(c.isalnum() for c in sentence):
                yield 'en', sentence.strip(' *()（）')
            continue
        start = 0
        for match in re.finditer(latin, sentence):
            before = sentence[start:match.start()].strip(' *()（）,:：，')
            if any(c.isalnum() for c in before):
                yield 'zh', before
            yield 'en', match.group()
            start = match.end()
        after = sentence[start:].strip(' *()（）,:：，')
        if any(c.isalnum() for c in after):
            yield 'zh', after
