"""可核验业务凭据链的核心算法：规范化、指纹、链式核验与导出清单。

只依赖标准库，签发方与核验方共用同一套构造，便于独立复算。
"""
import hashlib
import json

GENESIS = '0' * 64

# 纳入凭据链的四类业务事件：日历入库、试算完成、批准、简报归档
EVENTS = ('dataset.intake', 'job.completed', 'job.approved', 'delivery.archived')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def snapshot_hash(snapshot):
    """业务内容指纹：由当前业务实体重建快照后计算，用于比对凭据与业务是否相符。"""
    return digest(snapshot)


def credential_hash(seq, event, ref_type, ref_id, actor, summary, business_hash, prev_hash, created_at):
    return digest({
        'seq': seq, 'event': event, 'ref_type': ref_type, 'ref_id': ref_id,
        'actor': actor, 'summary': summary, 'business_hash': business_hash,
        'prev_hash': prev_hash, 'created_at': created_at,
    })


def row_hash(row):
    return credential_hash(row['seq'], row['event'], row['ref_type'], row['ref_id'],
                           row['actor'], row['summary'], row['business_hash'],
                           row['prev_hash'], row['created_at'])


def pass_attestation(from_seq, to_seq, end_hash):
    """干净区间的通过证明，绑定区间与区间末环指纹；异常区间不出具。"""
    return digest({'attestation': 'pass', 'from': from_seq, 'to': to_seq, 'end_hash': end_hash})


def verify_chain(rows, anchor_hash, from_seq, to_seq, lookup):
    """核验 [from_seq, to_seq] 区间，返回 {'status', 'anomalies', 'segments'}。

    rows: 区间内已存在的凭据字典（按 seq 排序，可能缺号）。
    anchor_hash: from_seq-1 号凭据的指纹；from_seq 为 1 时传 GENESIS。
    lookup(event, ref_id) -> 业务快照字典；业务记录不存在时返回 None。
    异常区间（缺号、链断裂、凭据篡改、业务缺失、业务不符）不出具通过证明。
    """
    anomalies = []
    by_seq = {row['seq']: row for row in rows}
    broken = set()
    prev_hash = anchor_hash
    for seq in range(from_seq, to_seq + 1):
        row = by_seq.get(seq)
        if row is None:
            anomalies.append({'seq': seq, 'type': '缺号', 'detail': f'第 {seq} 号凭据缺失，链上存在断点'})
            broken.add(seq)
            prev_hash = None
            continue
        if prev_hash is None:
            anomalies.append({'seq': seq, 'type': '链断裂', 'detail': f'第 {seq} 号凭据的前序环节缺失，无法衔接'})
            broken.add(seq)
        elif row['prev_hash'] != prev_hash:
            anomalies.append({'seq': seq, 'type': '链断裂', 'detail': f'第 {seq} 号凭据登记的前置指纹与上一环不符'})
            broken.add(seq)
        if row_hash(row) != row['hash']:
            anomalies.append({'seq': seq, 'type': '凭据篡改', 'detail': f'第 {seq} 号凭据内容与登记指纹不符'})
            broken.add(seq)
        snapshot = lookup(row['event'], row['ref_id'])
        if snapshot is None:
            anomalies.append({'seq': seq, 'type': '业务缺失', 'detail': f'第 {seq} 号凭据对应的业务记录已不存在'})
            broken.add(seq)
        elif snapshot_hash(snapshot) != row['business_hash']:
            anomalies.append({'seq': seq, 'type': '业务不符', 'detail': f'第 {seq} 号凭据与当前业务内容不一致'})
            broken.add(seq)
        prev_hash = row['hash']
    segments = []
    seq = from_seq
    while seq <= to_seq:
        start = seq
        if seq in broken:
            while seq + 1 in broken:
                seq += 1
            segments.append({'from': start, 'to': seq, 'result': '异常',
                             'issues': [a for a in anomalies if start <= a['seq'] <= seq]})
        else:
            while seq + 1 <= to_seq and seq + 1 not in broken:
                seq += 1
            segments.append({'from': start, 'to': seq, 'result': '通过',
                             'attestation': pass_attestation(start, seq, by_seq[seq]['hash'])})
        seq += 1
    return {'status': 'failed' if anomalies else 'passed', 'anomalies': anomalies, 'segments': segments}


def export_document(rows, upto_seq, exporter, exported_at):
    """按截止序号生成导出清单：凭据与业务摘要一并导出，清单本身带指纹可复算。"""
    credentials = [{
        'seq': r['seq'], 'event': r['event'], 'ref_type': r['ref_type'], 'ref_id': r['ref_id'],
        'actor': r['actor'], 'summary': r['summary'], 'business_hash': r['business_hash'],
        'prev_hash': r['prev_hash'], 'hash': r['hash'], 'created_at': r['created_at'],
    } for r in rows]
    manifest = {
        'type': 'credential-export', 'version': 1, 'cutoff_seq': upto_seq,
        'count': len(credentials), 'exported_by': exporter, 'exported_at': exported_at,
        'head_hash': credentials[-1]['hash'] if credentials else GENESIS,
    }
    return {**manifest, 'credentials': credentials,
            'manifest_checksum': digest({'manifest': manifest, 'credentials': credentials})}
