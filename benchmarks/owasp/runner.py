#!/usr/bin/env python3
"""Automated benchmark runner for OWASP Benchmark for Python.
Runs baseline or improved (structured data-flow analysis) against selected test cases on Lenovo Ollama.
"""
import json, os, subprocess, time, sys

BASE = "/mnt/hermes/spikes/004-owasp-benchmark"
LENOVO = "lenovo"
OLLAMA_URL = "http://localhost:11434/api/chat"

def load_cases():
    with open(f"{BASE}/selected-cases.json") as f:
        return json.load(f)

def run_ollama(payload, timeout=180):
    """Send payload to Lenovo Ollama, return content string."""
    tmp = f"/tmp/bench-{os.getpid()}.json"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    
    subprocess.run(["scp", tmp, f"{LENOVO}:{tmp}"], capture_output=True)
    result = subprocess.run(
        ["ssh", LENOVO, f"timeout {timeout} curl -s {OLLAMA_URL} -d @{tmp}"],
        capture_output=True, text=True, timeout=timeout+10
    )
    os.remove(tmp)
    
    if result.returncode != 0:
        return None, f"SSH error: {result.stderr[:200]}"
    
    try:
        data = json.loads(result.stdout)
        return data["message"]["content"], None
    except Exception as e:
        return None, f"Parse error: {e}"

# ─── Vulnerability category descriptions for improved prompting ───

CATEGORY_CONTEXT = {
    "pathtraver": {
        "name": "Path Traversal",
        "cwe": "CWE-22",
        "dangerous_sinks": "pathlib.Path() with user input, open() with user-controlled path, os.path.join() with unsanitized input",
        "safe_patterns": "path validation with os.path.realpath() checks, whitelist-based path resolution, hardcoded paths",
    },
    "sqli": {
        "name": "SQL Injection",
        "cwe": "CWE-89",
        "dangerous_sinks": "f-string or string formatting building SQL queries, cursor.execute() with concatenated SQL strings",
        "safe_patterns": "parameterized queries (?, %s placeholders with tuple arguments), ORM usage, proper escaping",
    },
    "cmdi": {
        "name": "Command Injection",
        "cwe": "CWE-78",
        "dangerous_sinks": "subprocess.run()/call()/Popen() with shell=True and user input, os.system(), os.popen() with user data",
        "safe_patterns": "subprocess with shell=False and argument lists, shlex.quote(), hardcoded command strings",
    },
    "deserialization": {
        "name": "Insecure Deserialization",
        "cwe": "CWE-502",
        "dangerous_sinks": "pickle.loads() on untrusted data, yaml.load() with unsafe Loader, marshal.loads() on user input",
        "safe_patterns": "yaml.safe_load(), json.loads(), pickle with restricted globals, hardcoded safe strings",
    },
    "codeinj": {
        "name": "Code Injection",
        "cwe": "CWE-94",
        "dangerous_sinks": "eval(), exec(), compile() with user-controlled input",
        "safe_patterns": "literal_eval(), sandboxed execution, hardcoded strings, proper input validation before eval",
    },
}

def build_improved_prompt(category):
    """Build a category-specific, data-flow-aware review prompt."""
    ctx = CATEGORY_CONTEXT.get(category, CATEGORY_CONTEXT["cmdi"])
    
    return f"""You are a precise security code reviewer. Your ONLY task is to check this code for **{ctx['name']}** ({ctx['cwe']}).

=== WHAT TO LOOK FOR ===
Dangerous sinks: {ctx['dangerous_sinks']}
Safe patterns: {ctx['safe_patterns']}

=== CRITICAL RULE: DATA-FLOW TRACE REQUIRED ===
Do NOT flag code just because it contains a dangerous function. You MUST trace whether **user-controlled input actually reaches that function at runtime**.

Step through the code line by line:
1. Identify where user input enters (request.form, request.args, request.headers, cookies, etc.)
2. Trace where that value flows through assignments, dictionaries, lists, config objects
3. Check if the value is **overwritten** by a hardcoded string before reaching any dangerous sink
4. Check if conditional branches (if/match) route user input to the sink or to a safe path
5. Only flag if user input survives ALL transformations and reaches the dangerous sink unsanitized

=== WHAT TO IGNORE ===
- Other vulnerability types (XSS, CSRF, weak crypto, etc.) — report ONLY {ctx['name']}
- Dangerous functions that receive hardcoded safe strings
- Dangerous patterns where user input is present in the function but overwritten before the call site
- Dead code paths that never execute

=== RESPONSE FORMAT ===
First, write your data-flow trace. Then output your verdict on the LAST line, exactly:

VULNERABLE: YES (if user input reaches a dangerous sink without sanitization)
VULNERABLE: NO (if user input does NOT reach a dangerous sink, OR if proper sanitization is present)"""

