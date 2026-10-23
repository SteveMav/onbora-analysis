import csv
import io
import json
import uuid
from threading import Barrier
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, SimpleTestCase, TestCase, override_settings

from research import serpapi
from research.models import ArspImport, ArspRecord, ResearchRun, SerpApiSearch
from research.serpapi_views import SearchForm


@override_settings(ONBORA_SERPAPI_API_KEY="test-private-secret")
class SerpApiProviderTests(SimpleTestCase):
    def opener(self, payload):
        mocked = MagicMock()
        mocked.open.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return mocked

    @patch("research.serpapi.build_opener")
    def test_fixed_endpoint_one_request_bounded_response_and_no_secret_in_report(self, build):
        build.return_value = self.opener({
            "search_metadata": {"id": "test-search", "status": "Success", "json_endpoint": "secret"},
            "search_parameters": {"api_key": "test-private-secret"},
            "organic_results": [{"title": "Example", "link": "https://example.com", "snippet": "test-private-secret"}],
        })
        parameters = {"engine": "google", "q": "sociétés Kinshasa", "hl": "fr", "gl": "cd", "no_cache": "false"}
        report = serpapi.search(parameters)
        build.return_value.open.assert_called_once()
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(urlsplit(request.full_url).netloc, "serpapi.com")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)["api_key"], ["test-private-secret"])
        build.return_value.open.return_value.__enter__.return_value.read.assert_called_once_with(serpapi.MAX_BYTES + 1)
        self.assertEqual(report["result_count"], 1)
        self.assertEqual(report["request_count"], 1)
        self.assertNotIn("test-private-secret", json.dumps(report))
        self.assertNotIn("json_endpoint", report)

    def test_google_keeps_organic_knowledge_graph_and_local_pack(self):
        results = serpapi.normalize_results({
            "organic_results": [{"title": "Entreprise", "link": "https://example.com", "snippet": "Activités"}],
            "knowledge_graph": {"title": "Entreprise", "website": "https://example.org", "description": "Profil"},
            "local_results": {"places": [{"title": "Agence", "address": "Kinshasa", "phone": "+243 123"}]},
            "ads": [{"title": "Ad", "link": "https://ad.example"}],
        }, "google")
        self.assertEqual([r["kind"] for r in results], ["Page web", "Fiche Google", "Établissement"])

    def test_maps_preserves_branches_and_deduplicates_place_ids(self):
        items = [{"title": "Agence", "place_id": place, "website": "https://example.com", "address": address}
                 for place, address in (("place-1", "Gombe"), ("place-2", "Limete"), ("place-1", "Gombe"))]
        results = serpapi.normalize_results({"local_results": items}, "google_maps")
        self.assertEqual(len(results), 2)
        self.assertIn("query_place_id=place-1", results[0]["url"])

    def test_news_flattens_stories_and_highlight_without_duplicates(self):
        article = {"title": "Nouveau projet", "link": "https://example.com/news", "source": {"name": "Journal"}, "date": "today"}
        results = serpapi.normalize_results({"news_results": [{"title": "Cluster", "highlight": article, "stories": [article, {"title": "Ouverture", "link": "https://example.org/news"}]}]}, "google_news")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["source"], "Journal")

    def test_unsafe_credential_and_api_links_are_never_returned(self):
        bad = ["javascript:alert(1)", "https://user:pass@example.com", "https://serpapi.com/search?api_key=x", "https://example.com?api_key=x", "https://example.com/test-private-secret", "https://example.com/\n"]
        results = serpapi.normalize_results({"organic_results": [{"title": "Unsafe", "link": link} for link in bad]}, "google")
        self.assertEqual(results, [])

    def test_malformed_results_and_limit(self):
        self.assertEqual(serpapi.normalize_results({"organic_results": {"invalid": 1}}, "google"), [])
        data = {"organic_results": [None, {}, {"title": ["invalid"]}] + [{"title": f"Page {n}", "link": f"https://example.com/{n}"} for n in range(80)]}
        self.assertEqual(len(serpapi.normalize_results(data, "google")), 50)

    @patch("research.serpapi.build_opener")
    def test_account_filters_key_email_and_account_identifier(self, build):
        build.return_value = self.opener({"api_key": "test-private-secret", "account_email": "private@example.com", "account_id": "private", "total_searches_left": 0, "this_month_usage": 250, "plan_name": "Free"})
        self.assertEqual(serpapi.account(), {"total_searches_left": 0, "this_month_usage": 250})

    @patch("research.serpapi.build_opener")
    def test_http_errors_are_actionable_redacted_and_not_retried(self, build):
        for status, expected in ((400, "Requête"), (401, "invalide"), (403, "refusé"), (429, "Quota"), (500, "indisponible"), (302, "indisponible")):
            with self.subTest(status=status):
                build.return_value.open.reset_mock()
                build.return_value.open.side_effect = HTTPError("https://serpapi.com/?api_key=test-private-secret", status, "test-private-secret", {}, None)
                with self.assertRaises(serpapi.SerpApiError) as caught:
                    serpapi.search({"engine": "google"})
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn("test-private-secret", str(caught.exception))
                build.return_value.open.assert_called_once()

    @patch("research.serpapi.build_opener")
    def test_invalid_oversized_empty_and_vendor_errors(self, build):
        for payload in (b"not json", b"x" * (serpapi.MAX_BYTES + 1), b"[]", b'{"error":"test-private-secret"}', b'{"search_metadata":{"status":"Processing"}}'):
            with self.subTest(payload=payload[:60]):
                mocked = self.opener({})
                mocked.open.return_value.__enter__.return_value.read.return_value = payload
                build.return_value = mocked
                with self.assertRaises(serpapi.SerpApiError) as caught:
                    serpapi.search({"engine": "google"})
                self.assertNotIn("test-private-secret", str(caught.exception))
        build.return_value.open.side_effect = URLError("test-private-secret")
        with self.assertRaisesMessage(serpapi.SerpApiError, "réseau"):
            serpapi.search({"engine": "google"})

    @override_settings(ONBORA_SERPAPI_API_KEY="")
    @patch("research.serpapi.build_opener")
    def test_missing_key_never_calls_network(self, build):
        with self.assertRaisesMessage(serpapi.SerpApiError, "SERPAPI_API_KEY"):
            serpapi.search({"engine": "google"})
        build.assert_not_called()

    @patch("research.serpapi.build_opener")
    def test_successful_search_with_no_matches_is_an_empty_report(self, build):
        build.return_value = self.opener({"search_metadata": {"status": "Success"}, "error": "Google hasn't returned any results for this query."})
        self.assertEqual(serpapi.search({"engine": "google"})["result_count"], 0)


