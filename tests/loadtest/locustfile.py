"""
Load Test: 20 Concurrent Chatbot Users — 5 Consecutive Chats Each

Spawns 20 users, each sends 5 consecutive messages to the streaming chat endpoint,
consumes the full SSE response for each, and tracks detailed request/response data.
The test auto-terminates once all 20 users have completed their 5 chats.

Features:
- 20 concurrent users × 5 chats = 100 total requests
- Detailed request/response logging with web UI display
- Session continuity across chats for each user
- Comprehensive metrics and failure tracking
- Real-time progress monitoring

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
    /chat/stream [Chat-N] — Individual chat round metrics

Web UI fields:
    # Users       → Total concurrent virtual users (default 20)
    Spawn rate    → Users added per second (default 2, so ramp-up takes 10s)
    Host          → Base URL of the API gateway
    RPS           → Requests per second across all users
    Response Time → Median / P95 / P99 end-to-end latency in ms
    Failures      → Count + percentage of failed requests (HTTP errors or empty responses)

Additional Web UI:
    Custom endpoint at /test-results shows detailed request/response data
"""

import json
import random
import time
import threading
from datetime import datetime
from flask import Flask, render_template_string
from threading import Thread

from locust import HttpUser, task, constant, events
from locust.web import WebUI

# ============================================================
# CONFIG
# ============================================================

TARGET_USERS = 20  # Test stops after this many users complete
CHATS_PER_USER = 5  # Each user sends 5 consecutive messages
TOTAL_EXPECTED_CHATS = TARGET_USERS * CHATS_PER_USER  # 100 total chats

# ============================================================
# SHARED STATE — tracks progress and stores detailed results
# ============================================================

_lock = threading.Lock()
_completed_users = 0
_completed_chats = 0
_detailed_results = []  # Store all request/response details

def _add_result(user_id, chat_num, question, response_text, session_id, 
                ttfc, total_time, chunk_count, status, error=None):
    """Add detailed result to shared storage."""
    global _detailed_results
    with _lock:
        _detailed_results.append({
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'chat_num': chat_num,
            'question': question,
            'response_text': response_text[:200] + '...' if len(response_text) > 200 else response_text,
            'response_length': len(response_text),
            'session_id': session_id,
            'ttfc': round(ttfc, 3),
            'total_time': round(total_time, 3),
            'chunk_count': chunk_count,
            'status': status,
            'error': error
        })

def _mark_chat_complete(environment):
    """Increment completed chat count."""
    global _completed_chats
    with _lock:
        _completed_chats += 1
        done = _completed_chats
    print(f"[Load Test] {done}/{TOTAL_EXPECTED_CHATS} chats completed")

def _mark_user_complete(environment):
    """Increment completed user count; quit when all users are done."""
    global _completed_users
    with _lock:
        _completed_users += 1
        done = _completed_users
    print(f"[Load Test] {done}/{TARGET_USERS} users completed all 5 chats")
    if done >= TARGET_USERS:
        print(f"\n✅ All {TARGET_USERS} users completed {CHATS_PER_USER} chats each ({TOTAL_EXPECTED_CHATS} total) — stopping test\n")
        environment.runner.quit()

def get_results_summary():
    """Get summary statistics of all results."""
    with _lock:
        results = _detailed_results.copy()
    
    if not results:
        return {
            'total_chats': 0,
            'successful_chats': 0,
            'failed_chats': 0,
            'avg_ttfc': 0,
            'avg_total_time': 0,
            'avg_response_length': 0
        }
    
    successful = [r for r in results if r['status'] == 'success']
    failed = [r for r in results if r['status'] == 'failed']
    
    return {
        'total_chats': len(results),
        'successful_chats': len(successful),
        'failed_chats': len(failed),
        'success_rate': round(len(successful) / len(results) * 100, 1) if results else 0,
        'avg_ttfc': round(sum(r['ttfc'] for r in successful) / len(successful), 3) if successful else 0,
        'avg_total_time': round(sum(r['total_time'] for r in successful) / len(successful), 3) if successful else 0,
        'avg_response_length': round(sum(r['response_length'] for r in successful) / len(successful), 1) if successful else 0,
        'results': results[-50:]  # Show last 50 results
    }


# ============================================================
# QUESTIONS — Stockholm-focused conversation sequences and individual questions
# ============================================================

