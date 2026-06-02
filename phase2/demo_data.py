"""演示数据初始快照（phase2 运行前重置用）"""

INITIAL_SUPPLIERS = [
    {
        "pk": "S-ACME-001",
        "name": "ACME 精密部件有限公司",
        "status": "active",
        "credit_limit": 500000,
        "outstanding_amount": 180000,
        "contract_status": "valid",
        "contract_expiry": "2026-12-31",
    },
    {
        "pk": "S-BETA-002",
        "name": "Beta 工业材料供应商",
        "status": "active",
        "credit_limit": 300000,
        "outstanding_amount": 120000,
        "contract_status": "valid",
        "contract_expiry": "2027-03-15",
    },
    {
        "pk": "S-GAMMA-003",
        "name": "Gamma 化工原料",
        "status": "active",
        "credit_limit": 300000,
        "outstanding_amount": 280000,
        "contract_status": "valid",
        "contract_expiry": "2027-06-30",
    },
]

INITIAL_CERTIFICATIONS = [
    {
        "pk": "CERT-001",
        "supplier_pk": "S-ACME-001",
        "cert_type": "ISO-9001",
        "issue_date": "2024-06-01",
        "expiry_date": "2027-06-01",
        "days_remaining": 365,
    },
    {
        "pk": "CERT-002",
        "supplier_pk": "S-BETA-002",
        "cert_type": "ISO-9001",
        "issue_date": "2025-05-01",
        "expiry_date": "2026-06-12",
        "days_remaining": 13,
    },
    {
        "pk": "CERT-003",
        "supplier_pk": "S-GAMMA-003",
        "cert_type": "ISO-14001",
        "issue_date": "2025-12-01",
        "expiry_date": "2026-06-08",
        "days_remaining": 8,
    },
]
