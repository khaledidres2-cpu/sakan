import os
from datetime import date, datetime
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from database import Base, engine, get_db, SessionLocal
import models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ساكن - نظام إدارة شقق السراير")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "sakin2026")


# ---------------------- المصادقة (بسيطة للمرحلة الأولى) ----------------------

def require_auth(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    if token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="غير مصرح")
    return True


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody):
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة")
    return {"token": ADMIN_PASSWORD, "role": "manager"}


# ---------------------- زرع البيانات الأولية (الشقتين) ----------------------

def seed_if_empty():
    db = SessionLocal()
    try:
        if db.query(models.Apartment).count() > 0:
            return
        for apt_name in ["شقة 1", "شقة 2"]:
            apt = models.Apartment(name=apt_name)
            db.add(apt)
            db.flush()

            master = models.Room(apartment_id=apt.id, name="غرفة ماستر", room_type="master")
            regular = models.Room(apartment_id=apt.id, name="غرفة عادية", room_type="regular")
            hall = models.Room(apartment_id=apt.id, name="الصالة", room_type="hall")
            db.add_all([master, regular, hall])
            db.flush()

            # غرفة ماستر: 4 سراير × 800
            for i in range(1, 5):
                db.add(models.Bed(room_id=master.id, code=f"M{i}",
                                  position="single", default_price=800))

            # غرفة عادية: 8 سراير دبل (4 وحدات × علوي/سفلي) × 500
            for i in range(1, 5):
                db.add(models.Bed(room_id=regular.id, code=f"R{i}-سفلي",
                                  position="lower", default_price=500))
                db.add(models.Bed(room_id=regular.id, code=f"R{i}-علوي",
                                  position="upper", default_price=500))

            # الصالة: 14 سرير دبل (7 وحدات × علوي/سفلي) × 500
            for i in range(1, 8):
                db.add(models.Bed(room_id=hall.id, code=f"S{i}-سفلي",
                                  position="lower", default_price=500))
                db.add(models.Bed(room_id=hall.id, code=f"S{i}-علوي",
                                  position="upper", default_price=500))

        db.commit()
    finally:
        db.close()


seed_if_empty()


def log_action(db: Session, action: str):
    db.add(models.ActivityLog(action=action))


# ---------------------- الشقق والسراير ----------------------

@app.get("/api/apartments")
def list_apartments(db: Session = Depends(get_db), _=Depends(require_auth)):
    result = []
    for apt in db.query(models.Apartment).all():
        beds_total, beds_occupied, expected = 0, 0, 0.0
        rooms_out = []
        for room in apt.rooms:
            beds_out = []
            for bed in room.beds:
                beds_total += 1
                active = next((c for c in bed.contracts if c.status == "active"), None)
                if active:
                    beds_occupied += 1
                    expected += active.monthly_rent
                beds_out.append({
                    "id": bed.id, "code": bed.code, "position": bed.position,
                    "price": bed.default_price, "status": bed.status,
                    "tenant": active.tenant.name if active else None,
                    "contract_id": active.id if active else None,
                })
            rooms_out.append({"id": room.id, "name": room.name,
                              "type": room.room_type, "beds": beds_out})
        result.append({
            "id": apt.id, "name": apt.name, "rooms": rooms_out,
            "beds_total": beds_total, "beds_occupied": beds_occupied,
            "occupancy_pct": round(beds_occupied / beds_total * 100) if beds_total else 0,
            "expected_monthly_income": expected,
        })
    return result


class BedUpdate(BaseModel):
    default_price: Optional[float] = None
    status: Optional[str] = None


@app.patch("/api/beds/{bed_id}")
def update_bed(bed_id: int, body: BedUpdate,
               db: Session = Depends(get_db), _=Depends(require_auth)):
    bed = db.get(models.Bed, bed_id)
    if not bed:
        raise HTTPException(404, "السرير غير موجود")
    if body.default_price is not None:
        log_action(db, f"تعديل سعر السرير {bed.code} من {bed.default_price} إلى {body.default_price}")
        bed.default_price = body.default_price
    if body.status is not None:
        log_action(db, f"تغيير حالة السرير {bed.code} إلى {body.status}")
        bed.status = body.status
    db.commit()
    return {"ok": True}


# ---------------------- المستأجرين ----------------------

class TenantBody(BaseModel):
    name: str
    phone: str = ""
    id_number: str = ""
    notes: str = ""


