import os
import json
import logging
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials as UserCredentials
import pickle
import requests
from models.models import User

logger = logging.getLogger(__name__)

# Google Calendar API scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

class GoogleMeetGenerator:
    """Generate Google Meet links for demo meetings using Google Calendar API"""
    
    def __init__(self, user: User = None, session = None):
        """Initialize with credentials from user or environment"""
        self.client_id = os.getenv("Client_ID")
        self.client_secret = os.getenv("Client_Secret")
        self.credentials = None
        self.user = user
        self.session = session
        if user:
            self.load_from_user(user)
        else:
            self.authenticate()
    
    def load_from_user(self, user: User):
        """Load credentials from a User model."""
        if user.google_access_token and user.google_refresh_token:
            self.credentials = UserCredentials(
                token=user.google_access_token,
                refresh_token=user.google_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=SCOPES
            )
            # Handle expiry
            if user.google_token_expiry:
                self.credentials.expiry = user.google_token_expiry
            
            logger.info(f"✅ Loaded Google credentials for user: {user.username}")
            return True
        return False

    def validate_authentication(self) -> dict:
        """
        Validates if current credentials are valid or can be refreshed.
        Returns:
            {
                "status": "valid" | "expiring_soon" | "expired" | "disconnected",
                "email": str or None,
                "expiry": str (ISO) or None,
                "message": str
            }
        """
        if not self.credentials:
            return {
                "status": "disconnected",
                "email": None,
                "expiry": None,
                "message": "Google Calendar not connected."
            }
            
        # Helper to get expiry string
        expiry_str = self.credentials.expiry.isoformat() if self.credentials.expiry else None
        email = self.user.google_account_email if self.user else self.credentials._id_token.get('email', None) if hasattr(self.credentials, '_id_token') else None

        # Check if expiring in the next 5 minutes
        is_expiring_soon = False
        if self.credentials.expiry:
            expiry = self.credentials.expiry
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            
            time_until_expiry = expiry - datetime.now(timezone.utc)
            if timedelta(0) < time_until_expiry < timedelta(minutes=5):
                is_expiring_soon = True

        if self.credentials.expired or is_expiring_soon:
            if self.credentials.refresh_token:
                from google.auth.transport.requests import Request
                try:
                    logger.info("🔄 Attempting token refresh...")
                    self.credentials.refresh(Request())
                    # Use merge to handle objects from different sessions (e.g. Pipeline vs Tool)
                    if self.user and self.session:
                        db_user = self.session.merge(self.user)
                        db_user.google_access_token = self.credentials.token
                        # Ensure expiry is UTC-aware before saving
                        expiry = self.credentials.expiry
                        if expiry and expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=timezone.utc)
                        db_user.google_token_expiry = expiry
                        self.session.commit()
                    
                    return {
                        "status": "valid",
                        "email": email,
                        "expiry": self.credentials.expiry.isoformat() if self.credentials.expiry else None,
                        "message": "Authenticated (Refreshed)"
                    }
                except Exception as e:
                    logger.error(f"❌ Token refresh failed: {e}")
                    return {
                        "status": "expired",
                        "email": email,
                        "expiry": expiry_str,
                        "message": f"Connection expired/revoked: {str(e)}. Please connect again."
                    }
            else:
                return {
                    "status": "expired",
                    "email": email,
                    "expiry": expiry_str,
                    "message": "Connection expired and no refresh token available. Please reconnect."
                }
            
        return {
            "status": "valid" if not is_expiring_soon else "expiring_soon",
            "email": email,
            "expiry": expiry_str,
            "message": "Authenticated"
        }

    def authenticate(self):
        """Boolean check for authentication status."""
        result = self.validate_authentication()
        return result["status"] == "valid"

    def get_auth_url(self) -> str:
        """Get the URL for the user to visit and authorize."""
        flow = Flow.from_client_secrets_file('google_credentials.json', SCOPES, redirect_uri='http://localhost:3006/profile')
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        return auth_url

    def finalize_auth(self, code: str, user: User = None, session=None) -> bool:
        """Exchange auth code for tokens and save them to user or pickle."""
        try:
            flow = Flow.from_client_secrets_file('google_credentials.json', SCOPES, redirect_uri='http://localhost:3006/profile')
            flow.fetch_token(code=code)
            self.credentials = flow.credentials
            
            if user and session:
                user.google_access_token = self.credentials.token
                user.google_refresh_token = self.credentials.refresh_token
                # Ensure expiry is UTC-aware before saving
                expiry = self.credentials.expiry
                if expiry and expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                user.google_token_expiry = expiry
                
                # Try to get the email if possible
                try:
                    user_info = requests.get(
                        'https://www.googleapis.com/oauth2/v3/userinfo',
                        headers={'Authorization': f'Bearer {self.credentials.token}'}
                    ).json()
                    user.google_account_email = user_info.get('email')
                except Exception as info_err:
                    logger.error(f"❌ Failed to fetch Google user info: {info_err}")
                
                session.add(user)
                session.commit()
                logger.info(f"✅ Google Calendar tokens saved to database for user: {user.username}")
            else:
                with open('token.pickle', 'wb') as token:
                    pickle.dump(self.credentials, token)
                logger.info("✅ Google Calendar tokens generated and saved (Legacy)")
            
            return True
        except Exception as e:
            logger.error(f"❌ Failed to finalize auth: {e}")
            return False
    
    async def create_google_meet_event(self, lead_name: str, lead_email: str, proposed_time: str, 
                                  meeting_type: str = "demo", duration_minutes: int = 30) -> dict:
        """
        Create a Google Calendar event with Google Meet link
        
        Args:
            lead_name: Name of the lead
            lead_email: Email of the lead
            proposed_time: Meeting time (natural language like "Tuesday at 2 PM" or ISO format)
            meeting_type: Type of meeting (demo, consultation, etc.)
            duration_minutes: Duration of meeting in minutes (default 30)
        
        Returns:
            {
                "success": bool,
                "google_meet_link": str,
                "calendar_event_id": str,
                "calendar_link": str,
                "error": str (if failed)
            }
        """
        
        if not self.credentials:
            logger.warning("⚠️ Google credentials not available - cannot create Meet link")
            return {
                "success": False,
                "error": "Google Calendar not authenticated",
                "google_meet_link": None
            }
        
        try:
            # Parse proposed_time to datetime (ASYNC)
            meeting_datetime = await self._parse_time_string(proposed_time)
            
            if not meeting_datetime:
                return {
                    "success": False,
                    "error": f"Could not parse meeting time: {proposed_time}",
                    "google_meet_link": None
                }
            
            # Format times for Google Calendar API
            start_time = meeting_datetime.isoformat() + 'Z'
            end_time = (meeting_datetime + timedelta(minutes=duration_minutes)).isoformat() + 'Z'
            
            # Create event body
            event = {
                'summary': f'{meeting_type.title()} with {lead_name}',
                'description': f'Rio Sales Assistant - {meeting_type.title()} Meeting\n\nLead: {lead_name}\nEmail: {lead_email}',
                'start': {
                    'dateTime': start_time,
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_time,
                    'timeZone': 'UTC',
                },
                'attendees': [
                    {
                        'email': lead_email,
                        'displayName': lead_name,
                        'responseStatus': 'needsAction'
                    }
                ],
                'conferenceData': {
                    'createRequest': {
                        'requestId': f'rio-{int(datetime.now().timestamp())}-{lead_name}',
                        'conferenceSolutionKey': {
                            'type': 'hangoutsMeet'
                        }
                    }
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                        {'method': 'popup', 'minutes': 15}  # 15 min before
                    ]
                }
            }
            
            # Call Google Calendar API
            service = self._get_calendar_service()
            created_event = service.events().insert(
                calendarId='primary',
                body=event,
                conferenceDataVersion=1,
                sendUpdates='all'
            ).execute()
            
            google_meet_link = created_event.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri')
            event_id = created_event.get('id')
            calendar_link = created_event.get('htmlLink')
            
            logger.info(f"✅ Google Meet created for {lead_name}")
            logger.info(f"   📞 Meet Link: {google_meet_link}")
            logger.info(f"   📅 Calendar: {calendar_link}")
            
            return {
                "success": True,
                "google_meet_link": google_meet_link,
                "calendar_event_id": event_id,
                "calendar_link": calendar_link,
                "meeting_time": meeting_datetime.isoformat(),
                "error": None
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to create Google Meet event: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "google_meet_link": None
            }
    
    def _get_calendar_service(self):
        """Get Google Calendar service object and ensure tokens are fresh/saved."""
        from googleapiclient.discovery import build
        
        if not self.credentials:
            raise ValueError("Google credentials not loaded")

        # Refresh token if expired
        if self.credentials.expired and self.credentials.refresh_token:
            logger.info("🔄 Refreshing expired Google tokens...")
            try:
                self.credentials.refresh(Request())
                
                # Use merge to handle objects from different sessions
                if self.user and self.session:
                    db_user = self.session.merge(self.user)
                    db_user.google_access_token = self.credentials.token
                    db_user.google_token_expiry = self.credentials.expiry
                    self.session.commit()
                    logger.info(f"✅ Refreshed Google tokens and saved to DB for user: {db_user.username}")
                # Legacy fallback to pickle if no user session
                elif os.path.exists('token.pickle'):
                    with open('token.pickle', 'wb') as token:
                        pickle.dump(self.credentials, token)
                    logger.info("✅ Refreshed Google tokens and saved to pickle (Legacy)")
            except Exception as e:
                logger.error(f"❌ Token refresh failed: {e}")
                raise
        
        return build('calendar', 'v3', credentials=self.credentials, cache_discovery=False)
    
    async def _parse_time_string(self, time_str: str) -> datetime:
        """
        Parse natural language time string to datetime
        
        Examples:
        - "Tuesday at 2 PM" → next Tuesday at 2:00 PM
        - "2026-01-30 14:00" → January 30, 2026 at 2:00 PM
        - "tomorrow at 10 AM" → tomorrow at 10:00 AM
        """
        import dateparser
        import re
        from utils.date_normalizer import normalize_date_ai
        
        try:
            # Pre-process natural language strings for better parsing
            processed_time = time_str.lower().strip()
            processed_time = re.sub(r'\b(coming|next)\b\s*', '', processed_time)
            
            # 1. Local Parsing
            dt = dateparser.parse(
                processed_time,
                settings={
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': datetime.now()
                }
            )
            
            # 2. AI Fallback
            if not dt:
                logger.info(f"🧠 [Calendar Service] Local parsing failed for '{time_str}', invoking AI Normalizer")
                dt = await normalize_date_ai(time_str)
            
            if not dt:
                logger.error(f"❌ Could not parse time: {processed_time} (original: {time_str})")
                return None
                
            return dt
        
        except Exception as e:
            logger.error(f"❌ Time parsing failed: {e}")
            return None


async def create_google_meet_for_booking(lead_name: str, lead_email: str, proposed_time: str, 
                                    meeting_type: str = "demo", user: User = None, session = None) -> dict:
    """
    Convenience function to create Google Meet link for a booking
    
    Returns:
        {
            "google_meet_link": str or None,
            "calendar_link": str or None,
            "success": bool
        }
    """
    try:
        generator = GoogleMeetGenerator(user=user, session=session)
        result = await generator.create_google_meet_event(lead_name, lead_email, proposed_time, meeting_type)
        return result
    except Exception as e:
        logger.error(f"❌ Google Meet creation error: {e}")
        return {
            "success": False,
            "google_meet_link": None,
            "calendar_link": None,
            "error": str(e)
        }
