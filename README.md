# AI Voice & SMS Assistant (Rio)

A real-time AI voice assistant capable of holding natural, low-latency conversations over the phone. Powered by **Twilio Media Streams** and **Google Gemini Multimodal Live API**.

Currently customized as "Rio", a sales assistant for **Yexis Electronics**.

## 🚀 Features

-   **Real-time Voice AI**: <1s latency conversations using WebSockets.
-   **SMS Capabilities**: Send and receive SMS messages (with auto-reply).
-   **Intelligent Persona**: "Rio" knows product catalogs (Samsung B2B) and can conduct sales conversations.
-   **Audio Transcoding**: Handles Twilio (8kHz mu-law) <-> Gemini (High-Fidelity PCM) conversion on the fly.
-   **Resiliency**: Auto-reconnection logic and silence handling.

## 🛠️ Tech Stack

-   **Python 3.12+**
-   **FastAPI** (Web Server)
-   **Uvicorn** (ASGI Server)
-   **Twilio** (Telephony & SMS)
-   **Google Gemini 2.0 Flash Exp** (LLM & Voice Generation)
-   **WebSockets** (Streaming Audio)

## 📦 Setup

1.  **Clone the repository**
    ```bash
    git clone https://github.com/iLokeshKumar/Make-Call.git
    cd Make-Call
    ```

2.  **Install Dependencies**
    Navigate to the source code folder and install:
    ```bash
    cd outbound-calling-speech-assistant-openai-realtime-api-python
    pip install -r requirements.txt
    ```

3.  **Environment Variables**
    Create a `.env` file in the source folder with your credentials:
    ```env
    TWILIO_ACCOUNT_SID=your_sid
    TWILIO_AUTH_TOKEN=your_token
    PHONE_NUMBER_FROM=+1234567890
    GEMINI_API_KEY=your_google_ai_key
    DOMAIN=your-ngrok-url.ngrok-free.app
    PORT=6060
    ```

4.  **Run the Server**
    ```bash
    python main.py
    ```

5.  **Expose to Internet (Ngrok)**
    Twilio needs a public URL to connect to your localhost.
    ```bash
    ngrok http 6060
    ```
    *Copy the ngrok URL and update `DOMAIN` in your `.env` file.*

## 📞 Usage

-   **Make a Call**: Send a POST request to `/make-call` with the destination number.
-   **Receive SMS**: Configure your Twilio number's messaging webhook to `https://[your-ngrok]/incoming-sms`.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
