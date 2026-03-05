import os
import json
import logging
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
import pickle
import requests

logger = logging.getLogger(__name__)

# Google Calendar API scopes
SCOPES = ['https://www.googleapis.com/auth/calendar']

class GoogleMeetGenerator:
    """Generate Google Meet links for demo meetings using Google Calendar API"""
    
    def __init__(self):
        """Initialize with credentials from environment"""
        self.client_id = os.getenv("Client_ID")
        self.client_secret = os.getenv("Client_Secret")
        self.credentials = None
        self.authenticate()
    
    def authenticate(self):
        """Check if authenticated, otherwise prepare for OAuth flow."""
        try:
            if os.path.exists('token.pickle'):
                with open('token.pickle', 'rb') as token:
                    self.credentials = pickle.load(token)
                
                # Check if expired
                if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                    from google.auth.transport.requests import Request
                    try:
                        self.credentials.refresh(Request())
                        with open('token.pickle', 'wb') as token:
                            pickle.dump(self.credentials, token)
                        logger.info("✅ Refreshed Google credentials")
                    except Exception as re:
                        logger.warning(f"⚠️ Refresh failed: {re}. Re-authentication needed.")
                        self.credentials = None
                
                if self.credentials:
                    logger.info("✅ Google Calendar Authenticated")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"❌ Google auth check failed: {e}")
            return False

    def get_auth_url(self) -> str:
        """Get the URL for the user to visit and authorize."""
        flow = InstalledAppFlow.from_client_secrets_file('google_credentials.json', SCOPES)
        # Using a fixed redirect URI that doesn't rely on a local server
        flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob' 
        auth_url, _ = flow.authorization_url(prompt='consent')
        return auth_url

    def finalize_auth(self, code: str) -> bool:
        """Exchange auth code for tokens and save them."""
        try:
            flow = InstalledAppFlow.from_client_secrets_file('google_credentials.json', SCOPES)
            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
            flow.fetch_token(code=code)
            self.credentials = flow.credentials
            
            with open('token.pickle', 'wb') as token:
                pickle.dump(self.credentials, token)
            
            logger.info("✅ Google Calendar tokens generated and saved")
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
                        'requestId': f'rio-{lead_name}-{datetime.now().timestamp()}',
                        'conferenceSolutionKey': {
                            'key': 'hangoutsMeet'
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
                sendUpdates='eventCreators'
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
        """Get Google Calendar service object"""
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        
        # Refresh token if expired
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
        
        return build('calendar', 'v3', credentials=self.credentials)
    
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
                                    meeting_type: str = "demo") -> dict:
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
        generator = GoogleMeetGenerator()
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
