"""
logsetup.py - structured (JSON) logging that never writes private data.

* One JSON object per line, with a request id so a problem on a page can be traced.
* Message text is scrubbed for passwords, tokens, long secrets and email addresses.
* Exceptions are logged as their type and where they happened, not their message, because database errors can quote
  the very values (names, emails) that failed.
* Request bodies, form fields and headers are never logged.
"""
import json
import logging
import re
import sys
import traceback
import uuid

from flask import g, has_request_context, request

_SCRUB = [
    (re.compile(r"(?i)\b(password|passwd|secret|token|authorization|api[_-]?key|csrf_token)\b\s*[=:]\s*\S+"), r"\1=[hidden]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "[secret]"),
    (re.compile(r"(?i)postgres(ql)?://\S+"), "[database-url]"),
]
EXTRA_FIELDS = ("event", "sqlstate", "error", "statement", "payment_id", "amount", "purpose", "email_id", "id", "status", "path")


def scrub(text):
    text = str(text)
    for pattern, repl in _SCRUB:
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname, "logger": record.name,
               "message": scrub(record.getMessage())}
        if has_request_context():
            out["request_id"] = getattr(g, "request_id", None)
            out["method"], out["path"] = request.method, request.path
        for field in EXTRA_FIELDS:
            if hasattr(record, field):
                out[field] = scrub(getattr(record, field))
        if record.exc_info:
            etype, _, tb = record.exc_info
            frames = traceback.extract_tb(tb)[-4:]
            out["exception"] = etype.__name__
            out["where"] = [f"{f.filename.split('/')[-1]}:{f.lineno} in {f.name}" for f in frames]
        return json.dumps(out)


def configure(app):
    root = logging.getLogger()
    if not any(getattr(h, "_miutm", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._miutm = True
        root.handlers = [handler]
    root.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.before_request
    def assign_request_id():
        g.request_id = uuid.uuid4().hex[:10]

    @app.after_request
    def stamp(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        if response.status_code >= 500:
            logging.getLogger("miutm.http").error("server error response", extra={"event": "http_5xx", "status": response.status_code})
        return response
