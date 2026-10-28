import os
import sys
import base64
import runpod

# Путь к модулю KazEmoTTS
sys.path.insert(0, '/app/KazEmoTTS')
try:
    from engine import synthesize_speech
except ImportError:
    # Запасной импорт, если скрипт в корне
    try:
        from KazEmoTTS.engine import synthesize_speech
    except Exception as e:
        print(f"Import error: {e}")

def handler(event):
    job_input = event.get('input', {})
    text = job_input.get('text', '')
    speaker = int(job_input.get('speaker', 2))
    speed = float(job_input.get('speed', 1.0))
    steps = int(job_input.get('steps', 100))

    if not text:
        return {'error': 'Text is empty'}

    output_path = '/tmp/output.wav'
    if os.path.exists(output_path):
        os.remove(output_path)

    try:
        synthesize_speech(text, speaker=speaker, speed=speed, steps=steps, output_path=output_path)
    except Exception as e:
        return {'error': f'Inference error: {str(e)}'}

    if not os.path.exists(output_path):
        return {'error': 'Failed to generate audio file'}

    with open(output_path, 'rb') as f:
        audio_b64 = base64.b64encode(f.read()).decode('utf-8')

    return {'audio_base64': audio_b64}

if __name__ == '__main__':
    runpod.serverless.start({'handler': handler})
