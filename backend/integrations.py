"""连接既有 SSH 环境；模型和训练均不拥有任意命令入口。"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shlex
import stat
import time
import paramiko
from .domain import RemoteConfig, ExperimentSpec
from .experiments import approved_payload, verify_log
from .store import ROOT, safe_path


@contextmanager
def ssh(config):
    config = RemoteConfig.model_validate(config)
    if not config.consent:
        raise ValueError('未授权远程操作')
    ssh_config = paramiko.SSHConfig()
    path = Path.home() / '.ssh/config'
    if path.exists():
        with path.open() as source:
            ssh_config.parse(source)
    entry = ssh_config.lookup(config.alias)
    if entry.get('proxycommand') or entry.get('proxyjump'):
        raise ValueError('首版不执行 ProxyCommand/ProxyJump；请配置可直连的 SSH 别名')
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(entry.get('hostname', config.alias), port=int(entry.get('port', 22)),
                       username=entry.get('user'), key_filename=entry.get('identityfile'),
                       timeout=12, banner_timeout=12, auth_timeout=15,
                       allow_agent=True, look_for_keys=True)
        yield client
    finally:
        client.close()


def mkdir(sftp, path):
    current = ''
    for part in PurePosixPath(path).parts:
        if part == '/':
            current = '/'
            continue
        current = current.rstrip('/') + '/' + part
        try:
            attrs = sftp.lstat(current)
            if not stat.S_ISDIR(attrs.st_mode):
                raise ValueError('远程路径不是目录或包含符号链接')
        except FileNotFoundError:
            sftp.mkdir(current, mode=0o700)


def put_immutable(sftp, path, raw):
    try:
        attrs = sftp.lstat(path)
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_size != len(raw):
            raise ValueError('远端文件冲突或非普通文件')
        with sftp.open(path, 'rb') as src:
            if hashlib.sha256(src.read(len(raw) + 1)).digest() != hashlib.sha256(raw).digest():
                raise ValueError('远端不可变文件内容冲突')
        return
    except FileNotFoundError:
        pass
    # 写临时文件后改名；只在新授权目录内写入。
    tmp = path + '.upload'
    with sftp.open(tmp, 'wb') as out:
        out.write(raw)
    sftp.chmod(tmp, 0o600)
    sftp.rename(tmp, path)


def runner_path(config, source=None):
    content = source.encode() if source is not None else (ROOT / 'runner/remote.py').read_bytes()
    return config['root'] + '/runner-' + hashlib.sha256(content).hexdigest()[:16] + '.py', content


def remote_call(client, config, action, id, payload=None, source=None):
    if action not in ('authorize', 'submit', 'status', 'cancel', 'doctor') or not re.fullmatch(r'approval-[a-f0-9]{16}', id):
        raise ValueError('拒绝非白名单远程动作')
    path, _ = runner_path(config, source)
    cmd = shlex.join([config['python'], path, config['root'], action, id])
    stdin, stdout, stderr = client.exec_command(cmd, timeout=40)
    if payload is not None:
        stdin.write(json.dumps(payload, ensure_ascii=False))
        stdin.flush()
    stdin.channel.shutdown_write()
    raw = stdout.read(1024 * 1024 + 1)
    error = stderr.read(10000)
    rc = stdout.channel.recv_exit_status()
    if rc or len(raw) > 1024 * 1024:
        raise ValueError('远程动作未成功：' + (raw + error).decode(errors='replace')[-600:])
    return json.loads(raw)


def deploy(client, config, source=None):
    path, raw = runner_path(config, source)
    with client.open_sftp() as sftp:
        mkdir(sftp, config['root'])
        put_immutable(sftp, path, raw)
    return remote_call(client, config, 'doctor', 'approval-' + '0' * 16, source=source)


def submit(store, approval_id, prepare_only=False):
    approval = approved_payload(store, approval_id)
    payload = approval['payload']
    config = payload['remote']
    source = payload.get('runner_source')
    safe_payload = {k: v for k, v in payload.items() if k != 'runner_source'}
    safe_payload['snapshot'] = dict(files={name: {'sha256': f['sha256'], 'size': f['size']}
                                          for name, f in payload['snapshot']['files'].items()})
    with ssh(config) as client:
        deploy(client, config, source)
        remote_call(client, config, 'authorize', approval_id, safe_payload, source=source)
        with client.open_sftp() as sftp:
            code = config['root'] + '/' + approval_id + '/code'
            mkdir(sftp, code)
            for name, entry in payload['snapshot']['files'].items():
                local_file = safe_path(store.root, entry['blob'], True)
                raw = local_file.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    raise ValueError('本地代码快照已变化')
                target = code + '/' + name
                mkdir(sftp, str(PurePosixPath(target).parent))
                put_immutable(sftp, target, raw)
        result = remote_call(client, config, 'status' if prepare_only else 'submit', approval_id, source=source)
    store.event(approval['project'], 'remote.submitted', {'approval': approval_id, 'status': result['status']}, payload['spec']['phase'])
    return result


def sync(store, approval_id, cancel=False):
    with store.connect() as db:
        row = db.execute('SELECT * FROM approvals WHERE id=?', (approval_id,)).fetchone()
    if not row:
        raise ValueError('审批不存在')
    payload = json.loads(row['payload'])
    config, spec = payload['remote'], ExperimentSpec.model_validate(payload['spec'])
    logs = []
    selections = {}
    seed_results = []
    with ssh(config) as client:
        result = remote_call(client, config, 'cancel' if cancel else 'status', approval_id, source=payload.get('runner_source'))
        with client.open_sftp() as sftp:
            for seed in spec.seeds:
                remote = f"{config['root']}/{approval_id}/run-{seed}.jsonl"
                try:
                    size = sftp.stat(remote).st_size
                except FileNotFoundError:
                    continue
                if size > 8 * 1024 * 1024:
                    raise ValueError('远程日志超过允许大小')
                local = safe_path(store.root, f'remote/{approval_id}/run-{seed}.jsonl')
                local.parent.mkdir(parents=True, exist_ok=True)
                offset = local.stat().st_size if local.exists() else 0
                if offset > size:
                    raise ValueError('远程日志发生截断，需人工核对')
                with sftp.open(remote, 'rb') as src:
                    # 核对已有前缀，避免同长度改写被忽略。
                    prefix = src.read(offset)
                    if local.exists() and hashlib.sha256(prefix).digest() != hashlib.sha256(local.read_bytes()).digest():
                        raise ValueError('原始日志被改写')
                    extra = src.read(size - offset)
                with local.open('ab') as out:
                    out.write(extra)
                log_text = local.read_text(errors='replace')
                logs.append(log_text)
                seed_spec = spec.model_copy(update={'seeds': [seed]})
                seed_results.append(verify_log(log_text, seed_spec))
                if result['status'] == 'done' and spec.phase == 'dev':
                    with sftp.open(f"{config['root']}/{approval_id}/selection-{seed}.json", 'rb') as src:
                        selection = json.loads(src.read(8192))
                    if not re.fullmatch(r'[a-f0-9]{64}', selection.get('sha256', '')):
                        raise ValueError('选模指纹不合法')
                    safe_path(store.root, selection['path'])
                    metrics = [m for m in seed_results[-1]['metrics'] if m['metric'] == spec.metric and m['split'] == 'val']
                    if not metrics:
                        raise ValueError('选模缺少原始验证集证据')
                    best = (max if spec.direction == 'max' else min)(metrics, key=lambda m: m['value'])
                    if selection.get('step') != best['step'] or selection.get('value') != best['value']:
                        raise ValueError('选模记录与原始日志不一致')
                    selections[str(seed)] = selection
    raw = '\n'.join(logs)
    details = verify_log(raw, spec, returncode=0 if result['status'] == 'done' else 1) if result['status'] in ('done', 'blocked', 'failed') else dict(metrics=[], summaries=[], problems=[], verdict='INCONCLUSIVE')
    if result['status'] == 'done' and (len(seed_results) != len(spec.seeds) or any(r['verdict'] not in ('PASS', 'FAIL') for r in seed_results)):
        order = ['PROTOCOL_VIOLATION', 'UNHEALTHY', 'INCONCLUSIVE', 'FAIL', 'PASS']
        details['verdict'] = min(['INCONCLUSIVE'] + [r['verdict'] for r in seed_results], key=order.index)
        details['problems'].append('逐 seed 证据未全部通过独立核验')
    blob = store.save_blob(raw.encode(), '.jsonl') if raw else None
    content = details | dict(title=spec.title, status=result['status'], remote=result, spec_id=row['spec_id'],
                              approval_id=approval_id, blob=blob, log_hash=hashlib.sha256(raw.encode()).hexdigest(),
                              protocol=spec.protocol, selections=selections,
                              refs=[{'id': row['spec_id'], 'version': payload.get('spec_version', 1)}])
    id = 'run-' + approval_id.removeprefix('approval-')
    try:
        old = store.get(id)
        if old['content'] == content:
            return old
        if old['content'].get('status') == 'done' and old['content'].get('log_hash') != content['log_hash']:
            raise ValueError('已归档运行日志发生变化，拒绝覆盖核验结果')
    except ValueError as exc:
        if str(exc) != '记录不存在':
            raise
    return store.put('run', row['project'], content, id=id,
                     visibility='final' if spec.phase == 'final' or details.get('visibility') == 'final' else 'dev')
