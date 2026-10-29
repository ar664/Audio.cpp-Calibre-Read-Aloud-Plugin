"""Record known model-specific smoke request options for the model matrix."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
reference = str(root / 'validation/model-tests/breeze_tts-offline.wav')
codec = str(root / 'models/MioTTS-1.7B-GGUF/MioCodec-25Hz-44.1kHz-v2')
json.dump({
    'auk': {'config': {'breeze_voice_mode': 'design', 'reference_audio': '', 'reference_text': ''}},
    'dramabox': {'options': {'duration_sec': 3, 'num_inference_steps': 8}},
    'irodori_tts': {'config': {'breeze_instruction': '', 'language': 'ja'}},
    'lfm2_audio': {'config': {'language': 'ja'}, 'options': {'language': 'ja'}},
    'miotts': {'model': {'session_options': {'miotts.codec_model_path': codec}}},
    'outetts': {'options': {'max_tokens': 4096}},
    'omnivoice': {'config': {'language': 'en'}},
    'pocket_tts': {'package': 'pocket_tts_english_q8_0', 'config': {'language': 'en'}},
    'vevo2': {'options': {'route': 'zero_shot_tts', 'target_voice': reference}},
    'vibevoice': {'config': {'breeze_voice_mode': 'design', 'reference_audio': '', 'reference_text': ''},
                  'text': 'Speaker 1: Hello. This is a short reading test.'},
}, (root / 'validation/model-tests/overrides.json').open('w', encoding='utf-8'), indent=2)
