"""
Load Test: 20 Concurrent Chatbot Users — Single Round

Spawns 20 users, each sends ONE message to the streaming chat endpoint,
consumes the full SSE response, and stops. The test auto-terminates once
all 20 users have completed their request.

Install:
    pip install -r requirements.txt

Run with Web UI (http://localhost:8089):
    locust -f locustfile.py --host=https://api-gateway-common.up.railway.app

Run headless:
    locust -f locustfile.py \\
        --host=https://api-gateway-common.up.railway.app \\
        --users=20 --spawn-rate=2 --headless

Metrics tracked:
    /chat/stream        — Full end-to-end response time (request → stream done)
    /chat/stream [TTFC] — Time to first chunk (how fast the bot starts typing)

Web UI fields:
    # Users       → Total concurrent virtual users (default 20)
    Spawn rate    → Users added per second (default 2, so ramp-up takes 10s)
    Host          → Base URL of the API gateway
    RPS           → Requests per second across all users
    Response Time → Median / P95 / P99 end-to-end latency in ms
    Failures      → Count + percentage of failed requests (HTTP errors or empty responses)
"""

import json
import random
import time
import threading

from locust import HttpUser, task, constant, events

# ============================================================
# CONFIG
# ============================================================

TARGET_USERS = 20  # Test stops after this many users complete

# ============================================================
# SHARED STATE — tracks how many users have finished
# ============================================================

_lock = threading.Lock()
_completed_users = 0


def _mark_complete(environment):
    """Increment completed count; quit the runner when all users are done."""
    global _completed_users
    with _lock:
        _completed_users += 1
        done = _completed_users
    print(f"[Load Test] {done}/{TARGET_USERS} users completed")
    if done >= TARGET_USERS:
        print("\n✅ All users completed — stopping test\n")
        environment.runner.quit()


# ============================================================
# QUESTIONS — varied prompts to exercise different RAG paths
# ============================================================

QUESTIONS = [
    # Greetings (no RAG needed)
    "Hi, I need some help",
    "Hello there",
    "Hey, can you assist me?",
    "Good morning",
    # General / FAQ
    "What products do you offer?",
    "Tell me about your pricing plans",
    "What is your return policy?",
    "Do you ship internationally?",
    "What payment methods do you accept?",
    # Knowledge-base questions (triggers RAG)
    "How do I place an order?",
    "What are the shipping costs?",
    "How do I track my order?",
    "Can you explain the warranty policy?",
    "What is the estimated delivery time?",
    "How do I update my shipping address?",
    "Do you offer bulk discounts?",
    "What are the product specifications?",
    "How do I contact customer support?",
    "Tell me about your loyalty program",
    "What is the cancellation process?",
]


# ============================================================
# SSE STREAM CONSUMER
# ============================================================

def consume_sse_stream(response):
    """
    Read the full SSE stream and return metrics.

    Returns:
        (full_text, session_id, time_to_first_chunk_s, chunk_count)
    """
    full_text = ""
    session_id = None
    first_chunk_time = None
    chunk_count = 0
    start = time.time()

    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue

        data_str = line[6:]  # strip "data: " prefix

        if data_str == "[DONE]":
            break

        try:
            parsed = json.loads(data_str)

            if parsed.get("type") == "session_created" and parsed.get("session_id"):
                session_id = parsed["session_id"]

            elif parsed.get("type") == "chunk" and parsed.get("content"):
                if first_chunk_time is None:
                    first_chunk_time = time.time() - start
                full_text += parsed["content"]
                chunk_count += 1

            elif parsed.get("type") == "complete":
                full_text = parsed.get("content", full_text)
                break

            elif parsed.get("type") == "error":
                raise Exception(parsed.get("content", "Unknown SSE error"))

        except json.JSONDecodeError:
            continue

    ttfc = first_chunk_time if first_chunk_time is not None else (time.time() - start)
    return full_text, session_id, ttfc, chunk_count


# ============================================================
# LOCUST USER
# ============================================================

class ChatbotUser(HttpUser):
    """
    Simulates a single chatbot visitor.

    Each user sends exactly ONE message, waits for the full streaming
    response, reports metrics, then idles until the test stops.
    """

    # After the single request, idle forever (test will quit via _mark_complete)
    wait_time = constant(999_999)

    def on_start(self):
        self.session_id = None
        self.question = random.choice(QUESTIONS)
        self.done = False
        self.user_num = random.randint(1000, 9999)
        print(f"[User-{self.user_num}] Spawned — will ask: \"{self.question[:50]}\"")

    @task
    def send_chat_message(self):
        if self.done:
            return

        payload = {
            "message": self.question,
            "session_id": "",  # new session every time
        }

        start_time = time.time()

        try:
            with self.client.post(
                "/api/v1/gateway/chatbot/chat/stream",
                json=payload,
                stream=True,
                catch_response=True,
                timeout=120,
                name="/chat/stream",
            ) as response:

                if response.status_code != 200:
                    # Read body for diagnostics (first 300 chars)
                    try:
                        body = response.text[:300]
                    except Exception:
                        body = "<unreadable>"
                    reason = f"HTTP {response.status_code}"
                    response.failure(reason)
                    print(
                        f"[User-{self.user_num}] ❌ {reason} | "
                        f"Body: {body}"
                    )
                    self.done = True
                    _mark_complete(self.environment)
                    return

                full_text, new_session_id, ttfc, chunk_count = consume_sse_stream(response)
                total_time = time.time() - start_time

                if new_session_id:
                    self.session_id = new_session_id

                if full_text:
                    response.success()
                    print(
                        f"[User-{self.user_num}] ✅ "
                        f"\"{self.question[:30]}...\" → "
                        f"{len(full_text)} chars, {chunk_count} chunks | "
                        f"TTFC: {ttfc:.2f}s | Total: {total_time:.2f}s"
                    )

                    # Fire custom metric for time-to-first-chunk
                    events.request.fire(
                        request_type="SSE",
                        name="/chat/stream [TTFC]",
                        response_time=ttfc * 1000,
                        response_length=0,
                        exception=None,
                        context={},
                    )
                else:
                    response.failure("Empty response — likely gateway 30s timeout under load")
                    print(
                        f"[User-{self.user_num}] ❌ Empty AI response | "
                        f"Elapsed: {total_time:.1f}s | "
                        f"Chunks received: {chunk_count} | "
                        f"Session: {new_session_id or 'none'}"
                    )

        except Exception as e:
            print(f"[User-{self.user_num}] ❌ ERROR: {str(e)[:100]}")

        self.done = True
        _mark_complete(self.environment)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════╗
║   CHATBOT LOAD TEST — 20 Users, Single Round, Auto-Stop  ║
╚═══════════════════════════════════════════════════════════╝

Run with Web UI:
  locust -f locustfile.py --host=https://api-gateway-common.up.railway.app

Run headless:
  locust -f locustfile.py \\
      --host=https://api-gateway-common.up.railway.app \\
      --users=20 --spawn-rate=2 --headless

What happens:
  1. Spawns 20 users at 2/sec (ramp-up over 10 seconds)
  2. Each user sends ONE message to /chat/stream
  3. Full SSE response is consumed and measured
  4. Test auto-stops once all 20 users have completed

Metrics (Web UI at http://localhost:8089):
  /chat/stream        → End-to-end time (request → stream fully consumed)
  /chat/stream [TTFC] → Time to first chunk (bot starts typing)
""")
