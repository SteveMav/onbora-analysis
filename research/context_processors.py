from .permissions import has_role


def onbora_navigation(request):
    return {
        "can_run_benchmarks": has_role(request.user, "reviewer", "operator", "admin"),
    }
