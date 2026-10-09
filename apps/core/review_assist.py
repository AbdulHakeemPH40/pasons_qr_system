"""
AI review assist (spec section 39).

The customer writes a half review on the smart page, this module asks the
LLM for improved versions of that exact draft, the customer picks one,
copies it and posts it on Google (Google has no API to post reviews on a
guest's behalf, so the final post always happens on Google itself).

Contract:
  - suggestions come from the LLM only — nothing is templated or canned;
  - the reply is plain text: NO labels/tones, NO emojis (asked of the model
    in the system prompt, then stripped defensively);
  - the guest's own meaning and language are kept, facts are never invented.

Provider order (all optional via environment variables):

    MIMO_API_KEY     preferred (Xiaomi MiMo, OpenAI-compatible). Two
                       endpoints are tried in order: the main API
                       (https://api.xiaomimimo.com/v1, override with
                       MIMO_BASE_URL) and the token-plan endpoint
                       (https://token-plan-sgp.xiaomimimo.com/v1, override
                       with MIMO_TOKEN_PLAN_URL). Model via MIMO_MODEL,
                       default mimo-v2.6-flash (the endpoint serves
                       mimo-v2.5, mimo-v2.5-pro, mimo-v2.6-flash,
                       mimo-v2.6-pro). Token-plan keys can be set
                       separately with MIMO_TOKEN_PLAN_API_KEY.
    DEEPSEEK_API_KEY (+ DEEPSEEK_MODEL, default deepseek-chat)
    GEMINI_API_KEY   (+ GEMINI_MODEL, default gemini-2.5-flash)

HTTP calls use the stdlib only (urllib) — no third-party packages needed.
With no key configured (or if every provider errors) the draft is returned
lightly tidied — the guest's own words only, never invented sentences.
"""

import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TIMEOUT = 15  # seconds per provider call
MAX_LEN = 2000
WANT = 6  # improved versions to ask the model for

SYSTEM_PROMPT = (
    "You improve short Google reviews for restaurants. The guest sends a rough "
    "draft in their own words and language. Return improved versions of that "
    "same review.\n"
    f"Reply with ONLY a JSON array of exactly {WANT} strings.\n"
    "Each string is one complete improved version of the guest's review.\n"
    "Plain text only: never use emojis, emoticons, star symbols or tone labels. "
    "No numbering, no quotation marks inside the strings.\n"
    "Keep the guest's own meaning and language; fix grammar and spelling; sound "
    "natural and human. Do not invent facts, dishes, names or feelings the "
    "guest did not write."
)

# Emoji / pictograph / emoticon characters (incl. variation selectors, ZWJ,
# skin tones and keycaps) — stripped from model output as a safety net.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\uFE0E\uFE0F\u200D\u20E3\u20DE\u20DF]+"
)


def suggest_variants(text, brand_name="", outlet_name=""):
    """Return {"variants": [str x6], "provider": name} — plain strings only."""
    draft = re.sub(r"\s+", " ", (text or "")).strip()[:MAX_LEN]

    for provider in (_mimo, _deepseek, _gemini):
        name = provider.__name__.lstrip("_")
        if not _has_key(name):
            continue
        try:
            variants = provider(draft, brand_name, outlet_name)
        except Exception:
            continue  # never let an AI outage break the customer flow
        if variants:
            return {"variants": variants[:WANT], "provider": name}

    cleaned = _clean_own_words(draft)
    return {"variants": [cleaned] if cleaned else [], "provider": "local"}


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------

def _has_key(name):
    if name == "mimo":
        return bool(os.environ.get("MIMO_API_KEY")
                    or os.environ.get("MIMO_TOKEN_PLAN_API_KEY"))
    return bool(os.environ.get({"deepseek": "DEEPSEEK_API_KEY",
                                "gemini": "GEMINI_API_KEY"}[name]))


def _user_prompt(draft, brand_name, outlet_name):
    where = " ".join(p for p in (brand_name, outlet_name) if p)
    head = f"Restaurant: {where}\n" if where else ""
    return f'{head}Guest\'s draft review:\n"""{draft}"""'