@app.get("/api/tenants")
def list_tenants(db: Session = Depends(get_db), _=Depends(require_auth)):
    out = []
    for t in db.query(models.Tenant).order_by(models.Tenant.name).all():
        active = next((c for c in t.contracts if c.status == "active"), None)
        out.append({
            "id": t.id, "name": t.name, "phone": t.phone,
            "id_number": t.id_number, "notes": t.notes,
            "bed": active.bed.code if active else None,
            "contract_id": active.id if active else None,
        })
    return out


@app.post("/api/tenants")
def create_tenant(body: TenantBody, db: Session = Depends(get_db), _=Depends(require_auth)):
    t = models.Tenant(**body.dict())
    db.add(t)
    log_action(db, f"إضافة مستأجر جديد: {body.name}")
    db.commit()
    db.refresh(t)
    return {"id": t.id}


@app.patch("/api/tenants/{tenant_id}")
def update_tenant(tenant_id: int, body: TenantBody,
                  db: Session = Depends(get_db), _=Depends(require_auth)):
    t = db.get(models.Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "المستأجر غير موجود")
    for k, v in body.dict().items():
        setattr(t, k, v)
    db.commit()
    return {"ok": True}


# ---------------------- العقود (تسكين / إخلاء) ----------------------

class ContractBody(BaseModel):
    tenant_id: int
    bed_id: int
    start_date: date
    monthly_rent: float
    deposit: float = 0
    notes: str = ""


@app.post("/api/contracts")
def create_contract(body: ContractBody, db: Session = Depends(get_db), _=Depends(require_auth)):
    bed = db.get(models.Bed, body.bed_id)
    tenant = db.get(models.Tenant, body.tenant_id)
    if not bed or not tenant:
        raise HTTPException(404, "السرير أو المستأجر غير موجود")
    if any(c.status == "active" for c in bed.contracts):
        raise HTTPException(400, f"السرير {bed.code} مشغول بعقد نشط")
    c = models.Contract(**body.dict())
    bed.status = "occupied"
    db.add(c)
    log_action(db, f"تسكين {tenant.name} في السرير {bed.code} بإيجار {body.monthly_rent} درهم")
    db.commit()
    db.refresh(c)
    return {"id": c.id}


class EndContractBody(BaseModel):
    end_date: date
    deposit_returned: bool = True
    notes: str = ""


@app.post("/api/contracts/{contract_id}/end")
def end_contract(contract_id: int, body: EndContractBody,
                 db: Session = Depends(get_db), _=Depends(require_auth)):
    c = db.get(models.Contract, contract_id)
    if not c or c.status != "active":
        raise HTTPException(404, "لا يوجد عقد نشط بهذا الرقم")
    c.status = "ended"
    c.end_date = body.end_date
    c.deposit_returned = body.deposit_returned
    if body.notes:
        c.notes = (c.notes + "\n" + body.notes).strip()
    c.bed.status = "vacant"
    dep = "مع إرجاع التأمين" if body.deposit_returned else "بدون إرجاع التأمين"
    log_action(db, f"إخلاء {c.tenant.name} من السرير {c.bed.code} ({dep})")
    db.commit()
    return {"ok": True}


# ---------------------- الدفعات والإيصالات ----------------------

def next_receipt_no(db: Session) -> str:
    year = datetime.utcnow().year
    count = db.query(models.Payment).filter(
        models.Payment.receipt_no.like(f"SKN-{year}-%")).count()
    return f"SKN-{year}-{count + 1:04d}"


class PaymentBody(BaseModel):
    contract_id: int
    month: str          # "2026-07"
    amount: float
    method: str = "cash"
    notes: str = ""


@app.post("/api/payments")
def create_payment(body: PaymentBody, db: Session = Depends(get_db), _=Depends(require_auth)):
    c = db.get(models.Contract, body.contract_id)
    if not c:
        raise HTTPException(404, "العقد غير موجود")
    existing = db.query(models.Payment).filter_by(
        contract_id=body.contract_id, month=body.month).first()
    if existing:
        raise HTTPException(400, f"يوجد دفعة مسجلة لهذا الشهر بإيصال {existing.receipt_no}")
    p = models.Payment(receipt_no=next_receipt_no(db), **body.dict())
    db.add(p)
    log_action(db, f"استلام {body.amount} درهم من {c.tenant.name} عن شهر {body.month} — إيصال {p.receipt_no}")
    db.commit()
    db.refresh(p)
    return {"id": p.id, "receipt_no": p.receipt_no}


