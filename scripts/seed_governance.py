# scripts/seed_governance.py
from app.extensions import db
from app.slices.governance.models import (
    CanonicalState,
    RoleCode,
    ServiceClassification,
)

US_STATES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
    ("DC", "District of Columbia"),
]

SERVICE_CLASSES = [
    ("food", "Food & Meals", 10),
    ("shelter", "Shelter", 20),
    ("medical", "Medical", 30),
    ("education", "Education", 40),
]


DOMAIN_ROLES = [
    ("customer", "Customer domain actor"),
    ("resource", "Resource domain actor"),
    ("sponsor", "Sponsor domain actor"),
    ("governor", "Governance domain actor"),
]


def upsert(model, **kw):
    row = model.query.filter_by(
        **{k: kw[k] for k in kw if k in ("code",)}
    ).one_or_none()
    if not row:
        row = model(**kw)
        db.session.add(row)
    else:
        for k, v in kw.items():
            setattr(row, k, v)
    return row


def run():
    for code, name in US_STATES:
        upsert(CanonicalState, code=code, name=name, is_active=True)
    for code, label, sort in SERVICE_CLASSES:
        upsert(
            ServiceClassification,
            code=code,
            label=label,
            sort=sort,
            is_active=True,
        )
    for code, desc in DOMAIN_ROLES:
        upsert(RoleCode, code=code, description=desc, is_active=True)
    db.session.commit()
    print("governance canonicals seeded")
    print(
        "domain_roles:",
        [r.code for r in RoleCode.query.order_by(RoleCode.code).all()],
    )
