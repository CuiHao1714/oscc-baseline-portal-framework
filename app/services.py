import csv
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy.orm import Session
from .config import settings
from .models import AuditLog, Patient


# The V0.1 package retains four legacy placeholder labels ("（必填）").
# These display-only corrections preserve the versioned data package while
# giving clinicians an unambiguous label in the portal.
DISPLAY_LABEL_OVERRIDES = {
    "nrm": "NRM 编号",
    "age_at_initial_diagnosis": "初次诊断年龄",
    "diagnosis_date": "诊断日期",
    "sex": "性别",
}

# Controlled choices for clinically standardized fields.  The V0.1 schema has
# no enum declarations, so this presentation-level catalog prevents typos
# without altering the stored JSON contract.
FORM_SELECT_OPTIONS = {
    "sex": ["man", "women"],
    "ct": ["T0", "Tis", "T1", "T2", "T3", "T4", "T4a", "T4b", "TX"],
    "pt": ["T0", "Tis", "T1", "T2", "T3", "T4", "T4a", "T4b", "TX"],
    "cn": ["N0", "N1", "N2", "N2a", "N2b", "N2c", "N3", "N3a", "N3b", "NX"],
    "pn": ["N0", "N1", "N2", "N2a", "N2b", "N2c", "N3", "N3a", "N3b", "NX"],
    "cm": ["M0", "M1", "MX"], "m": ["M0", "M1", "MX"],
    "ajcc_stage": ["I", "II", "III", "IVA", "IVB", "IVC"],
    "ace_27": ["0", "1", "2", "3"],
}
FORM_OVERRIDE_CONTROLS = {
    "cn": (["NX", "N0", "N1", "N2", "N2a", "N2b", "N2c", "N3", "N3a", "N3b"], "Value sheet（AJCC 第 7/8 版候选并集）", "请依据 AJCC 版本确认后选择；第 7 版不含 N3a/N3b。"),
    "pt": (["TX", "T0", "Tis", "T1", "T2", "T3", "T4", "T4a", "T4b"], "Value sheet（AJCC 第 7/8 版共同候选）", "请依据 AJCC 版本确认后选择。"),
    "m": (["M0", "M1"], "Value sheet（AJCC 第 7/8 版共同候选）", "请依据 AJCC 版本确认后选择。"),
    "neck_dissection_intent_left_1_primsugr": (["elective", "therapeutic", "Unknown", "not_applicable"], "Value sheet（颈清手术临床目的）", None),
    "neck_dissection_intent_right_1_primsugr": (["elective", "therapeutic", "Unknown", "not_applicable"], "Value sheet（颈清手术临床目的）", None),
    "neck_dissection_parotid_1_primsugr": (["yes", "no"], "Definition of value（Yes/No）", None),
    "ene_c_1_primsugr": (["negative", "positive", "unknown", "Undocumented", "Not reported"], "Value sheet（ENE p/c）", "p/c 共用值域；请确认临床 ENE 语义。"),
    "progress_1_1": (["yes", "no"], "Definition of value（Yes/No）", None),
    "recurrence_1_2": (["Adrenal (肾上腺)", "Brain (脑)", "Liver (肝)", "Lungs (肺)", "Peritoneum (腹膜)", "Pleura (胸膜)", "Skin (皮肤)", "Soft Tissue (软组织)", "Spleen (脾)", "Other Organs (其他器官)"], "Value sheet（远处转移部位关联值域）", "原始字典未定义 recurrence_1_2；此处采用关联值域，需人工确认字段语义。"),
}
FORM_OPTION_LABELS = {"man": "男", "women": "女", "yes": "是", "no": "否", "positive": "阳性", "negative": "阴性", "not_tested": "未检测"}
FREE_TEXT_FIELDS = {"comorbidities", "death_cause_1", "distant_metastasis_site_1_1"}
# Optional, institution-supplied dictionary audit artifacts. They are not
# part of the public distribution because they may be controlled research data.
AUDIT_DOCUMENTATION_DIR = Path(os.environ["VALUE_CATALOG_DIR"]) if os.getenv("VALUE_CATALOG_DIR") else None


def normalized_key(value: object) -> str:
    return "".join(char for char in str(value or "").lower() if char.isalnum())


