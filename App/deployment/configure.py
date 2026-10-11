from pathlib import Path
import copy
import json
import secrets
import yaml
from teaching import GENERAL_PERSONA, SQE_PERSONA

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT / 'deployment' / 'runtime.json'
if not runtime.exists():
    runtime.write_text(json.dumps({'gateway_key': secrets.token_urlsafe(32)}), encoding='utf-8')
local_key = json.loads(runtime.read_text(encoding='utf-8'))['gateway_key']
config = yaml.safe_load((ROOT / 'config_templates' / 'conf.default.yaml').read_text(encoding='utf-8'))
config['system_config'].update(host='127.0.0.1', port=32193, config_alts_dir='classroom_characters')
character = config['character_config']
character.update(conf_name='通用学习 · 苏格拉底课堂', conf_uid='general_learning_tutor_v1',
                 character_name='Alex · Learning Companion', human_name='Learner', avatar='mao.png')
character['persona_prompt'] = GENERAL_PERSONA
agent = character['agent_config']
agent['agent_settings']['basic_memory_agent'].update(llm_provider='openai_compatible_llm', use_mcpp=False, mcp_enabled_servers=[])
agent['llm_configs']['openai_compatible_llm'].update(base_url='http://127.0.0.1:32194/v1', llm_api_key=local_key,
    model='account-selected', organization_id=None, project_id=None, temperature=0.7)
asr = character['asr_config']
asr['asr_model'] = 'faster_whisper'
asr['faster_whisper'].update(model_path='models/whisper-small', download_root='models/whisper', language=None, device='cpu', compute_type='int8', prompt='Educational conversation in English or Chinese.', hotwords='')
character['tts_config']['tts_model'] = 'openai_tts'
character['tts_config']['openai_tts'].update(model='kokoro-local-youthful', voice='youthful',
    api_key=local_key, base_url='http://127.0.0.1:32195/v1', file_extension='wav')
character['vad_config']['vad_model'] = None
def write(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
write(ROOT / 'conf.yaml', config)
alternatives = ROOT / 'classroom_characters'
alternatives.mkdir(exist_ok=True)
sqe = copy.deepcopy(config)
sqe['character_config'].update(conf_name='SQE · 法律英语（可选）', conf_uid='sqe_english_tutor_v1')
sqe['character_config']['persona_prompt'] += SQE_PERSONA
write(alternatives / 'sqe-english.yaml', sqe)
simulation = copy.deepcopy(config)
simulation['character_config'].update(conf_name='SQE2 · 客户访谈模拟', conf_uid='sqe2_interview_v1')
simulation['character_config']['persona_prompt'] += SQE_PERSONA + '''\nIn this profile start in SQE2 client-interview roleplay. Ask the learner to choose Property Practice or Wills and the Administration of Estates, then agree on a short illustrative client scenario. Play a client with an invented name and ordinary concerns. Only switch to tutor feedback when asked to finish or review. Do not portray the simulation as an official assessment.'''
write(alternatives / 'sqe2-interview.yaml', simulation)
(ROOT / 'materials').mkdir(exist_ok=True)
print('Classroom configuration prepared; no external credentials stored in source.')
