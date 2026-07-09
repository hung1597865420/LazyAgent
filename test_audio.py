"""Test kết nối gpt-audio-1.5 trên Azure AI Foundry."""
import os
from dotenv import load_dotenv

load_dotenv()

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
api_key  = os.getenv("AZURE_OPENAI_API_KEY", "")

# Audio model dùng AzureOpenAI classic client (không phải Foundry base_url)
# Thử cả 2 cách vì Target URI trống trên portal

print(f"Endpoint: {endpoint}")
print(f"Key: {api_key[:8]}...")
print()

# Cách 1: qua Foundry endpoint (services.ai.azure.com)
try:
    from openai import OpenAI
    base_url = endpoint.split("/chat/completions")[0].rstrip("/")
    if not base_url.endswith("/models"):
        base_url += "/models"

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_query={"api-version": "2025-04-01-preview"},
    )
    resp = client.audio.speech.create(
        model="gpt-audio-1.5",
        input="Hello, test connection.",
        voice="alloy",
    )
    with open("test_audio_output.mp3", "wb") as f:
        f.write(resp.content)
    print("[PASS] Way 1 (Foundry endpoint) - saved: test_audio_output.mp3")

except Exception as e:
    print(f"[FAIL] Way 1: {e}")

# Cách 2: qua AzureOpenAI classic endpoint
try:
    from openai import AzureOpenAI
    # Suy ra classic endpoint từ Foundry endpoint
    host     = endpoint.split("://")[-1].split("/")[0]
    resource = host.split(".")[0]
    classic  = f"https://{resource}.openai.azure.com"

    client2 = AzureOpenAI(
        azure_endpoint=classic,
        api_key=api_key,
        api_version="2025-04-01-preview",
    )
    resp2 = client2.audio.speech.create(
        model="gpt-audio-1.5",
        input="Hello, test connection.",
        voice="alloy",
    )
    with open("test_audio_output2.mp3", "wb") as f:
        f.write(resp2.content)
    print(f"[PASS] Way 2 (classic endpoint: {classic}) - saved: test_audio_output2.mp3")

except Exception as e:
    print(f"[FAIL] Way 2: {e}")