@lru_cache
def audited_value_catalog() -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[list[str], str]]]:
    """Load only audited, high-confidence Value-sheet links for form controls."""
    if AUDIT_DOCUMENTATION_DIR is None:
        return {}, {}
    definition_path = AUDIT_DOCUMENTATION_DIR / "V0_Definition_of_value_规范化梳理.csv"
    value_path = AUDIT_DOCUMENTATION_DIR / "V0_Value_规范化梳理.csv"
    if not definition_path.exists() or not value_path.exists():
        return {}, {}
    with value_path.open(encoding="utf-8-sig", newline="") as handle:
        value_rows = {row["source_value_set"]: tuple(value for value in row["allowed_values"].split(" | ") if value) for row in csv.DictReader(handle)}
    choices: dict[str, tuple[str, ...]] = {}
    notices: dict[str, tuple[list[str], str]] = {}
    with definition_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = normalized_key(row["source_field"])
            targets = [item.strip() for item in row["matched_value_sets"].split(";") if item.strip()]
            if row["match_confidence"] == "HIGH" and len(targets) == 1 and targets[0] in value_rows:
                choices[key] = value_rows[targets[0]]
            elif row["match_method"] == "AMBIGUOUS":
                notices[key] = (targets, "该字段的 AJCC 第 7/8 版值域尚待确认；当前不限制录入值。")
    return choices, notices


@lru_cache
def observed_category_options() -> dict[str, tuple[str, ...]]:
    """Conservative dropdown options inferred from low-cardinality V0.1 values."""
    package = json.loads(Path(settings.dataset_path).read_text(encoding="utf-8"))
    catalog = {field["name"]: field for field in package["data_dictionary"]}
    options: dict[str, tuple[str, ...]] = {}
    for name, field in catalog.items():
        if field["data_type"] != "string" or name.startswith("notes_") or name.startswith("unlabeled_") or name in FREE_TEXT_FIELDS:
            continue
        values = sorted({str(record[name]) for record in package["records"] if record.get(name) is not None})
        if 2 <= len(values) <= 30:
            options[name] = tuple(values)
    return options


def form_control(field: dict[str, Any], value: Any) -> tuple[list[dict[str, str]], str | None, str | None]:
    """Return safe dropdown choices, their audited source, and any review notice."""
    name = field["name"]
    if name in FORM_OVERRIDE_CONTROLS:
        values, source, notice = FORM_OVERRIDE_CONTROLS[name]
        current = str(value) if value is not None else None
        if current and current not in values:
            values = [*values, current]
        return [{"value": item, "label": FORM_OPTION_LABELS.get(item, item)} for item in values], source, notice
    audited_choices, audited_notices = audited_value_catalog()
    source_keys = [normalized_key(field.get("source_column")), normalized_key(name)]
    type_conflict_notice = None
    for key in source_keys:
        if key in audited_choices:
            candidate_values = list(audited_choices[key])
            if field["data_type"] == "integer" and not all(item.lstrip("-").isdigit() for item in candidate_values):
                values, source = None, None
                type_conflict_notice = "审计值域与当前正式字段类型不一致，保留数值输入；请人工核验。"
            elif field["data_type"] == "number":
                try:
                    for item in candidate_values:
                        float(item)
                except ValueError:
                    values, source = None, None
                    type_conflict_notice = "审计值域与当前正式字段类型不一致，保留数值输入；请人工核验。"
                else:
                    values, source = candidate_values, "Value sheet（已审计高置信度值域）"
            else:
                values, source = candidate_values, "Value sheet（已审计高置信度值域）"
            break
    else:
        values, source = None, None
    for key in source_keys:
        if key in audited_notices:
            return [], None, audited_notices[key][1]
    if values is None:
        values = FORM_SELECT_OPTIONS.get(name)
    if values is None and name.endswith("_grade"):
        values = ["0", "1", "2", "3"]
    if values is None and (name.startswith("episode_") or name in {"smoking_status", "alcohol_status", "used_primarysurgery_1_primsugr", "used_neckdissection_1_primsugr", "tracheostomy_1_primsugr", "recurrence_1_1", "distant_metastasis_1_1"}):
        values = ["yes", "no"]
    if values is None:
        values = list(observed_category_options().get(name, ()))
    if not values:
        return [], None, type_conflict_notice
    current = str(value) if value is not None else None
    if current and current not in values:
        values = [*values, current]
    if source is None:
        source = "标准化录入选项" if name in FORM_SELECT_OPTIONS or name.endswith("_grade") else "V0.1 数据包已观察分类值"
    return [{"value": item, "label": FORM_OPTION_LABELS.get(item, item)} for item in values], source, type_conflict_notice


