from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from src.config.database import get_db
from src.middlewares.auth import current_user, admin_only
from src.schemas.credential import VerifyInput
from src.services import credentials

router = APIRouter(prefix='/credentials')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return {'head': credentials.head(db),
            'credentials': [credentials.credential_dict(c) for c in credentials.list_recent(db)]}


@router.get('/verifications')
def verifications(db=Depends(get_db), u=Depends(current_user)):
    return [credentials.verification_dict(v) for v in credentials.list_verifications(db)]


@router.post('/verify', status_code=201)
def verify(data: VerifyInput, db=Depends(get_db), u=Depends(admin_only)):
    run = credentials.verify(db, data.from_seq, data.to_seq, u.email)
    db.commit()
    return credentials.verification_dict(run)


@router.get('/export')
def export(upto: int, db=Depends(get_db), u=Depends(admin_only)):
    document = credentials.export_upto(db, upto, u.email)
    db.commit()
    return JSONResponse(content=document, headers={
        'Content-Disposition': f'attachment; filename="credentials-export-{upto}.json"'})
