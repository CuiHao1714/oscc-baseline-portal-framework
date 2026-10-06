import json
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import Base, engine, get_db
from .models import Patient, User
from .security import ROLES, can_admin, can_edit, csrf_token, hash_password, validate_csrf, verify_password
from .services import blank_record, record_from_form, record_sections, upsert_patient

settings.validate()
app = FastAPI(title="XJKQ-OSCC Baseline Portal", version="0.1.0", docs_url="/api/docs")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=settings.session_https_only, same_site="lax")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["csrf_token"] = csrf_token


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    return user if user and user.is_active else None


def context(request: Request, user: User | None, **kwargs):
    return {"request": request, "user": user, **kwargs}


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def optional_filter_int(value: str, label: str) -> tuple[int | None, str | None]:
    """Treat blank GET form fields as unset and report invalid values in-page."""
    value = value.strip()
    if not value:
        return None, None
    try:
        return int(value), None
    except ValueError:
        return None, f"{label}必须填写整数。"


async def form_data(request: Request) -> dict[str, str]:
    """Accept URL-encoded forms only; this portal has no file-upload workflow."""
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        raise HTTPException(415, "Only URL-encoded forms are accepted")
    values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: value[-1] for key, value in values.items()}


def api_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db): return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", context(request, None))


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await form_data(request); validate_csrf(request, form.get("csrf_token"))
    username, password = str(form.get("username", "")).strip(), str(form.get("password", ""))
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", context(request, None, error="用户名或密码错误"), status_code=401)
    request.session.clear(); request.session["user_id"] = user.id; csrf_token(request)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    form = await form_data(request); validate_csrf(request, form.get("csrf_token")); request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user: return login_redirect()
    return templates.TemplateResponse(request, "dashboard.html", context(request, user, patient_count=db.query(Patient).count()))


