from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import randbits
from typing import Annotated

from Crypto.Util.number import long_to_bytes
from fastapi import Cookie, Depends, HTTPException, Response, status

from mvmcryption.crypto.cipher import XSCBCCipher
from mvmcryption.crypto.ecdsa import ECDSA, private_key
from mvmcryption.crypto.jwt import SJWT
from mvmcryption.crypto.rsa import RSA, PrivKey
from mvmcryption.db.users import User, Users
from mvmcryption.resp import PERMISSION_DENIED

SJWT_TTL = timedelta(minutes=15)


def global_ecdsa(private_key: Annotated[int, Depends(private_key)]) -> ECDSA:
    return ECDSA(private_key)


def global_sjwt(ecdsa: Annotated[ECDSA, Depends(global_ecdsa)]):
    return SJWT(ecdsa)


def create_sjwt(user: User, sjwt: SJWT, expires: datetime | None = None) -> str:
    _expires = expires or (datetime.now(UTC) + SJWT_TTL)
    return sjwt.encode({"sub": user.id, "exp": _expires.isoformat()})


def decode_sjwt(token: str, sjwt: SJWT, users: Users) -> User | None:
    if not token:
        return None
    try:
        decoded = sjwt.decode(token)
    except Exception:
        return None

    if not (
        expiry_str := decoded.get("exp")
    ):  # no expiry -> some token generated by an admin
        return None  # for ~~security~~ budget reasons this is disabled right now # TODO: fix this

    if not isinstance(expiry_str, str):
        return None

    try:
        expiry = datetime.fromisoformat(expiry_str)
    except Exception:
        return None

    if not expiry or expiry <= datetime.now(UTC):
        return None

    user_id = decoded.get("sub")

    if user_id is None:
        return None

    if not isinstance(user_id, int):
        return None

    user = users.find(user_id)

    if user is None:
        return None

    return user


def authorized_user(
    users: Annotated[Users, Depends(Users.dependency)],
    sjwt: Annotated[SJWT, Depends(global_sjwt)],
    response: Response,
    mvmcryptionauthtoken: Annotated[str | None, Cookie()] = None,
):
    user = decode_sjwt(mvmcryptionauthtoken, sjwt, users)
    if not user:
        if mvmcryptionauthtoken:
            response.delete_cookie("mvmcryptionauthtoken")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
        )
    return user


def admin_user(user: Annotated[User, Depends(authorized_user)]):
    if not user.is_admin:
        raise PERMISSION_DENIED
    return user


def _aes_key() -> bytes:
    f = Path("/etc/aes-key")
    if not f.exists():
        f.write_bytes(long_to_bytes(randbits(128)))
    return f.read_bytes()


def global_rsa() -> RSA:
    f = Path("/etc/rsa")
    #
    # an attack on these should also work on the remote!
    e = 116591970041706379718532155665908888266686385012306382255623803049685541583532192334750761495391545779868293489052594691148251145407647036423290759484206824818995957368289817829191698292230111628507603650574855287432967558368023637303008639037850782925263155866362959265023886375680369942961371288326084824041

    p = 45451971945342384351746307287759765997973347839090260639694412464552793781005187267114562085821942688227357317219583361362353646878950896940183843297990546009873999147534085320185786757924396902950980568341191320751375188700478249675190215732576343159765113451640650736834237393822708039570047243039620286637

    q = 72009118392764261626413427431876874126326129069984217748634549026407244590676396047494273221646252626614631969458719207393002919632651673891260405183783344104061153870552960970102444506174717483826221480719066827975881319667694098081439486875056139219733072421530544103531952960041530707457961396585927096347

    if not f.exists():
        # key = RSA.new()
        key = PrivKey(p, q, e)
        f.write_text(json.dumps(key.__dict__))
    rsa = RSA(PrivKey(**json.loads(f.read_text())))

    assert rsa.verify(b"hello", rsa.sign(b"hello"))
    return rsa


GlobalRSA = Annotated[RSA, Depends(global_rsa)]


def global_aes(
    key: Annotated[bytes, Depends(_aes_key)],
    rsa: GlobalRSA,
):
    return XSCBCCipher(key, rsa)


AuthorizedUser = Annotated[User, Depends(authorized_user)]
AdminUser = Annotated[User, Depends(admin_user)]
GlobalECDSA = Annotated[ECDSA, Depends(global_ecdsa)]
GlobalXSCBCCipher = Annotated[XSCBCCipher, Depends(global_aes)]
