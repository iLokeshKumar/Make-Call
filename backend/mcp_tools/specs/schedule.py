from mcp_tools.spec import ToolSpec

schedule_demo = ToolSpec(
    name="schedule_demo",
    category="schedule",
    description=(
        "Authoritatively schedule a lead demo. Loads the lead, resolves the lead's "
        "runtime timezone, converts the requested local time into one timezone-aware "
        "appointment, persists it, creates the online meeting/calendar event, sends "
        "one confirmation, and returns the persisted appointment. This is the only "
        "tool that should be used to schedule a demo."
    ),
    when_to_use=[
        "The lead explicitly agrees to a demo and gives a date/time",
        "The lead gives natural language such as 'tomorrow at 10 AM'",
    ],
    when_not_to_use=[
        "The lead has not confirmed a time",
        "You are only sending a non-scheduling follow-up",
        "You need to send a second confirmation after this tool succeeds",
    ],
    returns=(
        "The persisted appointment: {appointment_id, lead_id, requested_time, "
        "appointment_time, timezone, status, meeting_link, calendar_event_id, "
        "email_sent, provider}. Downstream messages must use these returned values. "
        "The provider is selected from the company's connected scheduling integrations; "
        "do not assume Google Calendar."
    ),
)

book_meeting = ToolSpec(
    name="book_meeting",
    category="schedule",
    description=(
        "Book a Google Calendar meeting with a lead. Creates a calendar event for the "
        "specified date/time and sends an invite to the lead's email. "
        "Requires the company to have connected their Google Calendar account."
    ),
    when_to_use=[
        "Lead agrees to a follow-up call or demo and provides a specific date and time",
        "You want to lock in a meeting slot before ending the call",
    ],
    when_not_to_use=[
        "Lead has not confirmed availability — don't book without their agreement",
        "Google Calendar has not been connected — call get_google_auth_url first",
        "You don't have the lead's email — collect it first",
    ],
    returns="Dict: {event_id, calendar_link, meet_link, scheduled_at, attendees}.",
)

book_demo = ToolSpec(
    name="book_demo",
    category="schedule",
    description=(
        "Book a product demo session with a lead. Same as book_meeting but pre-fills "
        "the event title and description as a product demo with the correct team member."
    ),
    when_to_use=[
        "Lead says 'I want to see a demo' or 'can I get a trial?'",
        "You want to schedule a dedicated product demonstration",
    ],
    when_not_to_use=[
        "Lead only wants a follow-up call (not a demo) — use book_meeting instead",
        "Google Calendar is not connected",
    ],
    returns="Dict: {event_id, calendar_link, meet_link, scheduled_at, attendees}.",
)

get_google_auth_url = ToolSpec(
    name="get_google_auth_url",
    category="schedule",
    description=(
        "Generate a Google OAuth authorization URL so the company can connect their "
        "Google Calendar account. Returns a URL the user must open in their browser."
    ),
    when_to_use=[
        "Company wants to enable calendar booking and hasn't connected Google Calendar yet",
        "Existing Google Calendar connection has expired and needs re-authorization",
    ],
    when_not_to_use=[
        "Google Calendar is already connected and working",
    ],
    returns="Dict: {auth_url: str} — a URL the user must visit to grant calendar access.",
)

submit_google_auth_code = ToolSpec(
    name="submit_google_auth_code",
    category="schedule",
    description=(
        "Exchange a Google OAuth authorization code for access and refresh tokens, "
        "completing the Google Calendar connection for the company."
    ),
    when_to_use=[
        "User has completed the Google OAuth flow and has received the authorization code",
    ],
    when_not_to_use=[
        "No auth code has been received yet — call get_google_auth_url first",
    ],
    returns="Dict: {connected: bool, email: str} on success.",
)
