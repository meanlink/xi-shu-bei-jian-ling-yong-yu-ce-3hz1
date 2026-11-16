"""凭据签发、核验与导出的数据库层。

签发与业务结果同事务提交或回滚；链序号在 chain_state 行锁内分配，
并发事务按实际落库顺序衔接；(event, ref_type, ref_id) 唯一约束配合
锁内复查，保证中断恢复重试不重复记证。
"""
import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.models import Credential, ChainState, Verification, Dataset, Job, Delivery
from src.services import chaincore
from src.services.audit import record
from src.utils.serialization import checksum


# ---------- 业务快照与摘要（签发与核验共用同一构造） ----------

def dataset_snapshot(d):
    return {'event': 'dataset.intake', 'ref_id': d.id, 'name': d.name, 'source': d.source,
            'rows': len(d.records), 'records_checksum': checksum(d.records)}


def job_completed_snapshot(j):
    return {'event': 'job.completed', 'ref_id': j.id, 'name': j.name, 'dataset_id': j.dataset_id,
            'params': j.params, 'result': j.result, 'status': j.status}


def job_approved_snapshot(j):
    return {'event': 'job.approved', 'ref_id': j.id, 'name': j.name, 'dataset_id': j.dataset_id,
            'params': j.params, 'result': j.result, 'approved': j.approved}


def delivery_snapshot(d):
    return {'event': 'delivery.archived', 'ref_id': d.id, 'report_id': d.report_id,
            'destination': d.destination, 'filename': d.filename, 'checksum': d.checksum}


def dataset_summary(d):
    return {'name': d.name, 'source': d.source, 'rows': len(d.records), 'checksum': checksum(d.records)}


def job_completed_summary(j):
    result = j.result or {}
    return {'name': j.name, 'dataset_id': j.dataset_id, 'params': j.params,
            'summary': result.get('summary', ''), 'metrics': result.get('metrics', []),
            'finished_at': j.finished_at}


def job_approved_summary(j, actor):
    return {'name': j.name, 'dataset_id': j.dataset_id, 'params': j.params,
            'result_summary': (j.result or {}).get('summary', ''), 'approved_by': actor}


def delivery_summary(delivery, report, job):
    return {'report': report.name, 'report_id': report.id, 'job_id': job.id,
            'destination': delivery.destination, 'filename': delivery.filename,
            'checksum': delivery.checksum}


# ---------- 签发 ----------

def _locked_state(db):
    state = db.scalar(select(ChainState).where(ChainState.id == 1).with_for_update())
    if state is None:
        try:
            with db.begin_nested():
                state = ChainState(id=1, last_seq=0, last_hash=chaincore.GENESIS)
                db.add(state)
                db.flush()
        except IntegrityError:
            # 并发初始化：另一事务已建行，等待其提交后取出行锁
            state = db.scalar(select(ChainState).where(ChainState.id == 1).with_for_update())
    return state


def issue(db, event, ref_type, ref_id, actor, summary, snapshot):
    """为业务结果记证。须在业务变更的同一事务内调用，由调用方提交。"""
    if event not in chaincore.EVENTS:
        raise ValueError('未知的凭据事件类型')
    existing = db.scalar(select(Credential).where(Credential.event == event,
                                                  Credential.ref_type == ref_type,
                                                  Credential.ref_id == ref_id))
    if existing:
        return existing
    state = _locked_state(db)
    # 锁内复查：等待锁期间另一事务可能已为同一业务事件记证
    existing = db.scalar(select(Credential).where(Credential.event == event,
                                                  Credential.ref_type == ref_type,
                                                  Credential.ref_id == ref_id))
    if existing:
        return existing
    seq = state.last_seq + 1
    prev_hash = state.last_hash
    created_at = time.time()
    business_hash = chaincore.snapshot_hash(snapshot)
    fingerprint = chaincore.credential_hash(seq, event, ref_type, ref_id, actor, summary,
                                            business_hash, prev_hash, created_at)
    credential = Credential(seq=seq, event=event, ref_type=ref_type, ref_id=ref_id, actor=actor,
                            summary=summary, business_hash=business_hash, prev_hash=prev_hash,
                            hash=fingerprint, created_at=created_at)
    db.add(credential)
    state.last_seq = seq
    state.last_hash = fingerprint
    db.flush()
    return credential