@app.get("/patients", response_class=HTMLResponse)
def patients(request: Request, q: str = "", sex: str = "", primary_site: str = "", ajcc_stage: str = "", survival_status: str = "", age_min: str = "", age_max: str = "", cohort_year: str = "", page: int = 1, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user: return login_redirect()
    age_min_value, filter_error = optional_filter_int(age_min, "起始年龄")
    age_max_value, max_error = optional_filter_int(age_max, "终止年龄")
    cohort_year_value, year_error = optional_filter_int(cohort_year, "队列年份")
    filter_error = filter_error or max_error or year_error
    if not filter_error and age_min_value is not None and age_max_value is not None and age_min_value > age_max_value:
        filter_error = "起始年龄不能大于终止年龄。"
    query = db.query(Patient)
    if q.strip():
        term = f"%{q.strip()}%"; query = query.filter(or_(Patient.subject_id.ilike(term), Patient.primary_site.ilike(term)))
    if sex: query = query.filter(Patient.sex == sex)
    if primary_site: query = query.filter(Patient.primary_site == primary_site)
    if ajcc_stage: query = query.filter(Patient.ajcc_stage == ajcc_stage)
    if survival_status: query = query.filter(Patient.survival_status == survival_status)
    if age_min_value is not None: query = query.filter(Patient.age_at_diagnosis >= age_min_value)
    if age_max_value is not None: query = query.filter(Patient.age_at_diagnosis <= age_max_value)
    if cohort_year_value is not None: query = query.filter(Patient.cohort_year == cohort_year_value)
    page=max(page,1); page_size=25; total=query.count()
    records=query.order_by(Patient.cohort_year.is_(None), Patient.cohort_year.asc(), Patient.diagnosis_date.is_(None), Patient.diagnosis_date.asc(), Patient.subject_id.asc()).offset((page-1)*page_size).limit(page_size).all()
    options={"sexes":[x[0] for x in db.query(Patient.sex).filter(Patient.sex.isnot(None)).distinct().order_by(Patient.sex)],"sites":[x[0] for x in db.query(Patient.primary_site).filter(Patient.primary_site.isnot(None)).distinct().order_by(Patient.primary_site)],"stages":[x[0] for x in db.query(Patient.ajcc_stage).filter(Patient.ajcc_stage.isnot(None)).distinct().order_by(Patient.ajcc_stage)],"statuses":[x[0] for x in db.query(Patient.survival_status).filter(Patient.survival_status.isnot(None)).distinct().order_by(Patient.survival_status)]}
    return templates.TemplateResponse(request, "patients.html", context(request,user,records=records,total=total,page=page,page_size=page_size,options=options,filter_error=filter_error))


def edit_form(request: Request, user: User, record: dict, mode: str, error: str | None = None):
    return templates.TemplateResponse(request, "patient_form.html", context(request,user,record=record,sections=record_sections(record, include_empty=True),mode=mode,error=error))


@app.get("/patients/new", response_class=HTMLResponse)
def new_patient_page(request: Request, db: Session = Depends(get_db)):
    user=current_user(request,db)
    if not user: return login_redirect()
    if not can_edit(user.role): raise HTTPException(403,"Editor role required")
    return edit_form(request,user,blank_record(str(uuid4())),"new")


@app.post("/patients/new")
async def new_patient(request: Request, db: Session = Depends(get_db)):
    user=current_user(request,db)
    if not user: return login_redirect()
    if not can_edit(user.role): raise HTTPException(403,"Editor role required")
    form=await form_data(request); validate_csrf(request,form.get("csrf_token")); record=blank_record(str(uuid4()))
    try:
        record=record_from_form(form, record["subject_id"])
        patient=upsert_patient(db,record,"v0.1-manual",user.id,request.client.host if request.client else None); db.commit()
    except (ValueError,json.JSONDecodeError) as exc:
        db.rollback(); return edit_form(request,user,record,"new",f"保存失败：{exc}")
    return RedirectResponse(f"/patients/{patient.subject_id}",status_code=303)


@app.get("/patients/{subject_id}", response_class=HTMLResponse)
def patient_detail(subject_id: str, request: Request, db: Session = Depends(get_db)):
    user=current_user(request,db)
    if not user: return login_redirect()
    patient=db.query(Patient).filter(Patient.subject_id==subject_id).one_or_none()
    if not patient: raise HTTPException(404,"Patient not found")
    return templates.TemplateResponse(request, "patient_detail.html",context(request,user,patient=patient,sections=record_sections(patient.record_data, include_empty=False)))


@app.get("/patients/{subject_id}/edit", response_class=HTMLResponse)
def edit_patient_page(subject_id: str, request: Request, db: Session = Depends(get_db)):
    user=current_user(request,db)
    if not user: return login_redirect()
    if not can_edit(user.role): raise HTTPException(403,"Editor role required")
    patient=db.query(Patient).filter(Patient.subject_id==subject_id).one_or_none()
    if not patient: raise HTTPException(404,"Patient not found")
    return edit_form(request,user,patient.record_data,"edit")


@app.post("/patients/{subject_id}/edit")
async def edit_patient(subject_id: str, request: Request, db: Session = Depends(get_db)):
    user=current_user(request,db)
    if not user: return login_redirect()
    if not can_edit(user.role): raise HTTPException(403,"Editor role required")
    patient=db.query(Patient).filter(Patient.subject_id==subject_id).one_or_none()
    if not patient: raise HTTPException(404,"Patient not found")
    form=await form_data(request); validate_csrf(request,form.get("csrf_token"))
    try:
        record=record_from_form(form, subject_id)
        upsert_patient(db,record,"v0.1-manual",user.id,request.client.host if request.client else None); db.commit()
    except (ValueError,json.JSONDecodeError) as exc:
        db.rollback(); return edit_form(request,user,patient.record_data,"edit",f"保存失败：{exc}")
    return RedirectResponse(f"/patients/{subject_id}",status_code=303)


@app.get("/api/patients")
def patients_api(sex: str = "", primary_site: str = "", ajcc_stage: str = "", age_min: int | None = None, age_max: int | None = None, db: Session = Depends(get_db), user: User = Depends(api_user)):
    query=db.query(Patient)
    if sex: query=query.filter(Patient.sex==sex)
    if primary_site: query=query.filter(Patient.primary_site==primary_site)
    if ajcc_stage: query=query.filter(Patient.ajcc_stage==ajcc_stage)
    if age_min is not None: query=query.filter(Patient.age_at_diagnosis>=age_min)
    if age_max is not None: query=query.filter(Patient.age_at_diagnosis<=age_max)
    return JSONResponse({"items":[p.record_data for p in query.order_by(Patient.cohort_year.is_(None), Patient.cohort_year.asc(), Patient.diagnosis_date.is_(None), Patient.diagnosis_date.asc(), Patient.subject_id.asc()).limit(500)],"role":user.role})


@app.post("/admin/users")
async def create_user(request: Request, db: Session = Depends(get_db)):
    user=current_user(request,db)
    if not user: return login_redirect()
    if not can_admin(user.role): raise HTTPException(403,"Admin role required")
    form=await form_data(request); validate_csrf(request,form.get("csrf_token"))
    username,password,role=str(form.get("username","")).strip(),str(form.get("password","")),str(form.get("role","viewer"))
    if not username or role not in ROLES: raise HTTPException(422,"Invalid user fields")
    if db.query(User).filter(User.username==username).first(): raise HTTPException(409,"Username already exists")
    db.add(User(username=username,password_hash=hash_password(password),role=role)); db.commit()
    return RedirectResponse("/",status_code=303)
