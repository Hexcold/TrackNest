
import re
import json
import argparse
from pathlib import Path
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://\S+")
TS_RE = re.compile(r"^\[(\d{2}/\d{2}),\s*(\d{2}:\d{2})\]\s*(.*?):\s*(.*)$")


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if 'youtu' in host:
        return 'youtube'
    if 'kwai' in host:
        return 'kwai'
    return 'other'


def parse_messages(lines):
    messages = []
    current = None
    for raw in lines:
        line = raw.rstrip('\n')
        if not line.strip():
            continue
        m = TS_RE.match(line)
        if m:
            # new message header
            if current:
                messages.append(current)
            date, time, sender, text = m.groups()
            current = {'date': date, 'time': time, 'sender': sender.strip(), 'text': text.strip()}
        else:
            # continuation or standalone line
            if current:
                if current['text']:
                    current['text'] += '\n' + line.strip()
                else:
                    current['text'] = line.strip()
            else:
                # standalone line without header
                messages.append({'date': None, 'time': None, 'sender': None, 'text': line.strip()})
    if current:
        messages.append(current)
    return messages


def extract_links_from_text(text: str):
    return URL_RE.findall(text)


def build_entry(url: str, message: dict) -> dict:
    text_without_url = message['text'].replace(url, '').strip() if message and message.get('text') else ''
    title = text_without_url.split('\n')[0].strip() if text_without_url else '[NOME DA MUSICA]'
    return {
        'plataforma': detect_platform(url),
        'tipo': 'video',
        'autor': '[NOME DO AUTOR]',
        'titulo': title if title else '[NOME DA MUSICA]',
        'url': url
    }


def merge_into_json(json_path: Path, new_entries: list):
    if json_path.exists():
        with json_path.open('r', encoding='utf-8') as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = []
    else:
        existing = []
    existing_urls = {item.get('url') for item in existing if isinstance(item, dict) and item.get('url')}
    added = 0
    for e in new_entries:
        if e['url'] not in existing_urls:
            existing.append(e)
            existing_urls.add(e['url'])
            added += 1
    with json_path.open('w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return added


def main():
    parser = argparse.ArgumentParser(description='Parse texto com links e adicionar em um JSON estruturado')
    parser.add_argument('input', help='Arquivo de texto de entrada')
    parser.add_argument('--json', default='musicas.json', help='Arquivo JSON destino (default: musicas.json)')
    args = parser.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print('Arquivo de entrada não encontrado:', inp)
        return

    lines = inp.read_text(encoding='utf-8').splitlines()
    messages = parse_messages(lines)
    new_entries = []
    for msg in messages:
        urls = extract_links_from_text(msg['text'])
        for url in urls:
            new_entries.append(build_entry(url, msg))

    json_path = Path(args.json)
    added = merge_into_json(json_path, new_entries)
    print(f'Entradas encontradas: {len(new_entries)}. Adicionadas: {added}.')


if __name__ == '__main__':
    main()