CHAT_SEQUENCES = [
    # Sequence 1: Tourist planning visit to Stockholm
    [
        "Hi, I'm planning a trip to Stockholm. Can you help me?",
        "What are the must-see attractions in Stockholm?",
        "Tell me about the Vasa Museum and Nobel Prize ceremonies",
        "How does Stockholm's public transportation work?",
        "What's the best time of year to visit Stockholm?"
    ],
    # Sequence 2: Learning about Stockholm's history
    [
        "Hello, I'd like to learn about Stockholm's history",
        "When was Stockholm founded and by whom?",
        "What happened during the Stockholm Bloodbath?",
        "How did Stockholm become Sweden's capital?",
        "Tell me about Stockholm during the Swedish Empire period"
    ],
    # Sequence 3: Stockholm geography and climate
    [
        "Good morning, I have questions about Stockholm's geography",
        "How many islands is Stockholm built on?",
        "What's Stockholm's climate like throughout the year?",
        "Tell me about the Stockholm archipelago",
        "How does Stockholm compare to other Nordic capitals?"
    ],
    # Sequence 4: Stockholm culture and education
    [
        "I'm interested in Stockholm's cultural scene",
        "What universities and educational institutions are in Stockholm?",
        "Tell me about Stockholm's museums and art galleries",
        "What's special about Stockholm's metro system?",
        "How is Stockholm connected to the Nobel Prize?"
    ],
    # Sequence 5: Stockholm economy and technology
    [
        "Hi there, I want to know about Stockholm's economy",
        "What major companies are headquartered in Stockholm?",
        "Why is Stockholm called Europe's innovation hub?",
        "Tell me about Stockholm's role in the tech industry",
        "What makes Stockholm attractive for businesses?"
    ]
]

