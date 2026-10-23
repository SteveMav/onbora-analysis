from django.urls import path

from . import multi_search, serpapi_views, web_views

urlpatterns = [
    path("", web_views.dashboard, name="dashboard"),
    path("serpapi/", serpapi_views.search_page, name="serpapi-search"),
    path("serpapi/create", serpapi_views.create, name="serpapi-create"),
    path("serpapi/<int:search_id>/export/<str:format>/", serpapi_views.export, name="serpapi-export"),
    path("multi-search/", multi_search.selection, name="multi-search"),
    path("multi-search/create", multi_search.create, name="multi-search-create"),
    path("multi-search/<int:batch_id>/", multi_search.detail, name="multi-search-detail"),
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
