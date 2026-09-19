from django.urls import path

from . import web_views

urlpatterns = [
    path("", web_views.dashboard, name="dashboard"),
    path("benchmarks/", web_views.benchmark_list, name="benchmark-list"),
    path("benchmarks/create", web_views.benchmark_create, name="benchmark-create"),
    path("benchmarks/<int:benchmark_id>/", web_views.benchmark_detail, name="benchmark-detail"),
    path(
        "benchmarks/<int:benchmark_id>/cases/<int:case_id>",
        web_views.benchmark_case_update,
        name="benchmark-case-update",
    ),
    path("runs/create", web_views.create_run, name="web-run-create"),
    path("runs/<int:run_id>/", web_views.run_detail, name="web-run-detail"),
]
