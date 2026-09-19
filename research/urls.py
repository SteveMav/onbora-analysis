from django.urls import path

from . import views

urlpatterns = [
    path("research-runs", views.create_research_run, name="research-run-create"),
    path("research-runs/<int:run_id>", views.get_research_run, name="research-run-detail"),
    path("research-runs/<int:run_id>/cancel", views.cancel_research_run, name="research-run-cancel"),
]
