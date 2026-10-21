#!/usr/bin/env python3
"""macOS Shortcuts transcript -> explicitly bound VS Code terminal draft.

The worker is launched by gamepad_bridge.py, not in Rhino. Python stdlib only.
Manual dry run: python3 agent_handoff.py --text 'Please inspect these faces'
Terminal send is manual by default; a bound VS Code extension may explicitly enable autoSend.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import voice_protocol as vp

MAX_TRANSCRIPT = 12000


def connection(path=None):
    file = path or vp.CONNECTION
    with open(file, encoding='utf-8') as stream:
        info = json.load(stream)
    if (info.get('host') != '127.0.0.1' or not isinstance(info.get('port'), int)
            or not 1 <= info['port'] <= 65535 or
            not isinstance(info.get('token'), str) or len(info['token']) < 32):
        raise ValueError('Invalid VS Code agent-link.json')
    return info


def request(info, op, payload):
    if op not in ('draft','send','cancel','status'):
        raise ValueError('Unknown operation')
    url = 'http://127.0.0.1:{}/{}'.format(info['port'], op)
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization': 'Bearer ' + info['token'],
        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.load(resp)
        if not result.get('ok'):
            raise RuntimeError('VS Code rejected request')
        return result
    except urllib.error.HTTPError as exc:
        raise RuntimeError('VS Code route returned HTTP {}'.format(exc.code)) from exc


def wait_for_snapshot(request_id, timeout=6):
    path = vp.snapshot_path(request_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(path, encoding='utf-8') as f:
                result = json.load(f)
            if result.get('voice_request_id') == request_id:
                return result['basket']
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        time.sleep(0.08)
    raise RuntimeError('Rhino did not respond to voice request; is the current Rhino listener active?')


def shortcut_transcript(name):
    """Shortcut must finish with Stop and Output(Dictated Text)."""
    fd, tmp = tempfile.mkstemp(prefix='rhino_dictation_', suffix='.txt')
    os.close(fd)
    try:
        # No shell, and no user-supplied command. macOS displays its Dictate Text UI.
        proc = subprocess.run(['shortcuts','run',name,'-o',tmp], capture_output=True,
                              text=True, timeout=180, check=False)
        if proc.returncode:
            raise RuntimeError('Shortcuts failed (exit {}). Check its Dictate Text action and microphone permission.'.format(proc.returncode))
        with open(tmp, encoding='utf-8') as f:
            transcript = f.read().strip()
        if not transcript:
            raise RuntimeError('Shortcut produced no transcript (use Stop and Output).')
        return transcript
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def status(request_id, phase, detail=''):
    vp.atomic_json(vp.status_path(request_id), {'id': request_id, 'phase': phase, 'detail': detail[:150]})


def make_prompt(transcript, basket):
    clean = ' '.join(transcript.replace('\x00',' ').split()).strip()
    if not clean or len(clean) > MAX_TRANSCRIPT:
        raise ValueError('Transcript empty or too long')
    items = basket.get('selection_items', [])
    out = ['Voice instruction:', clean, '',
           'Rhino Gamepad Selection Basket (request-scoped snapshot, not entire Rhino selection):',
           'Units: {}'.format(basket.get('units','unknown')),
           'Basket count: {}'.format(len(items))]
    for i, item in enumerate(items[:200], 1):
        out.append('{}. {} ({}), kind={}, index={}, layer={}'.format(
            i, item.get('id','?'), item.get('name',''), item.get('kind','?'),
            item.get('index',-1), item.get('layer','')))
    if len(items) > 200:
        out.append('... remaining items omitted; read local snapshot with MCP integration.')
    out.extend(['',
        'Use your existing Rhino MCP connection to resolve IDs and validate subobject indices before changing geometry.',
        'This is metadata only, not a 3DM file. Ask before destructive or irreversible changes.'])
    return '\n'.join(out)


def do_draft(request_id, transcript=None, shortcut='Rhino Agent Dictate'):
    status(request_id, 'preparing')
    basket = wait_for_snapshot(request_id)
    info = connection()  # fail BEFORE recording if no VS Code terminal bound
    request(info, 'status', {})
    status(request_id, 'recording')
    if transcript is None:
        transcript = shortcut_transcript(shortcut)
    prompt = make_prompt(transcript, basket)
    response = request(info, 'draft', {'id': request_id, 'prompt': prompt})
    if response.get('state') == 'sent':
        status(request_id, 'sent', 'Already delivered earlier; not submitted again.')
        return response
    if response.get('state') != 'ready':
        raise RuntimeError('Draft is no longer available: {}'.format(response.get('state')))
    if info.get('autoSend') is True:
        status(request_id, 'sending', 'Auto-send enabled in VS Code Agent Link.')
        sent = request(info, 'send', {'id': request_id})
        if sent.get('state') != 'sent':
            raise RuntimeError('Agent terminal did not accept the prompt: {}'.format(sent.get('state')))
        status(request_id, 'sent', 'Handed to bound terminal (execution by agent is not verified).')
        print('Voice prompt handed to VS Code terminal (automatic).', flush=True)
        return sent
    status(request_id, 'ready', 'Press gamepad A to send to bound terminal, B to cancel.')
    print('Voice draft ready: {} characters. Press A to send.'.format(len(prompt)), flush=True)
    return response


def do_action(request_id, verb):
    info = connection()
    result = request(info, verb, {'id': request_id})
    phase = result.get('state')
    if verb == 'send' and phase != 'sent':
        raise RuntimeError('Draft cannot be sent: {}'.format(phase))
    status(request_id, phase if phase else ('sent' if verb == 'send' else 'cancelled'),
           'Sent to designated VS Code terminal (agent execution not verified).' if verb == 'send' else '')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-id', default=None)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--send', action='store_true')
    group.add_argument('--cancel', action='store_true')
    group.add_argument('--text', default=None, help='Use typed transcript, no microphone (test mode)')
    parser.add_argument('--shortcut', default='Rhino Agent Dictate')
    parser.add_argument('--test-link', action='store_true', help='Only verify VS Code extension connection')
    args = parser.parse_args(argv)
    request_id = args.request_id or uuid.uuid4().hex
    if not vp.valid_id(request_id):
        parser.error('request-id must be 32 lowercase hex characters')
    try:
        if args.test_link:
            reply = request(connection(), 'status', {})
            print('VS Code connection OK: terminal={}. Auto-submit={}'.format(
                reply.get('terminal'), reply.get('autoSubmit')) )
            return 0
        if args.send or args.cancel:
            do_action(request_id, 'send' if args.send else 'cancel')
        else:
            do_draft(request_id, args.text, args.shortcut)
    except Exception as exc:
        status(request_id, 'error', str(exc))
        print('Voice agent error:', exc, file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