FORM_SECTION_GROUPS = {
    "初始手术": [
        ("新辅助治疗", {"episode_1_neoadj", "tx_start_date_1_neoadj", "tx_class_1_neoadj"}),
        ("原发手术", {"episode_1_primsug", "treatment_intent_1_primsugr", "used_primarysurgery_1_primsugr", "date_of_primarysurgery_1_primsugr"}),
        ("颈部清扫", {"used_neckdissection_1_primsugr", "date_of_neckdissection_1_primsugr", "neck_dissection_type_1_primsugr", "neck_dissection_intent_total_1_primsugr", "neck_dissection_intent_left_1_primsugr", "neck_dissection_intent_right_1_primsugr", "neck_dissection_laterality_1_primsugr", "neck_dissection_levels_left_1_primsugr", "neck_dissection_levels_right_1_primsugr", "neck_dissection_parotid_1_primsugr"}),
        ("围手术期处理", {"tracheostomy_1_primsugr"}),
    ],
    "临床分期": [
        ("原发肿瘤与临床淋巴结", {"primary_site_clinical", "primary_tumor_side", "node_number_c", "largest_node_size_image_cm_c", "largest_node_size_exam_cm_c", "positive_nodal_side_c", "nodal_laterality_c", "clinical_ene_raw"}),
        ("TNM 与 AJCC 分期", {"ajcc_version_c", "ct", "cn", "cm", "ajcc_version_p", "pt", "pn", "m", "ajcc_stage"}),
    ],
    "初始病理": [
        ("肿瘤与侵袭特征", {"histologic_grade_1_primsugr", "hpv_association_p16_1_primsugr", "histologic_type_1_primsugr", "pathologic_tumor_size_1_primsugr", "doi_p_1_primsugr", "pni_1_primsugr", "lymphovascular_invasion_1_primsugr", "lymphatic_invasion_1_primsugr", "vascular_invasion_1_primsugr", "margins_status_1_primsugr", "wpoi"}),
        ("淋巴结与结外侵犯", {"positive_nodes_flag_1_primsugr", "positive_nodes_count_1_primsugr", "nodes_examined_1_primsugr", "ene_p_1_primsugr", "ene_c_1_primsugr"}),
    ],
    "随访与结局": [
        ("生存与随访", {"last_followup_date_1", "last_status_1", "survival_status_1", "death_date_1", "death_cause_1"}),
        ("复发、转移与进展", {"recurrence_1_1", "recurrence_type_1_1", "recurrence_date_1_1", "recurrence_1_2", "distant_metastasis_1_1", "distant_metastasis_date_1_1", "distant_metastasis_site_1_1", "progress_1_1", "date_of_progress_1_1"}),
    ],
}


