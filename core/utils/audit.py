from apps.audit.models import AuditLog


def log_action(request, action, entity, entity_id, metadata=None):
    AuditLog.objects.create(
        tenant_id=request.tenant_id,
        user=request.user if request.user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        metadata=metadata or {},
    )
