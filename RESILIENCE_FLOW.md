# Gemini API Resilience Flow

## Request Flow with All Three Patterns

```
┌─────────────────────────────────────────────────────────────────┐
│                    Incoming Chat Request                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  PATTERN 3: Circuit Breaker Check                                │
│  Is circuit OPEN for gemini-2.5-flash-lite?                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    YES ←─────┴─────→ NO
                     ↓                 ↓
        ┌────────────────────┐   ┌────────────────────┐
        │ Skip to Fallback   │   │ Try Primary Model  │
        │ (gemini-2.0-flash) │   │ (2.5-flash-lite)   │
        └────────────────────┘   └────────────────────┘
                     ↓                 ↓
                     │            SUCCESS? ──→ Reset Circuit Breaker
                     │                 ↓              ↓
                     │                NO         Return Response
                     │                 ↓
                     │         ┌──────────────────┐
                     │         │  503 Error?      │
                     │         └──────────────────┘
                     │                 ↓
                     │         YES ←───┴───→ NO
                     │          ↓              ↓
                     │    ┌──────────────┐    Record Failure
                     │    │ PATTERN 1:   │    Propagate Error
                     │    │ Exponential  │
                     │    │ Backoff      │
                     │    └──────────────┘
                     │          ↓
                     │    Attempt 1: Wait ~1s
                     │    Attempt 2: Wait ~2s
                     │    Attempt 3: Wait ~3s
                     │          ↓
                     │    Still Failing?
                     │          ↓
                     │         YES
                     │          ↓
                     │    Record Failures
                     │    Circuit Tripped?
                     │          ↓
                     └──────────┴──────────┐
                                           ↓
                              ┌────────────────────────┐
                              │  PATTERN 2:            │
                              │  Model Fallback        │
                              │  Try gemini-2.0-flash  │
                              └────────────────────────┘
                                           ↓
                                    SUCCESS? ──→ Return Response
                                           ↓
                                          NO
                                           ↓
                              ┌────────────────────────┐
                              │  Return User-Friendly  │
                              │  Error Message         │
                              └────────────────────────┘
```

## Circuit Breaker State Machine

```
                    ┌──────────────┐
                    │   CLOSED     │
                    │  (Normal)    │
                    └──────────────┘
                           ↓
                    Request passes
                    through normally
                           ↓
                    ┌──────────────┐
                    │  10 failures │
                    │  in 60s?     │
                    └──────────────┘
                           ↓
                          YES
                           ↓
                    ┌──────────────┐
                    │     OPEN     │
                    │  (Tripped)   │
                    │  Block 60s   │
                    └──────────────┘
                           ↓
                    Use fallback
                    immediately
                           ↓
                    Wait 60 seconds
                           ↓
                    ┌──────────────┐
                    │  HALF-OPEN   │
                    │ (Cooldown)   │
                    └──────────────┘
                           ↓
                    Try request
                           ↓
                    ┌──────────────┐
                    │  SUCCESS?    │
                    └──────────────┘
                           ↓
                    YES ←──┴──→ NO
                     ↓          ↓
              ┌──────────┐  ┌──────────┐
              │  CLOSED  │  │   OPEN   │
              │  Reset   │  │  Again   │
              └──────────┘  └──────────┘
```

## Example Scenarios

### Scenario 1: Temporary Spike (Backoff Works)
```
Request 1: 503 → Wait 1s → Retry → SUCCESS ✅
Circuit: Still CLOSED (only 1 failure)
```

### Scenario 2: Sustained Outage (Circuit Trips)
```
Request 1: 503 → Retry 3x → FAIL → Record failure
Request 2: 503 → Retry 3x → FAIL → Record failure
...
Request 10: 503 → Circuit TRIPS 🔴
Request 11-N: Circuit OPEN → Use gemini-2.0-flash immediately
After 60s: Circuit HALF-OPEN → Try 2.5-flash-lite again
```

### Scenario 3: Fallback Success
```
Request: 503 → Retry 3x → FAIL
→ Fallback to gemini-2.0-flash → SUCCESS ✅
User sees response (never knew there was an issue)
```

## Key Metrics to Monitor

1. **503 Error Rate**: Track frequency of 503 errors
2. **Fallback Usage**: How often gemini-2.0-flash is used
3. **Circuit Breaker Trips**: How often circuit opens
4. **Retry Success Rate**: % of requests that succeed after retry
5. **Average Response Time**: Impact of retries on latency

## Cost Implications

- **Primary Model** (gemini-2.5-flash-lite): Lower cost
- **Fallback Model** (gemini-2.0-flash): ~20-30% higher cost
- **Circuit Breaker**: Reduces unnecessary retries, saves costs
- **Net Effect**: Minimal cost increase, major reliability improvement
