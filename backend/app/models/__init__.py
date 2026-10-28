"""ORM models.

Importing this package registers every model on ``Base.metadata``, which is
what Alembic autogenerate and the test fixtures' ``create_all`` both rely on.
"""
from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.business import Business, BusinessPlan
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.models.invoice import Invoice, InvoiceSource, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import (
    MatchCategory,
    ReconciliationRun,
    ReconciliationStatus,
)
from app.models.referral import Referral
from app.models.report_purchase import ReportPurchase
from app.models.subscriber import Subscriber
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.models.subscription_payment import SubscriptionPayment
from app.models.supplier import RiskLevel, Supplier
from app.models.usage import UsageRecord
from app.models.user import User, UserRole

__all__ = [
    "Alert",
    "AlertSeverity",
    "AlertStatus",
    "AlertType",
    "Business",
    "BusinessMembership",
    "BusinessPlan",
    "GSTRReturn",
    "Invoice",
    "InvoiceSource",
    "InvoiceStatus",
    "InvoiceType",
    "MatchCategory",
    "MembershipRole",
    "ReconciliationRun",
    "ReconciliationStatus",
    "Referral",
    "ReportPurchase",
    "ReturnStatus",
    "ReturnType",
    "RiskLevel",
    "Subscriber",
    "Supplier",
    "Subscription",
    "SubscriptionPayment",
    "SubscriptionStatus",
    "SubscriptionTier",
    "UsageRecord",
    "User",
    "UserRole",
]
