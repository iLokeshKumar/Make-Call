import abc

class TelephonyCommunicator(abc.ABC):
    @abc.abstractmethod
    async def receive(self):
        """Receive media payload from the provider."""
        pass

    @abc.abstractmethod
    async def send_media(self, b64_audio: str):
        """Send media payload to the provider."""
        pass

    @abc.abstractmethod
    async def clear_audio_buffer(self):
        """Clear any buffered audio at the provider/communicator level."""
        pass
