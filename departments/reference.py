"""Default departments and categories (idempotent). Used by the seed command and tests."""
from .models import Category, Department

DEPARTMENTS = [
    ("Roads Department", "Road repair, potholes and street surfaces.", "roads@civicfix.example", "080-5550-0101", "A. Rao"),
    ("Sanitation Department", "Waste collection, dumping and street cleanliness.", "sanitation@civicfix.example", "080-5550-0102", "S. Nair"),
    ("Electrical Services", "Streetlights and public electrical safety.", "electrical@civicfix.example", "080-5550-0103", "M. Iyer"),
    ("Water Services", "Water supply, pipes and leakage.", "water@civicfix.example", "080-5550-0104", "R. Das"),
    ("Drainage Department", "Storm drains, sewage and manholes.", "drainage@civicfix.example", "080-5550-0105", "P. Menon"),
    ("Traffic Management Department", "Traffic signals, crossings and signage.", "traffic@civicfix.example", "080-5550-0106", "K. Singh"),
    ("Parks and Public Spaces Department", "Parks, playgrounds and public spaces.", "parks@civicfix.example", "080-5550-0107", "L. Gowda"),
    ("General Review Department", "Triage for unclear or uncategorised complaints.", "review@civicfix.example", "080-5550-0108", "V. Shetty"),
]
# slug, name, department, severity, SLA hours, icon, description
CATEGORIES = [
    ("pothole", "Pothole or road damage", "Roads Department", "HIGH", 168, "bi-cone-striped", "Potholes, cracks and broken road surfaces."),
    ("garbage", "Garbage or waste overflow", "Sanitation Department", "MEDIUM", 48, "bi-trash", "Overflowing bins and uncollected waste."),
    ("streetlight", "Broken streetlight", "Electrical Services", "MEDIUM", 72, "bi-lightbulb", "Streetlights that are off, dim or flickering."),
    ("water", "Water leakage", "Water Services", "HIGH", 48, "bi-droplet", "Leaking pipes and burst water mains."),
    ("drain", "Blocked drain", "Drainage Department", "HIGH", 48, "bi-water", "Blocked drains, sewage and open manholes."),
    ("footpath", "Damaged footpath", "Roads Department", "MEDIUM", 168, "bi-signpost-split", "Broken or uneven pavements."),
    ("traffic", "Traffic signal issue", "Traffic Management Department", "HIGH", 48, "bi-sign-stop", "Signals that are off or stuck."),
    ("animal", "Stray animal issue", "General Review Department", "MEDIUM", 120, "bi-bug", "Stray animals causing problems."),
    ("dumping", "Illegal dumping", "Sanitation Department", "MEDIUM", 72, "bi-boxes", "Dumped debris or waste."),
    ("safety", "Public safety concern", "General Review Department", "CRITICAL", 24, "bi-shield-exclamation", "Hazards that put people at risk."),
    ("park", "Park or public-space damage", "Parks and Public Spaces Department", "LOW", 240, "bi-tree", "Damaged benches, play equipment and gardens."),
    ("other", "Other", "General Review Department", "LOW", 240, "bi-three-dots", "Anything else."),
]


def ensure_reference_data():
    depts = {}
    for name, desc, email, phone, head in DEPARTMENTS:
        depts[name], _ = Department.objects.get_or_create(name=name, defaults=dict(
            description=desc, email=email, phone=phone, department_head=head))
    cats = {}
    for slug, name, dept, sev, sla, icon, desc in CATEGORIES:
        cats[slug], _ = Category.objects.get_or_create(slug=slug, defaults=dict(
            name=name, department=depts[dept], default_severity=sev, sla_hours=sla, icon=icon, description=desc))
    return depts, cats
