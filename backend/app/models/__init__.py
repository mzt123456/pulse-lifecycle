"""ORM 模型。导入本包即注册全部表，Alembic 自动生成迁移时依赖这里。"""

from app.models.consumable import Consumable, ConsumableUsage
from app.models.equipment import Component, Equipment, EquipmentStatusLog
from app.models.fault import FaultRecord
from app.models.maintenance import MaintenanceOrder, MaintenanceStep
from app.models.operation import MeasurementRecord, WellOperation
from app.models.system import Attachment, AuditLog, BackupRecord, DictItem, License
from app.models.user import (
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserPreference,
    UserRole,
)

__all__ = [
    "Attachment",
    "AuditLog",
    "BackupRecord",
    "Component",
    "Consumable",
    "ConsumableUsage",
    "DictItem",
    "Equipment",
    "EquipmentStatusLog",
    "FaultRecord",
    "License",
    "MaintenanceOrder",
    "MaintenanceStep",
    "MeasurementRecord",
    "Permission",
    "RefreshToken",
    "Role",
    "RolePermission",
    "User",
    "UserPreference",
    "UserRole",
    "WellOperation",
]
