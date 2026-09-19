from django.contrib.auth.models import AbstractBaseUser


ROLE_GROUPS = {"kam", "reviewer", "operator", "admin"}


def has_role(user: AbstractBaseUser, *roles: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=set(roles) & ROLE_GROUPS).exists()


def can_view_run(user: AbstractBaseUser, run) -> bool:
    return has_role(user, "operator", "reviewer", "admin") or (
        has_role(user, "kam") and run.requested_by_id == user.id
    )
