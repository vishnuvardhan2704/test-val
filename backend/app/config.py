import os
from dotenv import load_dotenv

load_dotenv()

# curl_cffi's bundled CA store isn't trusted on this network (TLS-inspecting
# proxy); force yfinance onto the plain `requests` backend, which respects
# the OS certificate store via pip-system-certs.
os.environ.setdefault("YF_DISABLE_CURL_CFFI", "1")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
PRIVATE_COMPANY_DISCOUNT = 0.25
TOP_N_PEERS = 5