@override_settings(ONBORA_SERPAPI_API_KEY="test-private-secret")
class SerpApiPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester")
        self.user.groups.add(Group.objects.create(name="kam"))
        self.client.force_login(self.user)

    def payload(self, **updates):
        return {"submission_id": str(uuid.uuid4()), "scenario": "discovery", "engine": "google_maps", "query": "logistique Kinshasa RDC", "language": "fr", "country": "cd", "coordinates": "", **updates}

    def report(self):
        return {"provider": "serpapi", "result_count": 1, "request_count": 1, "elapsed_seconds": 0.5, "results": [{"kind": "Établissement", "title": '<script>alert("x")</script>', "url": "https://example.com", "website": "https://example.com", "address": "Kinshasa", "phone": "+243 123", "snippet": "Extrait", "source": "example.com"}]}

    @patch("research.serpapi_views.serpapi.search")
    @patch("research.serpapi_views.serpapi.account")
    def test_page_navigation_and_get_have_no_api_side_effects(self, account, search):
        response = self.client.get("/serpapi/")
        self.assertContains(response, "Recherche SerpApi")
        self.assertContains(response, "Actualités et projets")
        self.assertContains(self.client.get("/"), 'href="/serpapi/"')
        account.assert_not_called()
        search.assert_not_called()

    @patch("research.serpapi_views.serpapi.search")
    def test_creation_refresh_and_duplicate_submission_only_call_once(self, search):
        search.return_value = self.report()
        payload = self.payload()
        first = self.client.post("/serpapi/create", payload)
        second = self.client.post("/serpapi/create", payload)
        self.assertEqual(first.url, second.url)
        page = self.client.get(first.url)
        self.assertContains(page, "Exporter CSV")
        self.assertNotContains(page, '<script>alert("x")</script>')
        self.assertContains(page, "Comparer ce nom à la base ARSP")
        self.assertEqual(SerpApiSearch.objects.count(), 1)
        self.assertEqual(ResearchRun.objects.count(), 0)
        search.assert_called_once_with({"engine": "google_maps", "q": payload["query"], "hl": "fr", "type": "search", "no_cache": "false"})

    @patch("research.serpapi_views.serpapi.search")
    def test_news_web_and_maps_use_engine_specific_parameters(self, search):
        search.return_value = self.report()
        for engine in ("google", "google_news", "google_maps"):
            self.client.post("/serpapi/create", self.payload(engine=engine, coordinates="@-4.3,15.3,14z"))
            parameters = search.call_args.args[0]
            if engine == "google_maps":
                self.assertEqual(parameters["ll"], "@-4.3,15.3,14z")
                self.assertNotIn("gl", parameters)
            else:
                self.assertEqual(parameters["gl"], "cd")
                self.assertNotIn("ll", parameters)
                self.assertNotIn("type", parameters)

    @patch("research.serpapi_views.serpapi.search")
    def test_invalid_form_does_not_consume_api(self, search):
        for changes in ({"query": ""}, {"engine": "bing"}, {"submission_id": "bad"}, {"coordinates": "@999,0,14z"}, {"coordinates": "@0,0,31z"}, {"query": "a" * 501}):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post("/serpapi/create", self.payload(**changes)).status_code, 200)
        self.assertEqual(SerpApiSearch.objects.count(), 0)
        search.assert_not_called()

    @override_settings(ONBORA_SERPAPI_API_KEY="")
    @patch("research.serpapi_views.serpapi.search")
    def test_missing_configuration_is_visible_and_blocks_post(self, search):
        self.assertContains(self.client.get("/serpapi/"), "Clé SerpApi à configurer")
        self.assertContains(self.client.post("/serpapi/create", self.payload()), "SERPAPI_API_KEY")
        self.assertEqual(SerpApiSearch.objects.count(), 0)
        search.assert_not_called()

    @patch("research.serpapi_views.serpapi.search", side_effect=serpapi.SerpApiError("Quota épuisé"))
    def test_failure_is_persisted_and_refresh_does_not_retry(self, search):
        response = self.client.post("/serpapi/create", self.payload())
        self.assertContains(self.client.get(response.url), "Quota épuisé")
        self.assertEqual(SerpApiSearch.objects.get().state, "failed")
        search.assert_called_once()

    @patch("research.serpapi_views.serpapi.account", return_value={"total_searches_left": 0, "this_month_usage": 250, "searches_per_month": 250})
    def test_explicit_quota_check_displays_zero_without_saving_account(self, account):
        response = self.client.post("/serpapi/", {"action": "account"})
        self.assertContains(response, "<strong>0</strong>", html=True)
        self.assertEqual(SerpApiSearch.objects.count(), 0)
        account.assert_called_once()

    def test_anonymous_and_disallowed_roles_cannot_search_or_export(self):
        self.client.logout()
        self.assertEqual(self.client.get("/serpapi/").status_code, 302)
        for role in (None, "reviewer"):
            user = get_user_model().objects.create_user(username=f"denied-{role}")
            if role:
                user.groups.add(Group.objects.create(name=role))
            self.client.force_login(user)
            self.assertEqual(self.client.get("/serpapi/").status_code, 404)
            self.assertEqual(self.client.post("/serpapi/create", self.payload()).status_code, 404)
            self.assertEqual(self.client.post("/serpapi/", {"action": "account"}).status_code, 404)
            self.assertEqual(self.client.get("/serpapi/1/export/json/").status_code, 404)

    @patch("research.serpapi_views.serpapi.search")
    def test_owner_only_history_detail_export_and_submission(self, search):
        search.return_value = self.report()
        payload = self.payload()
        response = self.client.post("/serpapi/create", payload)
        run = SerpApiSearch.objects.get()
        other = get_user_model().objects.create_user(username="other")
        other.groups.add(Group.objects.get(name="kam"))
        self.client.force_login(other)
        self.assertNotContains(self.client.get("/serpapi/"), payload["query"])
        self.assertEqual(self.client.get(response.url).status_code, 404)
        self.assertEqual(self.client.get(f"/serpapi/{run.pk}/export/json/").status_code, 404)
        self.assertEqual(self.client.post("/serpapi/create", payload).status_code, 404)
        search.assert_called_once()

    def test_csrf_and_methods(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post("/serpapi/create", self.payload()).status_code, 403)
        self.assertEqual(self.client.get("/serpapi/create").status_code, 405)
        self.assertEqual(self.client.post("/serpapi/1/export/json/").status_code, 405)

    def test_export_is_read_only_utf8_and_csv_formula_safe(self):
        run = SerpApiSearch.objects.create(requested_by=self.user, scenario="discovery", query="=1+1", engine="google_maps", state="complete", report=self.report())
        export = self.client.get(f"/serpapi/{run.pk}/export/json/")
        self.assertEqual(export.json()["query"], "=1+1")
        csv_export = self.client.get(f"/serpapi/{run.pk}/export/csv/")
        rows = list(csv.reader(io.StringIO(csv_export.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1][0], "'=1+1")
        self.assertIn("'+243 123", rows[1])
        self.assertEqual(csv_export["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(f"/serpapi/{run.pk}/export/xml/").status_code, 404)

    def test_operators_and_admins_have_access(self):
        for role in ("operator", "admin"):
            user = get_user_model().objects.create_user(username=role)
            user.groups.add(Group.objects.create(name=role))
            self.client.force_login(user)
            self.assertEqual(self.client.get("/serpapi/").status_code, 200)

    def test_bad_search_identifier_returns_404(self):
        self.assertEqual(self.client.get("/serpapi/?search=invalid").status_code, 404)

    @patch("research.serpapi._request")
    def test_combined_search_three_calls_history_exports_and_duplicate_protection(self, request):
        def response(path, params):
            engine = params["engine"]
            key = {"google": "organic_results", "google_maps": "local_results", "google_news": "news_results"}[engine]
            return {"search_metadata": {"status": "Success", "id": engine}, key: [{
                "title": f"Entreprise {engine}", "link": f"https://example.com/{engine}",
                "website": "https://example.com", "address": "Kinshasa", "phone": "+243 123",
            }]}
        request.side_effect = response
        payload = self.payload(engine="all", scenario="complete", coordinates="@-4.3,15.3,14z")
        response = self.client.post("/serpapi/create", payload)
        self.assertEqual(self.client.post("/serpapi/create", payload).url, response.url)
        self.assertEqual(request.call_count, 3)
        run = SerpApiSearch.objects.get()
        self.assertEqual(run.report["request_count"], 3)
        self.assertEqual(run.report["result_count"], 3)
        self.assertEqual(run.report["status"], "complete")
        self.assertEqual(run.report["successful_request_count"], 3)
        page = self.client.get(response.url)
        for label in ("Google Web", "Google Maps", "Google News", "3 appels API"):
            self.assertContains(page, label)
        self.assertEqual(len(page.context["result_sections"]), 3)
        self.assertEqual([len(section["results"]) for section in page.context["result_sections"]], [1, 1, 1])
        export = self.client.get(f"/serpapi/{run.pk}/export/json/").json()
        self.assertEqual(len(export["engines"]), 3)
        rows = list(csv.reader(io.StringIO(self.client.get(f"/serpapi/{run.pk}/export/csv/").content.decode("utf-8-sig"))))
        self.assertEqual({row[1] for row in rows[1:]}, {"google", "google_maps", "google_news"})
        self.assertEqual(self.client.get(response.url).context["form"].initial["engine"], "all")
        self.assertEqual(request.call_count, 3)

    @patch("research.serpapi._request")
    def test_combined_partial_failures_retain_results_and_are_exportable(self, request):
        def response(path, params):
            if params["engine"] == "google_news":
                raise serpapi.SerpApiError("Quota épuisé")
            key = "local_results" if params["engine"] == "google_maps" else "organic_results"
            return {key: [{"title": "Entreprise", "link": "https://example.com"}]}
        request.side_effect = response
        response = self.client.post("/serpapi/create", self.payload(engine="all", scenario="complete"))
        run = SerpApiSearch.objects.get()
        self.assertEqual(run.state, "complete")
        self.assertEqual(run.report["status"], "partial")
        self.assertEqual(run.report["successful_request_count"], 2)
        self.assertEqual(run.report["result_count"], 2)
        page = self.client.get(response.url)
        self.assertContains(page, "Résultats partiels")
        self.assertContains(page, "Quota épuisé")
        self.assertContains(page, "Entreprise")
        self.assertEqual(self.client.get(f"/serpapi/{run.pk}/export/json/").status_code, 200)
        self.assertEqual(request.call_count, 3)

    @patch("research.serpapi._request", side_effect=serpapi.SerpApiError("Réseau indisponible"))
    def test_combined_all_failures_are_reported_per_engine_without_retry(self, request):
        payload = self.payload(engine="all", scenario="complete")
        response = self.client.post("/serpapi/create", payload)
        self.client.post("/serpapi/create", payload)
        run = SerpApiSearch.objects.get()
        self.assertEqual(run.state, "failed")
        self.assertEqual(run.report["status"], "failed")
        self.assertEqual(len(run.report["engines"]), 3)
        self.assertContains(self.client.get(response.url), "Les trois moteurs ont échoué")
        self.assertEqual(request.call_count, 3)

    def test_new_form_defaults_to_three_engines_and_validates_maps_coordinates(self):
        form = self.client.get("/serpapi/").context["form"]
        self.assertEqual(form.initial["engine"], "all")
        self.assertEqual(form.initial["scenario"], "complete")
        self.assertFalse(SearchForm(self.payload(engine="all", coordinates="@999,0,14z")).is_valid())


@override_settings(ONBORA_SERPAPI_API_KEY="test-private-secret")
class SerpApiCombinedProviderTests(SimpleTestCase):
    @patch("research.serpapi._request")
    def test_engines_run_concurrently_with_only_their_supported_parameters(self, request):
        barrier = Barrier(3)
        def respond(path, params):
            barrier.wait(timeout=5)
            return {"search_metadata": {"status": "Success"}}
        request.side_effect = respond
        report = serpapi.search_all({"engine": "all", "q": "Rawbank RDC", "hl": "fr", "gl": "cd", "ll": "@-4.3,15.3,14z"})
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["result_count"], 0)
        self.assertEqual(request.call_count, 3)
        sent = {call.args[1]["engine"]: call.args[1] for call in request.call_args_list}
        self.assertEqual(set(sent), {"google", "google_maps", "google_news"})
        for engine, params in sent.items():
            self.assertEqual(params["q"], "Rawbank RDC")
            self.assertEqual(params["no_cache"], "false")
            if engine == "google_maps":
                self.assertEqual(params["ll"], "@-4.3,15.3,14z")
                self.assertEqual(params["type"], "search")
                self.assertNotIn("gl", params)
            else:
                self.assertEqual(params["gl"], "cd")
                self.assertNotIn("ll", params)
                self.assertNotIn("type", params)


@override_settings(ONBORA_SERPAPI_API_KEY="test-private-secret")
class SerpApiArspTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="arsp-tester")
        self.user.groups.add(Group.objects.create(name="kam"))
        self.client.force_login(self.user)
        self.imported = ArspImport.objects.create(file_name="active.xlsx", file_hash="a" * 64)
        self.record = ArspRecord.objects.create(
            arsp_import=self.imported, dossier_number="D-ARSP-01", legal_name="Alpha_x000D_ Logistics SARL",
            raw_data={"Province": "Kinshasa", "Nom Commercial": "Transport Rapide", "RCCM": "CD/KIN/RCCM-42"},
            normalized_data={},
        )

    def payload(self, **updates):
        return {
            "submission_id": str(uuid.uuid4()), "scenario": "complete", "engine": "all",
            "query": "Alpha Logistics Kinshasa RDC", "language": "fr", "country": "cd", "coordinates": "",
            "company_source": "arsp", "record_id": self.record.pk, **updates,
        }

    @patch("research.serpapi_views.serpapi.search_all")
    def test_local_picker_filters_name_trade_name_rccm_and_dossier_without_api_calls(self, search):
        for query in ("Alpha", "Transport Rapide", "RCCM-42", "D-ARSP-01"):
            with self.subTest(query=query):
                response = self.client.get("/serpapi/", {"company_source": "arsp", "arsp_q": query})
                self.assertContains(response, "Alpha Logistics SARL")
                self.assertEqual(response.context["company_source"], "arsp")
                self.assertEqual(list(response.context["arsp_page"]), [self.record])
        self.assertEqual(SerpApiSearch.objects.count(), 0)
        search.assert_not_called()

    def test_selection_prefills_clean_query_and_helper_without_starting_search(self):
        page = self.client.get("/serpapi/", {"record": self.record.pk})
        self.assertEqual(page.context["form"].initial["query"], "Alpha Logistics SARL Kinshasa RDC")
        self.assertEqual(page.context["form"].initial["record_id"], self.record.pk)
        self.assertEqual(page.context["company_source"], "arsp")
        self.assertEqual(page.context["company_subject"], "Alpha Logistics SARL")
        self.assertContains(page, "Entreprise sélectionnée : Alpha Logistics SARL")
        self.assertContains(page, 'form="serp-search-form"')
        self.assertEqual(SerpApiSearch.objects.count(), 0)

    @patch("research.serpapi_views.serpapi.search_all", return_value={"results": [], "status": "complete", "request_count": 3})
    def test_selected_company_snapshot_survives_history_export_and_duplicate_submission(self, search):
        payload = self.payload(query="Alpha Logistics SARL Kinshasa services")
        response = self.client.post("/serpapi/create", payload)
        self.assertEqual(self.client.post("/serpapi/create", payload).url, response.url)
        run = SerpApiSearch.objects.get()
        self.assertEqual(run.query, payload["query"])
        self.assertEqual(run.report["company_source"], "arsp")
        self.assertEqual(run.report["input_company"], {
            "id": self.record.pk, "name": "Alpha Logistics SARL", "province": "Kinshasa", "dossier": "D-ARSP-01",
        })
        self.assertNotIn("record_id", search.call_args.args[0])
        self.assertNotIn("input_company", search.call_args.args[0])
        page = self.client.get(response.url)
        self.assertEqual(page.context["form"].initial["record_id"], self.record.pk)
        self.assertContains(page, "Entreprise issue de l’ARSP")
        exported = self.client.get(f"/serpapi/{run.pk}/export/json/").json()
        self.assertEqual(exported["input_company"]["dossier"], "D-ARSP-01")
        search.assert_called_once()

    @patch("research.serpapi_views.serpapi.search_all")
    def test_missing_unknown_and_inactive_records_are_rejected_before_api(self, search):
        for record_id in ("", "invalid", 999999):
            with self.subTest(record_id=record_id):
                response = self.client.post("/serpapi/create", self.payload(record_id=record_id))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors.get("record_id"))
        ArspImport.objects.create(file_name="new.xlsx", file_hash="b" * 64)
        response = self.client.post("/serpapi/create", self.payload())
        self.assertTrue(response.context["form"].errors.get("record_id"))
        self.assertEqual(self.client.get("/serpapi/", {"record": self.record.pk}).status_code, 404)
        self.assertEqual(SerpApiSearch.objects.count(), 0)
        search.assert_not_called()

    @patch("research.serpapi_views.serpapi.search_all", return_value={"results": [], "status": "complete"})
    def test_free_text_ignores_stale_selection_and_preserves_user_query(self, search):
        response = self.client.post("/serpapi/create", self.payload(
            company_source="manual", record_id="stale-invalid-id", query="Entreprise saisie à la main RDC",
        ))
        self.assertEqual(response.status_code, 302)
        run = SerpApiSearch.objects.get()
        self.assertEqual(run.query, "Entreprise saisie à la main RDC")
        self.assertEqual(run.report["company_source"], "manual")
        self.assertIsNone(run.report["input_company"])
        search.assert_called_once()

    def test_picker_paginates_without_loading_all_records_and_escapes_names(self):
        for index in range(12):
            ArspRecord.objects.create(arsp_import=self.imported, dossier_number=f"D-{index}",
                                      legal_name=f"Beta {index}", raw_data={}, normalized_data={})
        response = self.client.get("/serpapi/", {"company_source": "arsp"})
        self.assertEqual(len(response.context["arsp_page"]), 10)
        self.assertEqual(response.context["arsp_page"].paginator.count, 13)
        self.assertEqual(len(self.client.get("/serpapi/", {"company_source": "arsp", "arsp_page": 2}).context["arsp_page"]), 3)
        self.record.legal_name = '<script>alert("x")</script>'
        self.record.save(update_fields=["legal_name"])
        self.assertNotContains(self.client.get("/serpapi/", {"record": self.record.pk}), '<script>alert("x")</script>')

    def test_empty_registry_keeps_manual_entry_and_bad_selection_returns_404(self):
        ArspImport.objects.create(file_name="empty.xlsx", file_hash="c" * 64)
        self.assertContains(self.client.get("/serpapi/", {"company_source": "arsp"}), "La base ARSP est vide")
        self.assertEqual(self.client.get("/serpapi/").context["company_source"], "manual")
        for value in ("invalid", "²", "-1"):
            self.assertEqual(self.client.get("/serpapi/", {"record": value}).status_code, 404)