def run_baseline(cases, model="qwen3.6:35b-a3b"):
    """Zero-shot: simple prompt, one pass."""
    results = {}
    prompt = """Review this Python code for security vulnerabilities.
    
At the end of your response, output exactly one line:
VULNERABLE: YES (if you found any security vulnerability)
VULNERABLE: NO (if the code is secure)

List what you find before the verdict line."""
    
    for i, case in enumerate(cases):
        test_name = case['# test name'].strip()
        expected = case[' real vulnerability'].strip() == 'true'
        category = case[' category'].strip()
        cwe = case[' cwe'].strip()
        
        code_path = f"{BASE}/cases/{test_name}.py"
        with open(code_path) as f:
            code = f.read()
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Review this code:\n\n```python\n{code}\n```"}
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 4096}
        }
        
        print(f"[{i+1}/{len(cases)}] {test_name} ({category}, {'VULN' if expected else 'SAFE'})...", end=" ", flush=True)
        content, error = run_ollama(payload)
        
        if error:
            print(f"ERROR: {error}")
            results[test_name] = {"error": error, "expected": expected}
            continue
        
        flagged = "VULNERABLE: YES" in content.upper() or "vulnerable: yes" in content.lower()
        
        print(f"{'FLAGGED' if flagged else 'CLEAN'} (expected={'VULN' if expected else 'SAFE'})")
        results[test_name] = {
            "flagged": flagged,
            "expected": expected,
            "category": category,
            "cwe": cwe,
            "content": content[:500]
        }
        
        time.sleep(2)
    
    return results

def run_improved(cases, model="qwen3.6:35b-a3b"):
    """Improved: category-specific prompt with data-flow trace requirement."""
    results = {}
    
    for i, case in enumerate(cases):
        test_name = case['# test name'].strip()
        expected = case[' real vulnerability'].strip() == 'true'
        category = case[' category'].strip()
        cwe = case[' cwe'].strip()
        
        code_path = f"{BASE}/cases/{test_name}.py"
        with open(code_path) as f:
            code = f.read()
        
        sys_prompt = build_improved_prompt(category)
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"Analyze this code for {CATEGORY_CONTEXT[category]['name']}:\n\n```python\n{code}\n```"}
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 4096}
        }
        
        print(f"[{i+1}/{len(cases)}] {test_name} ({category}, {'VULN' if expected else 'SAFE'})...", end=" ", flush=True)
        content, error = run_ollama(payload)
        
        if error:
            print(f"ERROR: {error}")
            results[test_name] = {"error": error, "expected": expected}
            continue
        
        flagged = "VULNERABLE: YES" in content.upper() or "vulnerable: yes" in content.lower()
        
        print(f"{'FLAGGED' if flagged else 'CLEAN'} (expected={'VULN' if expected else 'SAFE'})")
        results[test_name] = {
            "flagged": flagged,
            "expected": expected,
            "category": category,
            "cwe": cwe,
            "content": content[:500]
        }
        
        time.sleep(2)
    
    return results

def score(results):
    """Calculate precision, recall, F1."""
    tp = sum(1 for r in results.values() if r.get("flagged") and r.get("expected"))
    fp = sum(1 for r in results.values() if r.get("flagged") and not r.get("expected"))
    fn = sum(1 for r in results.values() if not r.get("flagged") and r.get("expected"))
    tn = sum(1 for r in results.values() if not r.get("flagged") and not r.get("expected"))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "total": tp + fp + fn + tn
    }

if __name__ == "__main__":
    args = sys.argv[1:]
    mode = "baseline"
    model = "qwen3.6:35b-a3b"
    
    i = 0
    while i < len(args):
        if args[i] in ("--model", "-m") and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] in ("baseline", "improved"):
            mode = args[i]
            i += 1
        else:
            print(f"Unknown arg: {args[i]}")
            print("Usage: python3 runner.py [baseline|improved] [--model MODEL]")
            sys.exit(1)
    
    model_slug = model.replace(":", "-").replace("/", "-")
    
    cases = load_cases()
    
    print(f"Running {mode} on {len(cases)} test cases...")
    print(f"Model: {model} on {LENOVO}")
    print()
    
    if mode == "improved":
        results = run_improved(cases, model=model)
    else:
        results = run_baseline(cases, model=model)
    
    # Save with model-specific filename
    out_path = f"{BASE}/{mode}-{model_slug}-results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    
    # Score
    scores = score(results)
    print(f"\n{'='*50}")
    print(f"{mode.upper()} RESULTS")
    print(f"{'='*50}")
    print(f"TP={scores['tp']} FP={scores['fp']} FN={scores['fn']} TN={scores['tn']}")
    print(f"Precision: {scores['precision']:.1%}")
    print(f"Recall:    {scores['recall']:.1%}")
    print(f"F1:        {scores['f1']:.3f}")
    print(f"\nSaved to {out_path}")