# Additional individual questions based on Stockholm Wikipedia content
INDIVIDUAL_QUESTIONS = [
    "What does the name Stockholm mean?",
    "How many people live in Stockholm?",
    "What is Stockholm's nickname 'Venice of the North'?",
    "Tell me about Gamla Stan, Stockholm's Old Town",
    "What is the Royal Palace in Stockholm?",
    "How does Stockholm's congestion pricing system work?",
    "What is Drottningholm Palace?",
    "Tell me about Stockholm's green spaces and parks",
    "What is the Stockholm Stock Exchange?",
    "How many museums does Stockholm have?",
    "What is Skansen open-air museum?",
    "Tell me about ABBA and Stockholm's music scene",
    "What sports teams are popular in Stockholm?",
    "How does Stockholm handle environmental sustainability?",
    "What is the Stockholm Marathon?",
    "Tell me about Stockholm's restaurant scene",
    "What is the Stockholm archipelago?",
    "How does Stockholm's metro art gallery work?",
    "What is Stockholm Pride festival?",
    "Tell me about Stockholm's winter and summer daylight hours",
    "What is Karolinska Institute?",
    "How did Stockholm host the 1912 Olympics?",
    "What is Stockholm City Hall famous for?",
    "Tell me about Stockholm's population diversity",
    "What is the Stockholm Water Festival?"
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
    Simulates a single chatbot visitor making 5 consecutive chats.

    Each user sends 5 messages in sequence, maintaining session continuity,
    waits for the full streaming response for each, reports detailed metrics,
    then idles until the test stops.
    """

    # After all 5 chats, idle forever (test will quit via _mark_user_complete)
    wait_time = constant(999_999)

    def on_start(self):
        self.session_id = ""  # Will be set after first chat
        self.user_num = random.randint(1000, 9999)
        self.chat_count = 0
        self.done = False
        
        # Choose a conversation sequence or random questions
        if random.random() < 0.7:  # 70% use predefined sequences
            self.questions = random.choice(CHAT_SEQUENCES)
        else:  # 30% use random individual questions
            self.questions = random.sample(INDIVIDUAL_QUESTIONS, 5)
        
        print(f"[User-{self.user_num}] Spawned — will ask {len(self.questions)} questions")

    @task
    def send_chat_message(self):
        if self.done or self.chat_count >= CHATS_PER_USER:
            return

        current_question = self.questions[self.chat_count]
        chat_num = self.chat_count + 1

        payload = {
            "message": current_question,
            "session_id": self.session_id,  # Maintain session across chats
        }

        start_time = time.time()

        try:
            with self.client.post(
                "/api/v1/gateway/chatbot/chat/stream",
                json=payload,
                stream=True,
                catch_response=True,
                timeout=120,
                name=f"/chat/stream [Chat-{chat_num}]",
            ) as response:

                if response.status_code != 200:
                    # Read body for diagnostics (first 300 chars)
                    try:
                        body = response.text[:300]
                    except Exception:
                        body = "<unreadable>"
                    reason = f"HTTP {response.status_code}"
                    response.failure(reason)
                    
                    # Log detailed failure
                    _add_result(
                        self.user_num, chat_num, current_question, "", 
                        self.session_id, 0, time.time() - start_time, 0, 
                        "failed", f"{reason}: {body}"
                    )
                    
                    print(
                        f"[User-{self.user_num}] ❌ Chat {chat_num}/5 - {reason} | "
                        f"Body: {body}"
                    )
                    self.chat_count += 1
                    _mark_chat_complete(self.environment)
                    
                    if self.chat_count >= CHATS_PER_USER:
                        self.done = True
                        _mark_user_complete(self.environment)
                    return

                full_text, new_session_id, ttfc, chunk_count = consume_sse_stream(response)
                total_time = time.time() - start_time

                # Update session ID for continuity
                if new_session_id:
                    self.session_id = new_session_id

                if full_text:
                    response.success()
                    
                    # Log detailed success
                    _add_result(
                        self.user_num, chat_num, current_question, full_text,
                        self.session_id, ttfc, total_time, chunk_count, "success"
                    )
                    
                    print(
                        f"[User-{self.user_num}] ✅ Chat {chat_num}/5 - "
                        f"\"{current_question[:30]}...\" → "
                        f"{len(full_text)} chars, {chunk_count} chunks | "
                        f"TTFC: {ttfc:.2f}s | Total: {total_time:.2f}s"
                    )

                    # Fire custom metrics
                    events.request.fire(
                        request_type="SSE",
                        name="/chat/stream [TTFC]",
                        response_time=ttfc * 1000,
                        response_length=0,
                        exception=None,
                        context={},
                    )
                    
                    events.request.fire(
                        request_type="SSE",
                        name="/chat/stream",
                        response_time=total_time * 1000,
                        response_length=len(full_text),
                        exception=None,
                        context={},
                    )
                else:
                    response.failure("Empty response — likely gateway timeout")
                    
                    # Log detailed failure
                    _add_result(
                        self.user_num, chat_num, current_question, "",
                        self.session_id, ttfc, total_time, chunk_count, 
                        "failed", "Empty AI response"
                    )
                    
                    print(
                        f"[User-{self.user_num}] ❌ Chat {chat_num}/5 - Empty AI response | "
                        f"Elapsed: {total_time:.1f}s | "
                        f"Chunks received: {chunk_count} | "
                        f"Session: {new_session_id or 'none'}"
                    )

        except Exception as e:
            error_msg = str(e)[:100]
            print(f"[User-{self.user_num}] ❌ Chat {chat_num}/5 - ERROR: {error_msg}")
            
            # Log detailed error
            _add_result(
                self.user_num, chat_num, current_question, "",
                self.session_id, 0, time.time() - start_time, 0,
                "failed", error_msg
            )

        self.chat_count += 1
        _mark_chat_complete(self.environment)
        
        # Check if this user is done with all 5 chats
        if self.chat_count >= CHATS_PER_USER:
            self.done = True
            _mark_user_complete(self.environment)
            print(f"[User-{self.user_num}] 🎉 Completed all {CHATS_PER_USER} chats!")
        else:
            # Small delay between chats to simulate realistic user behavior
            time.sleep(random.uniform(1, 3))


# ============================================================
# WEB UI EXTENSION — Custom endpoint for detailed results
# ============================================================

# HTML template for results page
RESULTS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Load Test Results - Detailed View</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .header { text-align: center; color: #333; margin-bottom: 30px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .stat-card { background: #f8f9fa; padding: 15px; border-radius: 6px; text-align: center; border-left: 4px solid #007bff; }
        .stat-value { font-size: 24px; font-weight: bold; color: #007bff; }
        .stat-label { font-size: 12px; color: #666; text-transform: uppercase; }
        .results-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .results-table th, .results-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .results-table th { background: #f8f9fa; font-weight: bold; }
        .status-success { color: #28a745; font-weight: bold; }
        .status-failed { color: #dc3545; font-weight: bold; }
        .refresh-btn { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin-bottom: 20px; }
        .refresh-btn:hover { background: #0056b3; }
        .progress { background: #e9ecef; border-radius: 4px; height: 20px; margin: 10px 0; }
        .progress-bar { background: #007bff; height: 100%; border-radius: 4px; transition: width 0.3s; }
    </style>
    <script>
        function refreshResults() {
            location.reload();
        }
        // Auto-refresh every 5 seconds
        setInterval(refreshResults, 5000);
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Chatbot Load Test Results</h1>
            <p>20 Users × 5 Chats Each = 100 Total Conversations</p>
            <button class="refresh-btn" onclick="refreshResults()">🔄 Refresh Now</button>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{{ summary.total_chats }}</div>
                <div class="stat-label">Total Chats</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.successful_chats }}</div>
                <div class="stat-label">Successful</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.failed_chats }}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.success_rate }}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.avg_ttfc }}s</div>
                <div class="stat-label">Avg TTFC</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.avg_total_time }}s</div>
                <div class="stat-label">Avg Total Time</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.avg_response_length }}</div>
                <div class="stat-label">Avg Response Length</div>
            </div>
        </div>

        <div class="progress">
            <div class="progress-bar" style="width: {{ (summary.total_chats / 100 * 100) }}%"></div>
        </div>
        <p style="text-align: center; color: #666;">Progress: {{ summary.total_chats }}/100 chats completed</p>

        <h2>Recent Results (Last 50)</h2>
        <table class="results-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>User</th>
                    <th>Chat #</th>
                    <th>Question</th>
                    <th>Response Preview</th>
                    <th>Length</th>
                    <th>TTFC</th>
                    <th>Total</th>
                    <th>Chunks</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for result in summary.results %}
                <tr>
                    <td>{{ result.timestamp[11:19] }}</td>
                    <td>{{ result.user_id }}</td>
                    <td>{{ result.chat_num }}/5</td>
                    <td title="{{ result.question }}">{{ result.question[:40] }}{% if result.question|length > 40 %}...{% endif %}</td>
                    <td title="{{ result.response_text }}">{{ result.response_text[:50] }}{% if result.response_text|length > 50 %}...{% endif %}</td>
                    <td>{{ result.response_length }}</td>
                    <td>{{ result.ttfc }}s</td>
                    <td>{{ result.total_time }}s</td>
                    <td>{{ result.chunk_count }}</td>
                    <td class="status-{{ result.status }}">{{ result.status.upper() }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        
        {% if summary.results|length == 0 %}
        <p style="text-align: center; color: #666; margin: 40px 0;">No results yet. Start the load test to see data here.</p>
        {% endif %}
    </div>
</body>
</html>
"""

def setup_web_ui_extension(environment):
    """Add custom endpoint to Locust's web UI for detailed results."""
    if hasattr(environment, 'web_ui') and environment.web_ui:
        app = environment.web_ui.app
        
        @app.route("/test-results")
        def test_results():
            summary = get_results_summary()
            return render_template_string(RESULTS_TEMPLATE, summary=summary)
        
        print("📊 Custom results page available at: http://localhost:8089/test-results")

# Hook into Locust events
@events.init.add_listener
def on_locust_init(environment, **kwargs):
    setup_web_ui_extension(environment)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║   CHATBOT LOAD TEST — 20 Users × 5 Chats = 100 Total     ║
╚═══════════════════════════════════════════════════════════╝

Run with Web UI:
  locust -f locustfile.py --host=https://api-gateway-common.up.railway.app

Run headless:
  locust -f locustfile.py \\
      --host=https://api-gateway-common.up.railway.app \\
      --users=20 --spawn-rate=2 --headless

What happens:
  1. Spawns 20 users at 2/sec (ramp-up over 10 seconds)
  2. Each user sends 5 consecutive messages to /chat/stream
  3. Session continuity maintained across all 5 chats per user
  4. Full SSE response consumed and detailed metrics collected
  5. Test auto-stops once all users complete their 5 chats

Metrics (Web UI at http://localhost:8089):
  /chat/stream [Chat-N]   → Individual chat round performance
  /chat/stream            → Overall end-to-end time
  /chat/stream [TTFC]     → Time to first chunk (bot starts typing)

📊 Detailed Results: http://localhost:8089/test-results
   - Real-time request/response data
   - Success/failure tracking
   - Performance metrics per chat
   - Auto-refreshes every 5 seconds

Total Expected: {TARGET_USERS} users × {CHATS_PER_USER} chats = {TOTAL_EXPECTED_CHATS} conversations
""")
