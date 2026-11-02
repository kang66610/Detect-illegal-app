"""Data-driven Frida hook registry for sensitive Android surfaces."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from agent.common.settings import PROJECT_ROOT

_REGISTRY_PATH = PROJECT_ROOT / "agent" / "config" / "sensitive_apis.yaml"


def load_sensitive_api_registry(path: Path | None = None) -> list[dict]:
    source = path or _REGISTRY_PATH
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    entries = data.get("sensitive_apis") or []
    required = {"id", "class_name", "method_name", "data_type"}
    seen: set[str] = set()
    normalized: list[dict] = []
    for raw in entries:
        missing = required - set(raw or {})
        if missing:
            raise ValueError(f"敏感 API 注册项缺少字段：{sorted(missing)}")
        registry_id = str(raw["id"])
        if registry_id in seen:
            raise ValueError(f"敏感 API 注册项重复：{registry_id}")
        seen.add(registry_id)
        normalized.append(dict(raw))
    return normalized


def resolve_data_type(registry_id: str, entries: list[dict] | None = None) -> str | None:
    for item in entries or load_sensitive_api_registry():
        if item["id"] == registry_id:
            return str(item["data_type"])
    return None


def build_hook_script(entries: list[dict]) -> str:
    """Build one safe Frida script without exporting argument/return values.

    The registry is serialized as metadata only. Filters inspect arguments in
    the target process, while the emitted record contains only the registry
    identifier, API name, data category, time and Java stack.
    """
    registry_json = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    return r'''
Java.perform(function () {
  var Log = Java.use('android.util.Log');
  var Throwable = Java.use('java.lang.Throwable');
  var registry = __REGISTRY__;
  function matchesFilter(entry, args) {
    var f = entry.argument_filter;
    if (!f) return true;
    try {
      var value = String(args[Number(f.index)]).toLowerCase();
      if (f.contains_any) {
        return f.contains_any.some(function (term) {
          return value.indexOf(String(term).toLowerCase()) >= 0;
        });
      }
      return value.indexOf(String(f.contains).toLowerCase()) >= 0;
    } catch (e) { return false; }
  }
  function emit(entry, apiName) {
    var stack = '';
    try { stack = Log.getStackTraceString(Throwable.$new()).toString(); } catch (e) {}
    send({type: 'api', registry_id: entry.id, api: apiName,
          data_type: entry.data_type, time: Date.now(), stack: stack});
  }
  function currentStack() {
    try { return Log.getStackTraceString(Throwable.$new()).toString(); } catch (e) { return ''; }
  }
  function credentialFields(value) {
    var text = '';
    try { text = String(value || '').toLowerCase(); } catch (e) { return []; }
    var names = [
      'password', 'passwd', 'pwd', 'passcode', 'username', 'user_name', 'account',
      'phone', 'mobile', 'verification_code', 'verifycode', 'sms_code', 'smscode',
      'captcha', 'access_token', 'refresh_token', 'token'
    ];
    return names.filter(function (name) {
      var escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return new RegExp('(?:[?&"\\\']|^)' + escaped + '(?:["\\\']?\\s*[:=]|=)', 'i').test(text);
    }).slice(0, 12);
  }
  function emitUrl(value, details) {
    var safe = '';
    var raw = '';
    try { raw = String(value); safe = raw.split('?')[0].split('#')[0]; } catch (e) {}
    if (!safe) return;
    var payload = {type: 'url', url: safe, time: Date.now(), stack: currentStack(),
                   transport: safe.toLowerCase().indexOf('https://') === 0 ? 'https' :
                              (safe.toLowerCase().indexOf('http://') === 0 ? 'http' : '')};
    payload.credential_fields = credentialFields(raw);
    if (details) {
      Object.keys(details).forEach(function (key) { payload[key] = details[key]; });
    }
    send(payload);
  }
  function emitOkHttpRequest(call) {
    try {
      var request = call.request();
      var url = request.url().toString();
      var fields = credentialFields(url);
      var authorization = false;
      try { authorization = String(request.header('Authorization') || '').length > 0; } catch (e) {}
      var bodyClass = '';
      try {
        var body = request.body();
        if (body) {
          bodyClass = String(body.$className || body.getClass().getName() || '');
          if (bodyClass.toLowerCase().indexOf('formbody') >= 0) {
            for (var i = 0; i < body.size(); i++) {
              fields = fields.concat(credentialFields(String(body.encodedName(i)) + '='));
            }
          } else {
            var length = Number(body.contentLength());
            var oneShot = false;
            try { oneShot = body.isOneShot(); } catch (e) {}
            if (!oneShot && length >= 0 && length <= 65536) {
              var Buffer = Java.use('okio.Buffer');
              var buffer = Buffer.$new();
              body.writeTo(buffer);
              fields = fields.concat(credentialFields(buffer.readUtf8()));
            }
          }
        }
      } catch (e) {}
      fields = fields.filter(function (value, index, all) { return all.indexOf(value) === index; }).slice(0, 12);
      emitUrl(url, {
        method: String(request.method() || ''), credential_fields: fields,
        authorization_present: authorization, body_class: bodyClass
      });
    } catch (e) {}
  }
  registry.forEach(function (entry) {
    try {
      var C = Java.use(entry.class_name); var method = C[entry.method_name];
      if (!method) return;
      method.overloads.forEach(function (overload) {
        overload.implementation = function () {
          if (matchesFilter(entry, arguments)) emit(entry, entry.class_name + '.' + entry.method_name);
          return overload.apply(this, arguments);
        };
      });
    } catch (e) {}
  });
  try {
    var URL = Java.use('java.net.URL'); var openConnection = URL.openConnection.overload();
    openConnection.implementation = function () {
      emitUrl(this.toString());
      return openConnection.call(this);
    };
  } catch (e) {}
  try {
    var WebView = Java.use('android.webkit.WebView');
    WebView.loadUrl.overloads.forEach(function (overload) {
        overload.implementation = function () { emitUrl(arguments[0]); return overload.apply(this, arguments); };
    });
  } catch (e) {}
  try {
    var RealCall = Java.use('okhttp3.RealCall');
    ['execute', 'enqueue'].forEach(function (methodName) {
      if (!RealCall[methodName]) return;
      RealCall[methodName].overloads.forEach(function (overload) {
        overload.implementation = function () {
          try { emitOkHttpRequest(this); } catch (e) {}
          return overload.apply(this, arguments);
        };
      });
    });
  } catch (e) {}
  try {
    var System = Java.use('java.lang.System');
    System.loadLibrary.implementation = function (name) {
      send({type: 'native_load', library: String(name || ''), time: Date.now(), stack: currentStack()});
      return System.loadLibrary.call(this, name);
    };
  } catch (e) {}
  try {
    var Runtime = Java.use('java.lang.Runtime');
    Runtime.loadLibrary0.overloads.forEach(function (overload) {
      overload.implementation = function () {
        try {
          var lib = arguments.length ? String(arguments[arguments.length - 1] || '') : '';
          send({type: 'native_load', library: lib, time: Date.now(), stack: currentStack()});
        } catch (err) {}
        return overload.apply(this, arguments);
      };
    });
  } catch (e) {}
});
'''.replace("__REGISTRY__", registry_json)