@app.get("/api/payments")
def list_payments(month: Optional[str] = None,
                  db: Session = Depends(get_db), _=Depends(require_auth)):
    q = db.query(models.Payment).options(
        joinedload(models.Payment.contract).joinedload(models.Contract.tenant),
        joinedload(models.Payment.contract).joinedload(models.Contract.bed),
    ).order_by(models.Payment.paid_at.desc())
    if month:
        q = q.filter(models.Payment.month == month)
    return [{
        "id": p.id, "receipt_no": p.receipt_no, "month": p.month,
        "amount": p.amount, "method": p.method,
        "paid_at": p.paid_at.isoformat(),
        "tenant": p.contract.tenant.name, "bed": p.contract.bed.code,
    } for p in q.all()]


@app.get("/api/late")
def late_report(month: str, db: Session = Depends(get_db), _=Depends(require_auth)):
    """المتأخرين: عقود نشطة بدون دفعة للشهر المحدد."""
    out = []
    contracts = db.query(models.Contract).filter_by(status="active").all()
    for c in contracts:
        paid = any(p.month == month for p in c.payments)
        if not paid:
            out.append({
                "contract_id": c.id, "tenant": c.tenant.name,
                "phone": c.tenant.phone, "bed": c.bed.code,
                "monthly_rent": c.monthly_rent,
            })
    return out


# ---------------------- ملخص شهري (أساس التسوية لاحقاً) ----------------------

@app.get("/api/summary")
def month_summary(month: str, db: Session = Depends(get_db), _=Depends(require_auth)):
    payments = db.query(models.Payment).filter_by(month=month).all()
    total = sum(p.amount for p in payments)
    active = db.query(models.Contract).filter_by(status="active").count()
    return {
        "month": month,
        "total_collected": total,
        "payments_count": len(payments),
        "active_contracts": active,
        "late_count": len(late_report(month, db, True)),
    }


# ---------------------- سجل النشاط ----------------------

@app.get("/api/activity")
def activity(limit: int = 100, db: Session = Depends(get_db), _=Depends(require_auth)):
    rows = db.query(models.ActivityLog).order_by(
        models.ActivityLog.created_at.desc()).limit(limit).all()
    return [{"action": r.action, "at": r.created_at.isoformat()} for r in rows]


# ---------------------- إيصال HTML قابل للطباعة/الحفظ PDF ----------------------

@app.get("/receipt/{payment_id}", response_class=HTMLResponse)
def receipt_view(payment_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Payment, payment_id)
    if not p:
        raise HTTPException(404, "الإيصال غير موجود")
    c = p.contract
    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>إيصال {p.receipt_no}</title>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background:#f4f4f4; margin:0; padding:20px; }}
  .receipt {{ max-width:480px; margin:auto; background:#fff; border:1px solid #ddd;
             border-radius:12px; padding:28px; }}
  .head {{ text-align:center; border-bottom:2px solid #1a936f; padding-bottom:14px; margin-bottom:18px; }}
  .head h1 {{ margin:0; color:#1a936f; font-size:26px; }}
  .head p {{ margin:4px 0 0; color:#777; font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:9px 4px; border-bottom:1px dashed #e5e5e5; font-size:15px; }}
  td:first-child {{ color:#666; width:42%; }}
  .amount {{ text-align:center; margin:18px 0 6px; }}
  .amount span {{ font-size:30px; font-weight:bold; color:#1a936f; }}
  .foot {{ text-align:center; color:#999; font-size:12px; margin-top:16px; }}
  .print-btn {{ display:block; margin:16px auto 0; padding:10px 26px; background:#1a936f;
               color:#fff; border:none; border-radius:8px; font-size:15px; cursor:pointer; }}
  @media print {{ .print-btn {{ display:none; }} body {{ background:#fff; }} }}
</style>
</head>
<body>
<div class="receipt">
  <div class="head">
    <h1>ساكن</h1>
    <p>إيصال استلام إيجار</p>
  </div>
  <table>
    <tr><td>رقم الإيصال</td><td><b>{p.receipt_no}</b></td></tr>
    <tr><td>المستأجر</td><td>{c.tenant.name}</td></tr>
    <tr><td>السرير</td><td>{c.bed.code}</td></tr>
    <tr><td>عن شهر</td><td>{p.month}</td></tr>
    <tr><td>طريقة الدفع</td><td>{"نقدي" if p.method == "cash" else ("تحويل" if p.method == "transfer" else p.method)}</td></tr>
    <tr><td>تاريخ الاستلام</td><td>{p.paid_at.strftime("%Y-%m-%d %H:%M")}</td></tr>
  </table>
  <div class="amount"><span>{p.amount:,.0f} درهم</span></div>
  <div class="foot">هذا الإيصال صادر من نظام ساكن لإدارة الشقق</div>
  <button class="print-btn" onclick="window.print()">🖨️ طباعة / حفظ PDF</button>
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/")
def root():
    return {"app": "ساكن", "status": "running"}