def _post_json(url, payload, headers=None):
    """POST JSON using the stdlib only (no third-party HTTP dependency)."""
    body = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json",
              "User-Agent": "pasons-review-assist/1.0"}
    if headers:
        merged.update(headers)
    request = Request(url, data=body, headers=merged, method="POST")
    with urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _chat_completion(base, api_key, model, draft, brand_name, outlet_name):
    """One OpenAI-compatible chat call (MiMo and DeepSeek share this shape)."""
    data = _post_json(
        f"{base.rstrip('/')}/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(draft, brand_name, outlet_name)},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return _parse(data["choices"][0]["message"]["content"])


MIMO_ENDPOINTS = (
    ("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
    ("MIMO_TOKEN_PLAN_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
)


def _mimo_endpoints():
    """(base, key) pairs to try in order.

    Two Xiaomi MiMo OpenAI-compatible endpoints: the main API
    (api.xiaomimimo.com) and the token-plan endpoint
    (token-plan-sgp.xiaomimimo.com). Each key is tried on its own endpoint
    first (that is where it is valid), then on the other endpoint as a
    fallback — a single key often works on both.
    """
    bases = {env: os.environ.get(env, default).rstrip("/")
             for env, default in MIMO_ENDPOINTS}
    main_key = os.environ.get("MIMO_API_KEY") or ""
    plan_key = os.environ.get("MIMO_TOKEN_PLAN_API_KEY") or ""

    candidates = []
    if main_key:
        candidates.append((bases["MIMO_BASE_URL"], main_key))
    if plan_key:
        candidates.append((bases["MIMO_TOKEN_PLAN_URL"], plan_key))
    if main_key:  # cross-endpoint fallbacks
        candidates.append((bases["MIMO_TOKEN_PLAN_URL"], main_key))
    if plan_key:
        candidates.append((bases["MIMO_BASE_URL"], plan_key))

    pairs, seen = [], set()
    for base, key in candidates:
        if base not in seen:
            seen.add(base)
            pairs.append((base, key))
    return pairs


def _mimo(draft, brand_name, outlet_name):
    """Xiaomi MiMo (preferred): main API first, then the token-plan endpoint."""
    model = os.environ.get("MIMO_MODEL", "mimo-v2.6-flash")
    last_error = None
    for base, key in _mimo_endpoints():
        try:
            return _chat_completion(base, key, model,
                                    draft, brand_name, outlet_name)
        except Exception as error:  # endpoint down/unauthorized -> try next
            last_error = error
    if last_error:
        raise last_error
    return None


def _deepseek(draft, brand_name, outlet_name):
    return _chat_completion(
        "https://api.deepseek.com",
        os.environ["DEEPSEEK_API_KEY"],
        os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        draft, brand_name, outlet_name,
    )


def _gemini(draft, brand_name, outlet_name):
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?" + urlencode({"key": os.environ["GEMINI_API_KEY"]}))
    data = _post_json(url, {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user",
                      "parts": [{"text": _user_prompt(draft, brand_name, outlet_name)}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000},
    })
    return _parse(data["candidates"][0]["content"]["parts"][0]["text"])


# --------------------------------------------------------------------------
# parsing + no-LLM fallback
# --------------------------------------------------------------------------

def _parse(content):
    """Extract plain improved versions from model output; tolerant by design.

    Accepts a JSON array of strings (the requested shape), a JSON array of
    {"text": ...} objects, or plain numbered/bulleted lines. Labels and
    emojis are removed — the customer sees clean text only.
    """
    raw = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.M).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None

    texts = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                texts.append(str(item["text"]))  # tolerate {"label","text"} shape
    else:
        for line in raw.splitlines():
            line = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip()
            if line:
                texts.append(line)

    variants, seen = [], set()
    for text in texts:
        cleaned = _strip_emoji(str(text)).strip().strip('"').strip()[:MAX_LEN]
        key = cleaned.lower()
        if len(cleaned) >= 3 and key not in seen:
            variants.append(cleaned)
            seen.add(key)
    return variants


def _strip_emoji(text):
    # collapse the gaps emojis leave behind ("Nice food 👍 we" -> "Nice food we")
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", text))


def _clean_own_words(draft):
    """No-key fallback: the guest's own words, lightly tidied. Nothing invented."""
    if not draft:
        return ""
    text = re.sub(r"\s+([,.;!?])", r"\1", draft).strip().rstrip(".!,; ").strip()
    if not text:
        return ""
    if not re.search(r"[\u0600-\u06FF]", text):  # Latin only
        text = re.sub(r"\bi\b", "I", text)
        text = text[0].upper() + text[1:]
    return text + "."