# ---------- 查询 ----------

def head(db):
    state = db.get(ChainState, 1)
    if state is None:
        return {'seq': 0, 'hash': chaincore.GENESIS}
    return {'seq': state.last_seq, 'hash': state.last_hash}


def list_recent(db, limit=500):
    return list(db.scalars(select(Credential).order_by(Credential.seq.desc()).limit(limit)))


def list_verifications(db, limit=50):
    return list(db.scalars(select(Verification).order_by(Verification.id.desc()).limit(limit)))


def credential_row(c):
    return {'seq': c.seq, 'event': c.event, 'ref_type': c.ref_type, 'ref_id': c.ref_id,
            'actor': c.actor, 'summary': c.summary, 'business_hash': c.business_hash,
            'prev_hash': c.prev_hash, 'hash': c.hash, 'created_at': c.created_at}


def credential_dict(c):
    return credential_row(c)


def verification_dict(v):
    return {'id': v.id, 'from_seq': v.from_seq, 'to_seq': v.to_seq, 'head_seq': v.head_seq,
            'head_hash': v.head_hash, 'status': v.status, 'anomalies': v.anomalies,
            'segments': v.segments, 'actor': v.actor, 'created_at': v.created_at}


# ---------- 核验 ----------

def _lookup(db):
    def lookup(event, ref_id):
        if event == 'dataset.intake':
            d = db.get(Dataset, ref_id)
            return dataset_snapshot(d) if d else None
        if event == 'job.completed':
            j = db.get(Job, ref_id)
            return job_completed_snapshot(j) if j else None
        if event == 'job.approved':
            j = db.get(Job, ref_id)
            return job_approved_snapshot(j) if j else None
        if event == 'delivery.archived':
            d = db.get(Delivery, ref_id)
            return delivery_snapshot(d) if d else None
        return None
    return lookup


def verify(db, from_seq, to_seq, actor):
    state = db.get(ChainState, 1)
    head_seq = state.last_seq if state else 0
    if head_seq == 0:
        raise HTTPException(409, '凭据链为空，暂无可核验的凭据')
    if from_seq < 1 or to_seq < from_seq or to_seq > head_seq:
        raise HTTPException(422, f'核验范围须为 1 至当前链头 {head_seq} 之间的连续序号')
    rows = [credential_row(c) for c in db.scalars(
        select(Credential).where(Credential.seq >= from_seq, Credential.seq <= to_seq)
        .order_by(Credential.seq))]
    anchor = db.get(Credential, from_seq - 1)
    anchor_hash = anchor.hash if anchor else chaincore.GENESIS
    result = chaincore.verify_chain(rows, anchor_hash, from_seq, to_seq, _lookup(db))
    run = Verification(from_seq=from_seq, to_seq=to_seq, head_seq=head_seq,
                       head_hash=state.last_hash, status=result['status'],
                       anomalies=result['anomalies'], segments=result['segments'],
                       actor=actor, created_at=time.time())
    db.add(run)
    record(db, actor, 'credentials.verify',
           {'from': from_seq, 'to': to_seq, 'status': run.status, 'anomalies': len(run.anomalies)})
    db.flush()
    return run


# ---------- 导出 ----------

def export_upto(db, upto_seq, exporter):
    state = db.get(ChainState, 1)
    head_seq = state.last_seq if state else 0
    if head_seq == 0:
        raise HTTPException(409, '凭据链为空，暂无可导出的凭据')
    if upto_seq < 1 or upto_seq > head_seq:
        raise HTTPException(422, f'截止序号须为 1 至当前链头 {head_seq} 之间')
    # 单条快照查询：序号按实际落库顺序连续分配，晚于截止序号的新操作不会混入导出
    rows = [credential_row(c) for c in db.scalars(
        select(Credential).where(Credential.seq <= upto_seq).order_by(Credential.seq))]
    document = chaincore.export_document(rows, upto_seq, exporter, time.time())
    record(db, exporter, 'credentials.export', {'upto': upto_seq, 'count': len(rows)})
    return document