def form_groups(title: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Subdivide dense clinical sections into the order in which they are entered."""
    remaining = {field["name"]: field for field in fields}
    groups = []
    for group_title, names in FORM_SECTION_GROUPS.get(title, []):
        group_fields = [field for field in fields if field["name"] in names]
        if group_fields:
            groups.append({"title": group_title, "fields": group_fields})
            for field in group_fields:
                remaining.pop(field["name"], None)
    if remaining:
        groups.append({"title": "其他字段" if groups else None, "fields": [field for field in fields if field["name"] in remaining]})
    return groups


@lru_cache
def dataset_schema() -> dict[str, Any]:
    return json.loads(Path(settings.schema_path).read_text(encoding="utf-8"))


@lru_cache
def field_catalog() -> tuple[dict[str, Any], ...]:
    """Load human labels and types from the versioned formal data package."""
    package = json.loads(Path(settings.dataset_path).read_text(encoding="utf-8"))
    return tuple(package["data_dictionary"])


def blank_record(subject_id: str) -> dict[str, Any]:
    record = {field["name"]: None for field in field_catalog()}
    record["subject_id"] = subject_id
    return record


def record_from_form(form: dict[str, str], subject_id: str) -> dict[str, Any]:
    """Convert a human-facing form into the typed JSON record validated below."""
    record = blank_record(subject_id)
    for field in field_catalog():
        name, data_type = field["name"], field["data_type"]
        if name == "subject_id":
            continue
        raw = form.get(f"field_{name}", "").strip()
        if not raw:
            record[name] = None
        elif data_type == "integer":
            record[name] = int(raw)
        elif data_type == "number":
            record[name] = float(raw)
        else:
            record[name] = raw
    return record


def record_sections(record: dict[str, Any], include_empty: bool) -> list[dict[str, Any]]:
    """Group 104 fields into clinically readable sections for display and editing."""
    groups = [
        ("患者与诊断", {"subject_id", "cohort_year", "specimen_pathology_number", "nrm", "age_at_initial_diagnosis", "diagnosis_date", "sex"}),
        ("生活方式与合并症", {"smoking_status", "alcohol_status", "comorbidities", "cci", "ace_27", "cardiovascular_grade", "respiratory_grade", "gastrointestinal_grade", "renal_grade", "endocrine_grade", "neurologic_grade", "psychiatric_grade", "rheumatologic_grade", "immunologic_grade", "malignancy_grade", "substance_abuse_grade", "obesity_bmi_grade"}),
        ("临床分期", {"primary_site_clinical", "primary_tumor_side", "node_number_c", "largest_node_size_image_cm_c", "largest_node_size_exam_cm_c", "positive_nodal_side_c", "nodal_laterality_c", "clinical_ene_raw", "ajcc_version_c", "ct", "cn", "cm", "ajcc_version_p", "pt", "pn", "m", "ajcc_stage"}),
        ("初始手术", {"episode_1_neoadj", "tx_start_date_1_neoadj", "tx_class_1_neoadj", "episode_1_primsug", "treatment_intent_1_primsugr", "used_primarysurgery_1_primsugr", "date_of_primarysurgery_1_primsugr", "used_neckdissection_1_primsugr", "date_of_neckdissection_1_primsugr", "neck_dissection_type_1_primsugr", "neck_dissection_intent_total_1_primsugr", "neck_dissection_intent_left_1_primsugr", "neck_dissection_intent_right_1_primsugr", "neck_dissection_laterality_1_primsugr", "neck_dissection_levels_left_1_primsugr", "neck_dissection_levels_right_1_primsugr", "neck_dissection_parotid_1_primsugr", "tracheostomy_1_primsugr"}),
        ("初始病理", {"histologic_grade_1_primsugr", "hpv_association_p16_1_primsugr", "histologic_type_1_primsugr", "pathologic_tumor_size_1_primsugr", "doi_p_1_primsugr", "pni_1_primsugr", "lymphovascular_invasion_1_primsugr", "lymphatic_invasion_1_primsugr", "vascular_invasion_1_primsugr", "margins_status_1_primsugr", "wpoi", "positive_nodes_flag_1_primsugr", "positive_nodes_count_1_primsugr", "nodes_examined_1_primsugr", "ene_p_1_primsugr", "ene_c_1_primsugr"}),
        ("辅助与挽救治疗", {"episode_1_adj", "date_of_adj_1_primsugr", "tx_class_1_adj", "episode_1_salvage", "disease_contex_1_salvage", "tx_start_date_1_salvage", "tx_class_1_salvage"}),
        ("随访与结局", {"last_followup_date_1", "last_status_1", "survival_status_1", "death_date_1", "death_cause_1", "recurrence_1_1", "recurrence_type_1_1", "recurrence_date_1_1", "recurrence_1_2", "distant_metastasis_1_1", "distant_metastasis_date_1_1", "distant_metastasis_site_1_1", "progress_1_1", "date_of_progress_1_1"}),
    ]
    catalog = {field["name"]: dict(field) for field in field_catalog()}
    assigned: set[str] = set()
    sections = []
    for title, names in groups:
        rows = []
        for name in (field["name"] for field in field_catalog() if field["name"] in names):
            value = record.get(name)
            if include_empty or value is not None:
                field = catalog[name]
                display_label = DISPLAY_LABEL_OVERRIDES.get(name, field["label"])
                field["label"] = display_label
                field["display_label"] = f"{display_label}（{name}）"
                field["options"], field["option_source"], field["option_notice"] = form_control(field, value)
                field.update({"value": value, "multiline": name.startswith("notes_") or name in {"comorbidities", "death_cause_1"}})
                rows.append(field)
            assigned.add(name)
        if rows:
            sections.append({"title": title, "fields": rows, "form_groups": form_groups(title, rows)})
    other = []
    for field in field_catalog():
        if field["name"] in assigned:
            continue
        value = record.get(field["name"])
        if include_empty or value is not None:
            item = dict(field)
            display_label = DISPLAY_LABEL_OVERRIDES.get(item["name"], item["label"])
            item["label"] = display_label
            item["display_label"] = f"{display_label}（{item['name']}）"
            item["options"], item["option_source"], item["option_notice"] = form_control(item, value)
            item.update({"value": value, "multiline": item["name"].startswith("notes_")})
            other.append(item)
    if other:
        sections.append({"title": "备注与其他字段", "fields": other, "form_groups": form_groups("备注与其他字段", other)})
    return sections


def validate_record(record: dict[str, Any]) -> None:
    schema = dataset_schema()
    record_schema = schema["$defs"]["record"]
    errors = list(Draft202012Validator(record_schema, format_checker=FormatChecker()).iter_errors(record))
    if errors:
        messages = "; ".join(error.message for error in errors[:3])
        raise ValueError(messages)


def core_values(record: dict[str, Any]) -> dict[str, Any]:
    diagnosis_date = record.get("diagnosis_date")
    return {
        "subject_id": record["subject_id"],
        "cohort_year": record.get("cohort_year"),
        "age_at_diagnosis": record.get("age_at_initial_diagnosis"),
        "sex": record.get("sex"),
        "diagnosis_date": date.fromisoformat(diagnosis_date) if diagnosis_date else None,
        "primary_site": record.get("primary_site_clinical"),
        "ajcc_stage": record.get("ajcc_stage"),
        "survival_status": record.get("survival_status_1"),
    }


def upsert_patient(db: Session, record: dict[str, Any], source_version: str, actor_id: int | None, remote_addr: str | None) -> Patient:
    validate_record(record)
    core = core_values(record)
    patient = db.query(Patient).filter(Patient.subject_id == record["subject_id"]).one_or_none()
    before = patient.record_data.copy() if patient else None
    action = "update" if patient else "create"
    if patient is None:
        patient = Patient(**core, record_data=record, source_version=source_version)
        db.add(patient)
    else:
        for key, value in core.items():
            setattr(patient, key, value)
        patient.record_data = record
        patient.source_version = source_version
    db.flush()
    db.add(AuditLog(actor_id=actor_id, action=action, entity_id=record["subject_id"], before_data=before, after_data=record, remote_addr=remote_addr))
    return patient


def restore_patient_from_audit(db: Session, audit_id: int, actor_id: int | None, remote_addr: str | None) -> Patient | None:
    """Restore exactly the pre-change state of one audit event and append a new audit event."""
    event = db.get(AuditLog, audit_id)
    if event is None or event.entity_type != "patient":
        raise ValueError("未找到可恢复的患者审计记录。")
    current = db.query(Patient).filter(Patient.subject_id == event.entity_id).one_or_none()
    if event.before_data is None:
        if current is None:
            raise ValueError("该创建事件对应的患者已不存在，无需回退。")
        before = current.record_data.copy()
        db.delete(current)
        db.flush()
        db.add(AuditLog(actor_id=actor_id, action="rollback_delete", entity_id=event.entity_id, before_data=before, after_data=None, remote_addr=remote_addr))
        return None
    record = event.before_data.copy()
    validate_record(record)
    core = core_values(record)
    before = current.record_data.copy() if current else None
    if current is None:
        current = Patient(**core, record_data=record, source_version="audit-restore")
        db.add(current)
    else:
        for key, value in core.items():
            setattr(current, key, value)
        current.record_data = record
        current.source_version = "audit-restore"
    db.flush()
    db.add(AuditLog(actor_id=actor_id, action="rollback_restore", entity_id=event.entity_id, before_data=before, after_data=record, remote_addr=remote_addr))
    return current
