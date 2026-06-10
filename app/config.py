from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str
    OLLAMA_BASE_URL: str
    OLLAMA_MODEL: str = "llama3"
    GARMIN_ENCRYPTION_KEY: str
    SECRET_KEY: str
    GARMIN_POLL_INTERVAL: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def fernet(self) -> Fernet:
        """Returns the Fernet cipher suite generated from the encryption key."""
        return Fernet(self.GARMIN_ENCRYPTION_KEY.strip().encode())

    def encrypt_value(self, value: str) -> str:
        """Encrypts a string using AES (Fernet)."""
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt_value(self, encrypted_value: str) -> str:
        """Decrypts a string using AES (Fernet)."""
        return self.fernet.decrypt(encrypted_value.encode()).decode()


settings = Settings()
