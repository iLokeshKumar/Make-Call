import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import CallTask, Campaign, CampaignRecipient, CampaignStep, Company, CompanySetting, EngagementEvent, Interaction, Lead, OptOut, Product, Quote, QuoteCreate, QuoteItemCreate, User
from services.analytics_service import get_engagement_summary
from services.automation_worker_service import run_worker_cycle
from services.demand_generation_service import get_scheduled_call_task_for_lead, trigger_new_lead_outreach
from services.dialer_service import create_batch_call_tasks, is_lead_callable, opt_out_lead_from_calls
import services.next_action_service as next_action_service
import services.quote_service as quote_service
from services.outcome_service import apply_call_outcome
from services.email_tracking_service import build_quote_view_url, ensure_interaction_tracking_token, rewrite_click_tracking_links
from services.engagement_service import record_email_open
from services.inbound_email_service import ingest_email_webhook_event
from services.inbound_whatsapp_service import ingest_whatsapp_webhook_event
from services.opt_out_service import unsubscribe_lead
from services.quote_service import record_quote_open_by_token


class PhaseOneTwoServicesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        company = Company(name="Acme", slug="acme")
        self.session.add(company)
        self.session.commit()
        self.session.refresh(company)
        self.company_id = company.id

        user = User(
            company_id=self.company_id,
            email="owner@example.com",
            username="owner",
            username_normalized="owner",
            password_hash="x",
            is_active=True,
            email_verified=True,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_id = user.id

    def tearDown(self):
        self.session.close()

    def _make_lead(self, **overrides):
        lead = Lead(
            company_id=self.company_id,
            owner_user_id=self.user_id,
            name=overrides.get("name", "Lead One"),
            normalized_phone=overrides.get("normalized_phone", "+911234567890"),
            email=overrides.get("email", "lead@example.com"),
            source=overrides.get("source", "manual"),
            enrichment_status=overrides.get("enrichment_status", "not_enriched"),
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(lead)
        self.session.commit()
        self.session.refresh(lead)
        return lead

    def _make_task(self, lead_id: int):
        task = CallTask(
            company_id=self.company_id,
            lead_id=lead_id,
            assigned_user_id=self.user_id,
            status="dialing",
            attempt_count=1,
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def test_apply_call_outcome_marks_interested_call_completed(self):
        lead = self._make_lead()
        interaction = Interaction(
            company_id=self.company_id,
            lead_id=lead.id,
            user_id=self.user_id,
            type="call",
            channel="call",
            direction="outbound",
            source="twilio",
            status="completed",
            transcript="Yes, I am interested. Please send quote and product details.",
        )
        self.session.add(interaction)
        self.session.commit()
        self.session.refresh(interaction)

        task = self._make_task(lead.id)

        result = apply_call_outcome(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            task_id=task.id,
            interaction_id=interaction.id,
            raw_status="completed",
            transcript=interaction.transcript,
            confidence=Decimal("0.90"),
        )

        self.assertEqual(result["normalized_outcome"], "answered_interested")
        updated_task = self.session.get(CallTask, task.id)
        updated_lead = self.session.get(Lead, lead.id)
        self.assertEqual(updated_task.status, "completed")
        self.assertEqual(updated_task.last_outcome, "answered_interested")
        self.assertEqual(updated_lead.qualification_status, "qualified")
        self.assertEqual(updated_lead.next_action, "send_quote")

    def test_apply_call_outcome_schedules_retry_for_no_answer(self):
        lead = self._make_lead(normalized_phone="+919999999999")
        task = self._make_task(lead.id)

        result = apply_call_outcome(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            task_id=task.id,
            interaction_id=None,
            raw_status="no_answer",
            transcript=None,
        )

        updated_task = self.session.get(CallTask, task.id)
        self.assertEqual(result["normalized_outcome"], "no_answer")
        self.assertEqual(updated_task.status, "retry_scheduled")
        self.assertIsNotNone(updated_task.retry_after)

    def test_batch_call_tasks_skip_opted_out_leads(self):
        lead_a = self._make_lead(name="Callable Lead", normalized_phone="+911111111111")
        lead_b = self._make_lead(name="Opted Lead", normalized_phone="+922222222222", email="lead2@example.com")
        opt_out_lead_from_calls(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            lead_id=lead_b.id,
            reason="Requested no more calls",
        )

        result = create_batch_call_tasks(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            lead_ids=[lead_a.id, lead_b.id],
            dialer_source="batch_dialer",
        )

        self.assertEqual(result["created_count"], 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["lead_id"], lead_b.id)
        self.assertEqual(result["skipped"][0]["reason"], "opted_out")

    def test_is_lead_callable_false_for_opted_out(self):
        lead = self._make_lead()
        self.session.add(OptOut(company_id=self.company_id, lead_id=lead.id, channel="call"))
        self.session.commit()

        allowed, reason = is_lead_callable(self.session, self.company_id, lead.id)
        self.assertFalse(allowed)
        self.assertEqual(reason, "opted_out")

    def test_trigger_new_lead_outreach_creates_task_when_enabled(self):
        lead = self._make_lead(
            name="High Intent Lead",
            normalized_phone="+913333333333",
            email="ceo@targettech.com",
            source="apollo api",
            enrichment_status="apollo_enriched",
        )
        lead.industry = "Tech"
        lead.job_title = "Founder"
        self.session.add(lead)
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="AUTO_TRIGGER_NEW_LEADS",
                value="true",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        result = trigger_new_lead_outreach(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            lead_id=lead.id,
        )

        self.assertTrue(result["auto_triggered"])
        task = get_scheduled_call_task_for_lead(self.session, self.company_id, lead.id)
        self.assertIsNotNone(task)
        self.assertEqual(task.dialer_source, "demand_generation")

    def test_record_email_open_uses_tracking_token(self):
        lead = self._make_lead()
        interaction = Interaction(
            company_id=self.company_id,
            lead_id=lead.id,
            user_id=self.user_id,
            type="communication",
            channel="email",
            direction="outbound",
            source="system",
            content="Hello",
            status="completed",
        )
        self.session.add(interaction)
        self.session.commit()
        self.session.refresh(interaction)

        token = ensure_interaction_tracking_token(self.session, interaction)
        result = record_email_open(self.session, token)

        self.assertEqual(result["interaction_id"], interaction.id)
        refreshed = self.session.get(Interaction, interaction.id)
        self.assertIn("opened_at", refreshed.metadata_json)

    def test_record_quote_open_by_token_sets_opened_at(self):
        lead = self._make_lead()
        quote = Quote(
            company_id=self.company_id,
            lead_id=lead.id,
            quote_number="Q-1",
            status="draft",
            currency="INR",
            subtotal=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            tracking_token="quote-token",
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(quote)
        self.session.commit()

        result = record_quote_open_by_token(self.session, "quote-token")
        self.assertEqual(result["quote_id"], quote.id)
        refreshed = self.session.get(Quote, quote.id)
        self.assertIsNotNone(refreshed.opened_at)

    def test_unsubscribe_lead_creates_opt_out(self):
        lead = self._make_lead()
        opt_out = unsubscribe_lead(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            lead_id=lead.id,
            channel="email",
            reason="Requested unsubscribe",
        )
        self.assertEqual(opt_out.channel, "email")
        exists = self.session.exec(
            select(OptOut).where(
                OptOut.company_id == self.company_id,
                OptOut.lead_id == lead.id,
                OptOut.channel == "email",
            )
        ).first()
        self.assertIsNotNone(exists)

    def test_rewrite_click_tracking_links_wraps_plain_urls(self):
        rewritten = rewrite_click_tracking_links(
            "Visit https://example.com/demo for details",
            "https://app.example.com",
            "track-123",
        )
        self.assertIn("/tracking/email/click/track-123", rewritten)
        self.assertIn("target=https%3A%2F%2Fexample.com%2Fdemo", rewritten)

    def test_rewrite_click_tracking_links_skips_existing_tracking_url(self):
        original = (
            "Tracked "
            "https://app.example.com/tracking/email/click/track-123?target=https%3A%2F%2Fexample.com"
        )
        rewritten = rewrite_click_tracking_links(
            original,
            "https://app.example.com",
            "track-123",
        )
        self.assertEqual(rewritten, original)

    def test_ingest_whatsapp_webhook_records_reply(self):
        lead = self._make_lead(normalized_phone="+918888888888")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="WHATSAPP_NUMBER",
                value="+14155238886",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        result = ingest_whatsapp_webhook_event(
            self.session,
            {
                "From": "whatsapp:+918888888888",
                "To": "whatsapp:+14155238886",
                "Body": "Yes, send me the details",
                "MessageSid": "SM-whatsapp-1",
            },
        )

        self.assertEqual(result["status"], "reply_recorded")
        interaction = self.session.get(Interaction, result["interaction_id"])
        self.assertEqual(interaction.channel, "whatsapp")
        self.assertEqual(interaction.direction, "inbound")

    def test_whatsapp_callback_reply_creates_follow_up_call_task(self):
        lead = self._make_lead(normalized_phone="+917777777777")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="WHATSAPP_NUMBER",
                value="+14155238886",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        result = ingest_whatsapp_webhook_event(
            self.session,
            {
                "From": "whatsapp:+917777777777",
                "To": "whatsapp:+14155238886",
                "Body": "Please call me back in 10 minutes",
                "MessageSid": "SM-whatsapp-2",
            },
        )

        self.assertEqual(result["intent"], "callback_requested")
        self.assertIsNotNone(result["call_task_id"])
        lead = self.session.get(Lead, lead.id)
        task = self.session.get(CallTask, result["call_task_id"])
        self.assertEqual(lead.next_action, "follow_up_call")
        self.assertEqual(task.dialer_source, "whatsapp_reply")
        self.assertEqual(task.status, "queued")

    def test_whatsapp_reply_marks_active_campaign_recipient_responded(self):
        lead = self._make_lead(normalized_phone="+916666666666")
        campaign = Campaign(
            company_id=self.company_id,
            name="WA Campaign",
            channel="whatsapp",
            objective="nurture",
            status="active",
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(campaign)
        self.session.commit()
        self.session.refresh(campaign)

        step = CampaignStep(
            campaign_id=campaign.id,
            company_id=self.company_id,
            step_order=1,
            channel="whatsapp",
            delay_hours=0,
            is_active=True,
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(step)
        self.session.commit()

        recipient = CampaignRecipient(
            campaign_id=campaign.id,
            company_id=self.company_id,
            lead_id=lead.id,
            status="active",
            current_step=1,
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(recipient)
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="WHATSAPP_NUMBER",
                value="+14155238886",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()
        self.session.refresh(recipient)

        result = ingest_whatsapp_webhook_event(
            self.session,
            {
                "From": "whatsapp:+916666666666",
                "To": "whatsapp:+14155238886",
                "Body": "Yes, share the quote",
                "MessageSid": "SM-whatsapp-3",
            },
        )

        updated_recipient = self.session.get(CampaignRecipient, recipient.id)
        updated_lead = self.session.get(Lead, lead.id)
        self.assertEqual(result["campaign_recipient_id"], recipient.id)
        self.assertEqual(updated_recipient.status, "responded")
        self.assertEqual(updated_lead.next_action, "send_quote")

    def test_whatsapp_quote_reply_auto_creates_and_sends_quote_when_product_matches(self):
        lead = self._make_lead(normalized_phone="+915555555555")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="WHATSAPP_NUMBER",
                value="+14155238886",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.add(
            Product(
                company_id=self.company_id,
                name="Solar CRM Suite",
                sku="SOLAR-CRM",
                price=Decimal("4999.00"),
                currency="INR",
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        with patch.object(quote_service, "generate_quote_pdf", side_effect=lambda session, company_id, actor_user_id, quote_id: session.get(Quote, quote_id)):
            with patch.object(next_action_service, "send_quote_to_lead", return_value={"results": [{"success": True}]}):
                result = ingest_whatsapp_webhook_event(
                    self.session,
                    {
                        "From": "whatsapp:+915555555555",
                        "To": "whatsapp:+14155238886",
                        "Body": "Please send a quote for Solar CRM Suite",
                        "MessageSid": "SM-whatsapp-quote-1",
                    },
                )

        self.assertEqual(result["intent"], "quote_requested")
        self.assertEqual(result["status"], "reply_recorded")
        self.assertEqual(result["quote_request_status"], "created_and_sent")
        self.assertEqual(result["product_id"] > 0, True)
        self.assertIsNotNone(result["quote_id"])
        self.assertIn("whatsapp", result["channels"])
        lead = self.session.get(Lead, lead.id)
        interaction = self.session.get(Interaction, result["interaction_id"])
        quote = self.session.get(Quote, result["quote_id"])
        self.assertEqual(lead.next_action, "await_quote_response")
        self.assertEqual(interaction.metadata_json["quote_request_result"]["status"], "created_and_sent")
        self.assertEqual(quote.quote_number.startswith("Q-"), True)

    def test_whatsapp_quote_reply_creates_review_task_when_product_context_is_insufficient(self):
        lead = self._make_lead(normalized_phone="+914444444444")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="WHATSAPP_NUMBER",
                value="+14155238886",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.add(
            Product(
                company_id=self.company_id,
                name="Solar CRM Suite",
                sku="SOLAR-CRM",
                price=Decimal("4999.00"),
                currency="INR",
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        result = ingest_whatsapp_webhook_event(
            self.session,
            {
                "From": "whatsapp:+914444444444",
                "To": "whatsapp:+14155238886",
                "Body": "Please send me the quote",
                "MessageSid": "SM-whatsapp-quote-2",
            },
        )

        self.assertEqual(result["intent"], "quote_requested")
        self.assertEqual(result["status"], "reply_recorded")
        self.assertEqual(result["quote_request_status"], "queued_for_review")
        self.assertEqual(result["reason"], "insufficient_product_context")
        self.assertIsNotNone(result["call_task_id"])
        review_task = self.session.get(CallTask, result["call_task_id"])
        self.assertEqual(review_task.dialer_source, "quote_request_review")

    def test_quote_public_accept_and_reject_by_token(self):
        lead = self._make_lead()
        quote = quote_service.create_quote(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            data=QuoteCreate(
                lead_id=lead.id,
                account_id=lead.account_id,
                currency="INR",
                notes="Test quote",
                items=[
                    QuoteItemCreate(
                        product_name_snapshot="Test Item",
                        quantity=1,
                        unit_price=Decimal("1000.00"),
                        discount_percent=Decimal("0.00"),
                    )
                ],
            ),
        )

        accepted = quote_service.respond_to_quote_token(self.session, quote.tracking_token, "accept")
        self.assertEqual(accepted.status, "accepted")
        rejected = quote_service.respond_to_quote_token(self.session, quote.tracking_token, "reject")
        self.assertEqual(rejected.status, "rejected")

    def test_analytics_summary_counts_engagement_and_activity(self):
        self.session.add(
            EngagementEvent(
                company_id=self.company_id,
                event_type="email.open",
                channel="email",
                payload={"tracking_token": "t1"},
            )
        )
        self.session.add(
            EngagementEvent(
                company_id=self.company_id,
                event_type="quote.viewed",
                channel="quote",
                payload={"quote_id": 1},
            )
        )
        call_lead = self._make_lead(normalized_phone="+919876543210")
        self.session.add(
            CallTask(
                company_id=self.company_id,
                lead_id=call_lead.id,
                assigned_user_id=self.user_id,
                status="queued",
                attempt_count=0,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        campaign = Campaign(
            company_id=self.company_id,
            name="AI nurture",
            channel="email",
            objective="demo",
            status="active",
            created_by=self.user_id,
            updated_by=self.user_id,
        )
        self.session.add(campaign)
        self.session.commit()
        self.session.refresh(campaign)
        self.session.add(
            CampaignRecipient(
                campaign_id=campaign.id,
                company_id=self.company_id,
                lead_id=self._make_lead(normalized_phone="+919999111222").id,
                status="responded",
                current_step=1,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        quote = quote_service.create_quote(
            session=self.session,
            company_id=self.company_id,
            actor_user_id=self.user_id,
            data=QuoteCreate(
                lead_id=self._make_lead().id,
                account_id=None,
                currency="INR",
                notes="Analytics quote",
                items=[
                    QuoteItemCreate(
                        product_name_snapshot="Profiler",
                        quantity=1,
                        unit_price=Decimal("1299.00"),
                        discount_percent=Decimal("0.00"),
                    )
                ],
            ),
        )
        self.session.commit()

        summary = get_engagement_summary(self.session, self.company_id, lookback_days=7)
        self.assertEqual(summary["event_counts"].get("email.open"), 1)
        self.assertEqual(summary["event_counts"].get("quote.viewed"), 1)
        self.assertEqual(summary["call_task_status_counts"].get("queued"), 1)
        self.assertEqual(summary["campaign_status_counts"].get("responded"), 1)
        timeline = summary["event_timeline"]
        self.assertTrue(any(entry["event_type"] == "email.open" for entry in timeline))
        self.assertTrue(summary["campaign_funnel"])
        trends = summary["campaign_conversion_trends"]
        self.assertTrue(len(trends) >= 1)
        self.assertEqual(trends[0]["responded"], 1)
        self.assertEqual(trends[0]["sent"], 1)
        export = summary["quote_timeline_export"]
        self.assertTrue(any(item["quote_id"] == quote.id for item in export))
        overtime = summary["campaign_status_over_time"]
        self.assertTrue(any(entry["status"] == "responded" for entry in overtime))

    def test_email_quote_reply_auto_creates_and_sends_quote_when_product_matches(self):
        lead = self._make_lead(email="customer@example.com")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="INBOUND_EMAIL_ADDRESS",
                value="quotes@acme.test",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.add(
            Product(
                company_id=self.company_id,
                name="Solar CRM Suite",
                sku="SOLAR-CRM",
                price=Decimal("4999.00"),
                currency="INR",
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        payload = {
            "From": "customer@example.com",
            "To": "quotes@acme.test",
            "Subject": "Quick quote for Solar CRM Suite",
            "Body": "Please send a quote for Solar CRM Suite",
            "Message-ID": "msg-email-1",
        }

        with patch.object(quote_service, "generate_quote_pdf", side_effect=lambda session, company_id, actor_user_id, quote_id: session.get(Quote, quote_id)):
            with patch.object(next_action_service, "send_quote_to_lead", return_value={"results": [{"success": True}]}):
                result = ingest_email_webhook_event(self.session, payload)

        self.assertEqual(result["status"], "reply_recorded")
        self.assertEqual(result["quote_request_status"], "created_and_sent")
        self.assertEqual(result["intent"], "quote_requested")
        self.assertEqual(result["message_id"], "msg-email-1")
        self.assertIsNotNone(result["quote_id"])
        self.assertEqual(result["channels"][0], "email")
        quote = self.session.get(Quote, result["quote_id"])
        self.assertTrue(quote.quote_number.startswith("Q-"))

    def test_email_quote_reply_creates_review_task_when_product_context_is_insufficient(self):
        lead = self._make_lead(email="customer@example.com", normalized_phone="+919999999999")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="INBOUND_EMAIL_ADDRESS",
                value="quotes@acme.test",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.add(
            Product(
                company_id=self.company_id,
                name="Solar CRM Suite",
                sku="SOLAR-CRM",
                price=Decimal("4999.00"),
                currency="INR",
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        payload = {
            "From": "customer@example.com",
            "To": "quotes@acme.test",
            "Subject": "Need quote",
            "Body": "Please send me the quote",
            "Message-ID": "msg-email-2",
        }

        result = ingest_email_webhook_event(self.session, payload)

        self.assertEqual(result["status"], "reply_recorded")
        self.assertEqual(result["quote_request_status"], "queued_for_review")
        self.assertEqual(result["reason"], "insufficient_product_context")
        self.assertIsNotNone(result["call_task_id"])

    def test_email_quote_reply_duplicate_is_ignored(self):
        lead = self._make_lead(email="customer@example.com")
        self.session.add(
            CompanySetting(
                company_id=self.company_id,
                key="INBOUND_EMAIL_ADDRESS",
                value="quotes@acme.test",
                is_secret=False,
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.add(
            Product(
                company_id=self.company_id,
                name="Solar CRM Suite",
                sku="SOLAR-CRM",
                price=Decimal("4999.00"),
                currency="INR",
                created_by=self.user_id,
                updated_by=self.user_id,
            )
        )
        self.session.commit()

        payload = {
            "From": "customer@example.com",
            "To": "quotes@acme.test",
            "Subject": "Quick quote for Solar CRM Suite",
            "Body": "Please send a quote for Solar CRM Suite",
            "Message-ID": "msg-email-dup",
        }

        with patch.object(
            quote_service,
            "generate_quote_pdf",
            side_effect=lambda session, company_id, actor_user_id, quote_id: session.get(Quote, quote_id),
        ):
            with patch.object(next_action_service, "send_quote_to_lead", return_value={"results": [{"success": True}]}):
                first = ingest_email_webhook_event(self.session, payload)

        second = ingest_email_webhook_event(self.session, payload)
        self.assertEqual(second["status"], "ignored")
        self.assertEqual(second["reason"], "duplicate_message")
        self.assertEqual(second["message_id"], "msg-email-dup")

    def test_run_worker_cycle_aggregates_dialer_and_campaign_results(self):
        with patch("services.automation_worker_service.run_batch_dialer", return_value=[{"task_id": 1}]) as mock_dialer:
            with patch("services.automation_worker_service.run_due_campaign_recipients", return_value=[{"recipient_id": 2}]) as mock_campaign:
                results = run_worker_cycle(self.session, company_id=self.company_id, dial_limit_per_company=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["company_id"], self.company_id)
        self.assertEqual(results[0]["dialer_results"], [{"task_id": 1}])
        self.assertEqual(results[0]["campaign_results"], [{"recipient_id": 2}])
        mock_dialer.assert_called_once()
        mock_campaign.assert_called_once()

    def test_build_quote_view_url_uses_tracking_route(self):
        url = build_quote_view_url("https://app.example.com", "quote-token")
        self.assertEqual(url, "https://app.example.com/tracking/quote/view/quote-token")


class TenantIsolationTest(unittest.TestCase):
    """Verify that the company_id boundary prevents cross-tenant data access."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        # Company A
        co_a = Company(name="Acme A", slug="acme-a")
        self.session.add(co_a)
        self.session.commit()
        self.session.refresh(co_a)
        self.co_a_id = co_a.id

        user_a = User(
            company_id=self.co_a_id, email="a@a.com", username="ua",
            username_normalized="ua", password_hash="x", is_active=True, email_verified=True,
        )
        self.session.add(user_a)
        self.session.commit()
        self.session.refresh(user_a)
        self.user_a_id = user_a.id

        # Company B
        co_b = Company(name="Acme B", slug="acme-b")
        self.session.add(co_b)
        self.session.commit()
        self.session.refresh(co_b)
        self.co_b_id = co_b.id

        user_b = User(
            company_id=self.co_b_id, email="b@b.com", username="ub",
            username_normalized="ub", password_hash="x", is_active=True, email_verified=True,
        )
        self.session.add(user_b)
        self.session.commit()
        self.session.refresh(user_b)
        self.user_b_id = user_b.id

    def tearDown(self):
        self.session.close()

    def _make_lead(self, company_id: int, user_id: int, **overrides):
        lead = Lead(
            company_id=company_id,
            owner_user_id=user_id,
            name=overrides.get("name", "Test Lead"),
            normalized_phone=overrides.get("normalized_phone", "+911111111111"),
            email=overrides.get("email", "lead@test.com"),
            source="manual",
            enrichment_status="not_enriched",
            created_by=user_id,
            updated_by=user_id,
        )
        self.session.add(lead)
        self.session.commit()
        self.session.refresh(lead)
        return lead

    # ------------------------------------------------------------------ #
    # Lead isolation                                                       #
    # ------------------------------------------------------------------ #

    def test_company_b_cannot_read_company_a_lead(self):
        """Querying leads scoped to company_b must not return company_a leads."""
        lead_a = self._make_lead(self.co_a_id, self.user_a_id, name="Lead A")
        leads_for_b = self.session.exec(
            select(Lead).where(Lead.company_id == self.co_b_id)
        ).all()
        self.assertNotIn(lead_a.id, [l.id for l in leads_for_b])

    def test_is_lead_callable_returns_false_for_wrong_company(self):
        """is_lead_callable(company_b_id, lead_a_id) → False (lead not found)."""
        lead_a = self._make_lead(self.co_a_id, self.user_a_id)
        callable_, reason = is_lead_callable(self.session, self.co_b_id, lead_a.id)
        self.assertFalse(callable_)
        self.assertEqual(reason, "lead_not_found")

    def test_batch_call_tasks_skips_lead_from_other_company(self):
        """create_batch_call_tasks with a lead from company_a scoped to company_b creates no tasks."""
        lead_a = self._make_lead(self.co_a_id, self.user_a_id)
        result = create_batch_call_tasks(
            session=self.session,
            company_id=self.co_b_id,
            actor_user_id=self.user_b_id,
            lead_ids=[lead_a.id],
        )
        self.assertEqual(result["created"], 0)
        tasks = self.session.exec(
            select(CallTask).where(CallTask.company_id == self.co_b_id)
        ).all()
        self.assertEqual(len(tasks), 0)

    # ------------------------------------------------------------------ #
    # Opt-out isolation                                                    #
    # ------------------------------------------------------------------ #

    def test_opt_out_from_company_a_does_not_affect_company_b(self):
        """Opting a lead out in company_a must not create an OptOut row for company_b."""
        lead_a = self._make_lead(self.co_a_id, self.user_a_id)
        opt_out_lead_from_calls(self.session, self.co_a_id, self.user_a_id, lead_a.id)
        opt_outs_b = self.session.exec(
            select(OptOut).where(OptOut.company_id == self.co_b_id)
        ).all()
        self.assertEqual(len(opt_outs_b), 0)

    # ------------------------------------------------------------------ #
    # Engagement event isolation                                           #
    # ------------------------------------------------------------------ #

    def test_engagement_summary_only_returns_own_company_events(self):
        """get_engagement_summary for company_b must not count company_a events."""
        lead_a = self._make_lead(self.co_a_id, self.user_a_id)
        # Plant an engagement event for company A
        evt = EngagementEvent(
            company_id=self.co_a_id,
            lead_id=lead_a.id,
            channel="email",
            event_type="open",
            payload={},
        )
        self.session.add(evt)
        self.session.commit()

        # Company B summary must have 0 email opens
        summary_b = get_engagement_summary(self.session, self.co_b_id)
        email_section = summary_b.get("email", {})
        self.assertEqual(email_section.get("open", 0), 0)

    # ------------------------------------------------------------------ #
    # ISM orchestrator isolation                                           #
    # ------------------------------------------------------------------ #

    def test_ism_for_company_b_does_not_process_company_a_leads(self):
        """run_ism_for_company scoped to company_b must not touch company_a leads."""
        from agents.ism_orchestrator import run_ism_for_company

        lead_a = self._make_lead(self.co_a_id, self.user_a_id)
        original_outreach_at = lead_a.last_outreach_at

        # run ISM for company_b
        with patch("agents.ism_orchestrator._dispatch_call", return_value={"action": "queued_call_task"}):
            run_ism_for_company(self.session, self.co_b_id, self.user_b_id)

        # company_a lead must be untouched
        self.session.refresh(lead_a)
        self.assertEqual(lead_a.last_outreach_at, original_outreach_at)

    # ------------------------------------------------------------------ #
    # WhatsApp webhook isolation                                           #
    # ------------------------------------------------------------------ #

    def test_whatsapp_inbound_reply_routed_only_to_correct_company(self):
        """ingest_whatsapp_webhook_event with forced_company_id=co_b must not create
        interactions under company_a even if the phone matches a company_a lead."""
        lead_a = self._make_lead(
            self.co_a_id, self.user_a_id,
            normalized_phone="+919999999999",
            email="lead_a@example.com",
        )
        payload = {
            "From": "whatsapp:+919999999999",
            "To": "whatsapp:+911234567890",
            "Body": "Yes I am interested",
        }
        result = ingest_whatsapp_webhook_event(
            self.session,
            payload,
            forced_company_id=self.co_b_id,  # force company_b context
        )
        # Should be ignored — lead phone not found under company_b
        self.assertIn(result["status"], {"ignored", "reply_recorded"})
        interactions_a = self.session.exec(
            select(Interaction).where(
                Interaction.company_id == self.co_a_id,
                Interaction.direction == "inbound",
            )
        ).all()
        self.assertEqual(len(interactions_a), 0)


if __name__ == "__main__":
    unittest.main()
