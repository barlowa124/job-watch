#!/usr/bin/env python3
"""Classifier tests for check_replies: ATS subject/body ambiguity cases.

Run: python3 -m unittest test_check_replies -v
"""

import unittest

import check_replies as cr

CFG = {
    "employer": [
        "iambictherapeutics.com",
        "ashbyhq.com",
        "teiko.bio",
        "chaidiscovery.com",
        "michaeljfox",
    ],
    "bulk": ["linkedin.com", "newsletters", "michaeljfox-email"],
    "reply_kw": ["interview", "next steps", "move forward"],
    "confirm_kw": ["thank you for applying", "received your application"],
    "reject_kw": cr.DEFAULT_REJECTION_KEYWORDS,
}

IAMBIC_REJECT_BODY = (
    "Thanks for taking the time to apply to the Software Engineer - Agentic "
    "data pipelines role at Iambic Therapeutics. We're happy you considered "
    "us in your career search. Unfortunately, after careful consideration, "
    "we have decided not to move forward with your candidacy."
)

TEIKO_REJECT_BODY = (
    "Thank you for applying for the Bioinformatics Engineer role at Teiko. "
    "After reviewing your application we've determined that there isn't an "
    "ideal fit at this time, and we will not be moving forward with your "
    "candidacy."
)

CONFIRM_BODY = (
    "Thank you for applying! We have received your application and will "
    "review it shortly."
)

INTERVIEW_BODY = (
    "We were impressed with your background and would like to schedule a "
    "phone screen as a next step."
)


def msg(sender, subject, body=""):
    return {
        "id": "1",
        "date": "d",
        "sender": sender,
        "subject": subject,
        "body": body,
    }


class EmployerBodyClassification(unittest.TestCase):
    """ATS platforms reuse confirmation subjects on rejections; body decides."""

    def test_rejection_under_confirmation_subject(self):
        m = msg(
            "Iambic Therapeutics <no-reply@ashbyhq.com>",
            "Thank you for applying for the Software Engineer - Agentic data pipelines",
            IAMBIC_REJECT_BODY,
        )
        self.assertEqual(cr.classify(m, CFG), "REJECTION")

    def test_ideal_fit_rejection(self):
        m = msg(
            "Teiko <no-reply@ashbyhq.com>",
            "Teiko Application Update",
            TEIKO_REJECT_BODY,
        )
        self.assertEqual(cr.classify(m, CFG), "REJECTION")

    def test_real_confirmation(self):
        m = msg(
            "Acme <no-reply@ashbyhq.com>",
            "Thank you for applying to Acme",
            CONFIRM_BODY,
        )
        self.assertEqual(cr.classify(m, CFG), "CONFIRMATION")

    def test_interview_invite_is_reply(self):
        m = msg(
            "Acme Recruiting <recruiting@iambictherapeutics.com>",
            "Next steps for your application",
            INTERVIEW_BODY,
        )
        self.assertEqual(cr.classify(m, CFG), "REPLY")

    def test_application_variant_rejection(self):
        # Chai's phrasing: "decided not to move forward with your application"
        m = msg(
            "Chai Discovery <careers@chaidiscovery.com>",
            "Thank you for applying to Chai Discovery",
            "After careful review, we've decided not to move forward "
            "with your application.",
        )
        self.assertEqual(cr.classify(m, CFG), "REJECTION")

    def test_bulk_beats_employer_newsletter(self):
        # Employer domain sending newsletters from a bulk subdomain:
        # the bulk entry wins so marketing mail is suppressed entirely.
        m = msg(
            "MFF <no-reply@michaeljfox-email.org>",
            "A Future without Parkinson's Is Possible",
            "newsletter body mentioning moving forward",
        )
        self.assertIsNone(cr.classify(m, CFG))

    def test_employer_person_still_classified(self):
        # A human at the real employer domain is not bulk-suppressed.
        m = msg(
            "Recruiter <person@michaeljfox.org>",
            "Interview availability",
            "We would like to schedule an interview.",
        )
        self.assertEqual(cr.classify(m, CFG), "REPLY")

    def test_employer_empty_body_needs_review(self):
        # A confirmation-shaped subject with no fetched body could hide a
        # rejection; surface it instead of guessing.
        m = msg(
            "Iambic <no-reply@ashbyhq.com>",
            "Thank you for applying for the ML Scientist role",
            "",
        )
        self.assertEqual(cr.classify(m, CFG), "REPLY")


class NonEmployerPaths(unittest.TestCase):
    def test_unknown_sender_replyish(self):
        m = msg(
            "Someone <a@b.com>",
            "Interview availability",
            "body does not matter",
        )
        self.assertEqual(cr.classify(m, CFG), "REPLY")

    def test_bulk_ignored(self):
        m = msg(
            "LinkedIn <news@linkedin.com>",
            "Interview availability",
            "",
        )
        self.assertIsNone(cr.classify(m, CFG))

    def test_unknown_sender_no_match(self):
        m = msg("A <a@b.com>", "Your order shipped", "body")
        self.assertIsNone(cr.classify(m, CFG))


if __name__ == "__main__":
    unittest.main()
