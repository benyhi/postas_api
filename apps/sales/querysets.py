from datetime import datetime, time, timedelta

from django.utils import timezone


def filter_by_local_dates(queryset, *, field_name: str, date_from=None, date_to=None):
    """Apply inclusive local dates as a sargable [start, next-day) datetime range."""
    filters = {}
    current_timezone = timezone.get_current_timezone()
    if date_from is not None:
        filters[f"{field_name}__gte"] = timezone.make_aware(
            datetime.combine(date_from, time.min),
            current_timezone,
        )
    if date_to is not None:
        filters[f"{field_name}__lt"] = timezone.make_aware(
            datetime.combine(date_to + timedelta(days=1), time.min),
            current_timezone,
        )
    return queryset.filter(**filters)
