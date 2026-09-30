from .permissions import has_role


def onbora_navigation(request):
    return {
        "can_multi_search": has_role(request.user, "kam", "operator", "admin"),
        "can_run_benchmarks": has_role(request.user, "reviewer", "operator", "admin"),
    }
