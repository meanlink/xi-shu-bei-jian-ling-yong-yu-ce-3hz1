from sqlalchemy import String, Double, JSON, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.services.chaincore import GENESIS


class Credential(Base):
    """业务凭据：与业务结果在同一事务生效或撤回，序号按实际落库顺序连续分配。"""
    __tablename__ = 'credentials'
    seq: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column(String(40))
    ref_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(150))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # 业务摘要，随凭据导出
    business_hash: Mapped[str] = mapped_column(String(64))  # 业务内容指纹
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    # 同一业务事件只记证一次：中断恢复重试不重复记证
    __table_args__ = (UniqueConstraint('event', 'ref_type', 'ref_id', name='uq_credential_event_ref'),)


class ChainState(Base):
    """链头单行状态；记证时行锁串行化，保证序号顺序即实际落库顺序。"""
    __tablename__ = 'chain_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), default=GENESIS)


class Verification(Base):
    """核验运行记录：范围、断点与结果留痕，供页面查询。"""
    __tablename__ = 'verifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    from_seq: Mapped[int] = mapped_column(Integer)
    to_seq: Mapped[int] = mapped_column(Integer)
    head_seq: Mapped[int] = mapped_column(Integer)
    head_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))  # passed / failed
    anomalies: Mapped[list] = mapped_column(JSON, default=list)  # 断点与异常明细
    segments: Mapped[list] = mapped_column(JSON, default=list)  # 区间结论；仅干净区间含通过证明
    actor: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)
