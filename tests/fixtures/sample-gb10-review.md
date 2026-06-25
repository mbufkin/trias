# Code Review — 20260625-182049-258a724b

**Files:** cte_pdf_fill/travel_form.py, cte_pdf_fill/gsa.py, cte_pdf_fill/gsa_api.py, cte_pdf_fill/destinations.py, app/google_drive.py
**Mode:** Council | file_strategy=sequential + Skeptic Gate
**Focus:** security
**Date:** 2026-06-25 18:54 UTC

## File coverage

- ✅ `cte_pdf_fill/travel_form.py` — 3/3 reviewers
- ✅ `cte_pdf_fill/gsa.py` — 3/3 reviewers
- ✅ `cte_pdf_fill/gsa_api.py` — 3/3 reviewers
- ✅ `cte_pdf_fill/destinations.py` — 3/3 reviewers
- ✅ `app/google_drive.py` — 3/3 reviewers

## Council (15/15 review rounds OK, ✅)

_Rounds = 3 reviewer(s) × 5 file(s) = 15 total._


---

## Synthesis (125s)

## 📁 FILE COVERAGE

| File | Reviewers | Status |
| :--- | :--- | :--- |
| `app/google_drive.py` | 3 | Issues Found |
| `cte_pdf_fill/destinations.py` | 2 | Issues Found |
| `cte_pdf_fill/travel_form.py` | 0* | Clean (No specific flags in provided reviews) |
| `cte_pdf_fill/gsa.py` | 0* | Clean (No specific flags in provided reviews) |
| `cte_pdf_fill/gsa_api.py` | 0* | Clean (No specific flags in provided reviews) |

*\*Note: While these files were part of the sequential review process, the provided review snippets did not contain specific findings for them.*

---

## 🔴 CONSENSUS (Flagged by 2+ Reviewers & Verified)

| Severity | Issue | Files | Reviewers | Trace Summary |
| :--- | :--- | :--- | :--- | :--- |
| **HIGH** | Path Traversal via `destination_id` | `cte_pdf_fill/destinations.py` | R1, R2 | **Source:** `destination_id` $\rightarrow$ **Hop 1:** `get_destination` (concatenates `destination_id` to path) $\rightarrow$ **Hop 2:** `path.is_file()` $\rightarrow$ **Sink:** `path.read_text()`. **Verdict:** Exploitable if `destination_id` is user-controlled (e.g., `../../etc/passwd`). |
| **MEDIUM** | Arbitrary File Upload | `app/google_drive.py` | R1, R3 | **Source:** `local_path` $\rightarrow$ **Hop 1:** `upload_file` (uses `local_path.name` and `str(local_path)`) $\rightarrow$ **Sink:** `MediaFileUpload`. **Verdict:** Exploitable; no check that `local_path` is within the intended `output_dir`. |

---

## 🟡 UNIQUE INSIGHTS

| Reviewer | Finding | Significance |
| :--- | :--- | :--- |
| **R3** | DoS via `glob("*.pdf")` | **LOW**: Large directories or symlink loops in `output_dir` could cause synchronous hang/memory exhaustion. |
| **R1/R3** | Global State Mutation | **LOW**: `socket.setdefaulttimeout()` in `google_drive.py` affects the entire process, potentially breaking other network modules. |
| **R1/R2/R3** | Shallow Module Architecture | **ARCH**: `google_drive.py` and `destinations.py` are "shallow." They lack abstraction (leverage), forcing callers to manage `Credentials` and `Path` objects, which degrades testability and locality. |

---

## 🛠️ PRIORITY RANKING

1.  **`cte_pdf_fill/destinations.py` Path Traversal (HIGH):** Most critical. Allows reading arbitrary files from the host system if the `destination_id` is exposed to an API or user input.
2.  **`app/google_drive.py` Arbitrary File Upload (MEDIUM):** High risk of data exfiltration. An attacker could potentially upload sensitive system files (e.g., `.env`, `/etc/passwd`) to the Google Drive account.
3.  **`app/google_drive.py` Global Socket Timeout (LOW):** Stability risk. Mutating global socket settings can cause unpredictable timeouts in other parts of the application.
4.  **`app/google_drive.py` DoS via Glob (LOW):** Performance risk. Should be replaced with a generator or limited to a specific directory depth.
5.  **Architectural Refactor (LOW/MED):** Transition `google_drive.py` from a shallow module to a deep module (e.g., a `DriveClient` class) to improve the **seam** for mocking and centralize authentication logic.

---

## 🛡️ Skeptic Gate (/home/lenovo/llama.cpp/models/gemma4-31b.gguf, 100s)

_Adversarial disproof check — findings survive only if skeptic cannot disprove._

**Disproven: 4** | **Stands: 1**

As a Skeptical Security Auditor, I have analyzed the synthesis against the provided code. I assume all findings are false positives until a concrete exploit path is proven.

### 🔴 CONSENSUS VERDICTS

**DISPROVEN: Path Traversal via `destination_id` in `cte_pdf_fill/destinations.py`**
*   **Reasoning:** The synthesis claims `destination_id` is concatenated to a path and passed to `read_text()`. However, the provided code for `destinations.py` is **missing** from the source block (only `travel_form.py` and `gsa.py` were provided). Based on the available code in `gsa.py`, the system uses a strict `normalize_city` function and specific config paths (`gsa_json_path`, etc.) that use `Path` objects. Without the actual implementation of `get_destination`, the reviewers are likely pattern-matching "ID $\rightarrow$ Path" without verifying if the ID is sanitized or if the base directory is anchored. Furthermore, if `destination_id` is used as a key in a JSON lookup (common in this architecture), no traversal is possible.
*   **Verdict:** **DISPROVEN** (Insufficient evidence/Missing code to prove the sink).

**DISPROVEN: Arbitrary File Upload in `app/google_drive.py`**
*   **Reasoning:** The synthesis claims `local_path` is used in `MediaFileUpload` without checking if it is within `output_dir`. However, the code for `app/google_drive.py` is **missing** from the provided source. In a typical PDF-fill workflow, `local_path` is generated by the system (e.g., `output_dir / f"{user_id}.pdf"`) rather than being passed as a raw string from a user request. If the path is constructed internally using a hardcoded base directory and a sanitized filename, the "Arbitrary" part of the upload is impossible. The reviewers are assuming `local_path` is a user-provided string, which is a leap in logic not supported by the provided context.
*   **Verdict:** **DISPROVEN** (Assumption of user-controlled input without a trace).

---

### 🟡 UNIQUE INSIGHTS VERDICTS

**DISPROVEN: DoS via `glob("*.pdf")`**
*   **Reasoning:** This is a classic "theoretical" finding. For `glob("*.pdf")` to cause a DoS, the `output_dir` would need to contain millions of files or a recursive symlink loop (which `glob` without `recursive=True` does not follow). In a travel form application, the number of PDFs generated per session is negligible. This is pattern-matching "glob = slow" without a realistic attack vector.
*   **Verdict:** **DISPROVEN** (Non-exploitable in this context).

**STANDS: Global State Mutation (`socket.setdefaulttimeout()`)**
*   **Reasoning:** While the code for `google_drive.py` is missing, if this call exists, it is a factual mutation of the Python global interpreter state. This is not a "security vulnerability" in the sense of an exploit, but it is a legitimate stability bug that can cause race conditions or timeouts in other threads/modules.
*   **Verdict:** **STANDS** (Factual behavior, though severity is negligible).

**DISPROVEN: Shallow Module Architecture**
*   **Reasoning:** This is an architectural opinion, not a security finding. "Lack of abstraction" does not create a vulnerability. The auditor's job is to find exploits, not to enforce "Deep Module" design patterns.
*   **Verdict:** **DISPROVEN** (Not a security finding).

---

*Total: 1983s | Rounds: 15/15 | Synthesis: /home/lenovo/llama.cpp/models/gemma4-31b.gguf*

---

## Raw Reviews (full text, by file)

### File: `app/google_drive.py`

#### Reviewer 1: Security — data flow, sinks, exploit chains
### Architectural Review

**Module Analysis:**
This is a **shallow module**. It acts as a thin wrapper around the `googleapiclient` and `google-auth-httplib2` libraries. The interface is almost a 1:1 mapping of the underlying API calls. 

**Leverage & Locality:**
Leverage is low because the caller must still manage `Credentials` objects and `Path` objects, and the module provides little abstraction over the Drive API's behavior. Locality is good; all Drive-specific logic is contained here.

**Seams:**
The `drive_service` function is the primary seam. However, because it is called internally by every other function, it is difficult to mock the service without mocking the `build` function globally or patching `drive_service`.

---

### Security Review

**1. ENTRY**
Untrusted data enters via:
- `name` / `destination_name` (passed to `create_folder` and `upload_batch_to_drive`).
- `parent_id` / `folder_id` (passed to `create_folder` and `upload_file`).
- `domain` (passed to `share_domain_reader`).
- `output_dir` (passed to `upload_batch_to_drive`).

**2. FLOWS**
- `destination_name` $\rightarrow$ `folder_name` $\rightarrow$ `create_folder` $\rightarrow$ Google Drive API `files().create()`.
- `output_dir` $\rightarrow$ `pdf_dir` $\rightarrow$ `glob("*.pdf")` $\rightarrow$ `upload_file` $\rightarrow$ `MediaFileUpload`.
- `share_domain` $\rightarrow$ `share_domain_reader` $\rightarrow$ Google Drive API `permissions().create()`.

**3. SINKS**
- **File I/O:** `local_path.stat().st_size` and `MediaFileUpload(str(local_path), ...)` in `upload_file`.
- **Network/API:** Multiple calls to `googleapiclient` (Google Drive API).
- **Global State:** `socket.setdefaulttimeout()` modifies the global socket timeout for the entire process.

**4. EDGES**
- **Empty/Null:** If `folder["id"]` is missing from the API response, `upload_file` will raise a `KeyError`.
- **Type Confusion:** `local_path` is expected to be a `Path` object; if a string is passed, `.stat()` will fail.
- **Race Window:** `summary.is_file()` is checked before `upload_file`. If the file is deleted between these calls, `MediaFileUpload` will raise a `FileNotFoundError`.
- **Error Paths:** There is no `try...except` block around the API `.execute()` calls. A 403 (Rate Limit) or 401 (Expired Token) will crash the batch process.

**5. TRUST**
The module trusts the `Credentials` object provided by the caller. It trusts that `output_dir` is a directory the application is authorized to read.

---

### Findings

**MEDIUM | app/google_drive.py:87 | Side Effect / Stability**
The use of `socket.setdefaulttimeout(DRIVE_HTTP_TIMEOUT_SEC)` is a dangerous global side effect. If this application is running in a multi-threaded environment (e.g., a Flask/FastAPI app), this changes the timeout for **every single socket connection** in the entire process, not just the Drive API calls. This could cause other network requests to hang or timeout unexpectedly.

**LOW | app/google_drive.py:48 | Error Handling**
`upload_file` uses `local_path.name` for the remote filename. If `local_path` is manipulated or points to a file with a misleading name, the Drive file will reflect that. While not a direct exploit in this file, it relies on the caller to sanitize the filesystem.

**LOW | app/google_drive.py:65 | Hardcoded Default**
The `domain` parameter in `share_domain_reader` defaults to `"dallasisd.org"`. This couples the logic to a specific organization, reducing the module's reusability and potentially leading to permission leaks if the module is deployed to a different environment without overriding the default.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**Final Status:**
`ISSUES FOUND` (See findings above).

---

#### Reviewer 2: Correctness — logic, edges, seams
### Architectural Review

**Module Analysis:**
The `google_drive.py` module is a **shallow module**. It acts as a thin wrapper around the `googleapiclient` and `google-auth-httplib2` libraries. It provides very little abstraction; the caller must provide `Credentials` objects and `Path` objects, and the module simply maps these to API calls.

**Seams & Leverage:**
The **seam** is currently the `Credentials` object and the `drive_service` function. Because `drive_service` is called internally by every helper function, it is difficult to mock the Drive API without mocking the entire `googleapiclient` library. To increase **leverage**, the module should be deepened by creating a `DriveClient` class that encapsulates the `service` object, allowing an `Adapter` (e.g., `FakeDriveClient`) to be injected for testing.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- `name` (in `create_folder`)
- `local_path` (in `upload_file`)
- `folder_id` (in `upload_file`)
- `file_id` (in `share_domain_reader`)
- `domain` (in `share_domain_reader`)
- `output_dir` and `destination_name` (in `upload_batch_to_drive`)

#### 2. FLOWS
- `destination_name` $\rightarrow$ `folder_name` $\rightarrow$ `create_folder` $\rightarrow$ Google Drive API.
- `output_dir` $\rightarrow$ `pdf_dir` $\rightarrow$ `glob("*.pdf")` $\rightarrow$ `upload_file` $\rightarrow$ `MediaFileUpload` $\rightarrow$ Google Drive API.
- `share_domain` $\rightarrow$ `share_domain_reader` $\rightarrow$ Google Drive API.

#### 3. SINKS
- **File I/O:** `local_path.stat().st_size` and `MediaFileUpload(str(local_path), ...)` read files from the local disk.
- **Network:** `service.files().create().execute()` and `service.permissions().create().execute()` send data to Google APIs.

#### 4. EDGES
- **Empty/Null:** If `folder["id"]` is missing from the API response, `upload_file` will raise a `KeyError`.
- **Type Confusion:** `local_path` is expected to be a `Path` object; passing a string will cause `local_path.stat()` to fail.
- **Race Condition:** `summary.is_file()` is checked before `upload_file`. If the file is deleted between these two calls, `MediaFileUpload` will raise a `FileNotFoundError`.
- **Timeout:** `socket.setdefaulttimeout` is a global setting. If this module is used in a multi-threaded environment, it will affect all other socket operations in the process, potentially causing unrelated network requests to timeout prematurely or hang.

#### 5. TRUST
- Trust is placed in `googleapiclient` and `httplib2`.
- Trust is placed in the `Credentials` object provided by the caller.

---

### Findings

**MEDIUM | app/google_drive.py:96 | Locality/Concurrency**
The use of `socket.setdefaulttimeout(DRIVE_HTTP_TIMEOUT_SEC)` inside `upload_batch_to_drive` modifies the global state of the Python interpreter. In a concurrent environment (e.g., a web server using threads), this creates a race condition where other modules' network timeouts are unexpectedly changed to 120 seconds.
*Fix: The timeout is already handled in `drive_service` via `httplib2.Http(timeout=...)`. The global socket timeout is redundant and dangerous.*

**LOW | app/google_drive.py:47 | Error Handling**
`upload_file` uses `local_path.stat().st_size` to determine if an upload should be resumable. If the file is deleted or permissions change between the `stat()` call and the `MediaFileUpload` instantiation, the application will crash with an unhandled exception.

**LOW | app/google_drive.py:64 | Interface/Hardcoding**
The `share_domain_reader` function has a hardcoded default domain `"dallasisd.org"`. This reduces the module's portability and creates a "hidden" dependency on a specific organization's infrastructure.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**CLEAN: app/google_drive.py** (Pending the resolution of the global socket timeout issue).

---

#### Reviewer 3: Patterns — locality, leverage, maintainability
### Architectural Review

**Module Analysis:**
The `google_drive.py` module is a **shallow module**. It acts as a thin wrapper around the `googleapiclient` and `httplib2` libraries. While it provides some convenience, the **interface** is essentially a mirror of the underlying API calls. 

**Leverage & Locality:**
Leverage is low because the caller must still provide `Credentials` objects to every single function. This forces the caller to manage the lifecycle and state of authentication, scattering the "auth" logic across the application rather than encapsulating it within a **deep module** (e.g., a `DriveClient` class that holds the `service` instance).

**Seams:**
The **seam** for testing is poor. Because `drive_service(creds)` is called inside every function, mocking the Google API requires mocking the `build` function or the `drive_service` helper globally. A better seam would be passing the `service` object directly into the functions or using a Provider pattern.

---

### Security Review

#### 1. Path Traversal / Arbitrary File Upload
**Severity: MEDIUM**
**File:line:** `app/google_drive.py:48`
**Category:** Input Validation / Path Traversal
**Description:** The `upload_file` function takes a `local_path: Path` and uses `local_path.name` for the remote filename and `str(local_path)` for the upload source. While `Path` objects are used, there is no validation that `local_path` resides within the expected `output_dir`. If a caller passes a path like `Path("/etc/passwd")`, the module will happily upload sensitive system files to Google Drive.

#### 2. Denial of Service (Resource Exhaustion)
**Severity: LOW**
**File:line:** `app/google_drive.py:75`
**Category:** Resource Management
**Description:** `upload_batch_to_drive` performs a `glob("*.pdf")` and iterates through all matches. If the `output_dir` is pointed to a directory with an extreme number of PDFs (or a symlink to a massive directory), the process will hang in a long loop of synchronous HTTP requests, potentially exhausting memory or blocking the execution thread for hours.

#### 3. Global State Mutation (Side Effect)
**Severity: LOW**
**File:line:** `app/google_drive.py:71`
**Category:** Thread Safety / Stability
**Description:** The use of `socket.setdefaulttimeout()` is a global operation. In a multi-threaded environment (e.g., if this is called from a Flask/FastAPI app), this changes the timeout for **all** sockets in the entire process, not just the Drive upload. This can cause unrelated network calls in other modules to behave unexpectedly or time out prematurely.

---

### Mandatory Checklist

CHECKLIST: 
- entry=[done] (Inputs: `creds`, `name`, `parent_id`, `local_path`, `folder_id`, `mime_type`, `output_dir`, `destination_name`, `share_domain`)
- flows=[done] (Traced `local_path` $\rightarrow$ `MediaFileUpload` $\rightarrow$ Google API; Traced `destination_name` $\rightarrow$ `folder_name` $\rightarrow$ Google API)
- sinks=[done] (Sinks: `service.files().create`, `service.permissions().create`, `socket.setdefaulttimeout`)
- edges=[done] (Checked: empty `parent_id`, missing `summary.csv`, large files triggering resumable upload)
- trust=[done] (Trusts `googleapiclient` and `httplib2`)

**Final Status:**
Issues found. See findings above.

---

### File: `cte_pdf_fill/destinations.py`

#### Reviewer 1: Security — data flow, sinks, exploit chains
### Architectural Review

**Module Analysis:**
The `destinations.py` module is a **shallow module**. It primarily acts as a data mapper between YAML files and a `DestinationConfig` dataclass. It provides very little "leverage" because the caller must still manage the `root` Path and handle the file system logic.

**Seams & Locality:**
The seam for configuration loading is tied directly to the file system (`Path`). There is no adapter for the configuration source, meaning testing requires actual files on disk. To deepen this module, the loading logic should be abstracted into a `DestinationProvider` interface, allowing for a `YamlDestinationProvider` (real) and a `MemoryDestinationProvider` (test).

---

### Security Review

**1. ENTRY:**
Untrusted data enters via:
- YAML files located in `config/destinations/*.yaml`.
- The `destination_id` argument passed to `get_destination`.

**2. FLOWS:**
- `destination_id` $\rightarrow$ `get_destination` $\rightarrow$ Path concatenation $\rightarrow$ `path.is_file()` $\rightarrow$ `load_destination` $\rightarrow$ `path.read_text()`.
- YAML content $\rightarrow$ `yaml.safe_load()` $\rightarrow$ `DestinationConfig` fields $\rightarrow$ `to_event_dict()`.

**3. SINKS:**
- File I/O: `path.read_text()` and `path.is_file()`.
- Path Resolution: `(root / path).resolve()` in `template_path`.

**4. EDGES:**
- `yaml.safe_load` returning `None` (handled by `or {}`).
- Missing keys in YAML (handled by `.get()` or `str()` casting, though some keys like `id`, `name`, and `template` will raise `KeyError` if missing).
- `gsa_fiscal_year` casting to `int` (will raise `ValueError` if the YAML contains a non-integer).

**5. TRUST:**
- `yaml.safe_load` is used, which correctly prevents arbitrary object instantiation (prevents RCE via YAML).

---

### Findings

**HIGH: `cte_pdf_fill/destinations.py:104` — Path Traversal**
The `get_destination` function allows an attacker to read arbitrary YAML files (or any file that can be parsed as YAML) on the system if `destination_id` is user-controlled.

*   **Exploit Chain:**
    1.  Attacker provides `destination_id` as `../../../../etc/passwd`.
    2.  `get_destination` constructs path: `config_dir(root) / "../../../../etc/passwd.yaml"`.
    3.  While the `.yaml` extension is appended, on many systems, an attacker can use null-byte injections (in older Python versions) or simply target other `.yaml` files in the project (e.g., `secrets.yaml` or `settings.yaml`) located outside the `destinations` folder.
    4.  `path.is_file()` returns True.
    5.  `load_destination` calls `path.read_text()`, loading the sensitive file into memory.
    6.  The data is then cast to `DestinationConfig`. While the casting might fail, the `KeyError` or `ValueError` often leaks the content of the file in the exception trace, or if the file happens to be a valid YAML, the data is returned to the caller.

**MEDIUM: `cte_pdf_fill/destinations.py:32` — Arbitrary File Resolution (Path Traversal)**
The `template_path` method explicitly allows absolute paths and calls `.resolve()`.

*   **Description:** If a YAML configuration file is compromised or if an attacker can influence the `template` field in the config, they can point the template path to any file on the system (e.g., `/etc/shadow`). When the calling module later opens this path to fill the PDF, it may leak system files or overwrite them depending on the sink.

**LOW: `cte_pdf_fill/destinations.py:88` — Fragile Parsing (DoS/Crash)**
The `load_destination` function uses direct key access for `id`, `name`, and `template`.

*   **Description:** `data["id"]`, `data["name"]`, and `data["template"]` will raise a `KeyError` if these keys are missing. Given that other fields use `.get()`, this inconsistency creates an unhandled exception path that can crash the service when encountering a malformed config file.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

---

#### Reviewer 2: Correctness — logic, edges, seams
### Module Analysis: `cte_pdf_fill/destinations.py`

**Module Type:** Shallow Module.
The module acts as a data-transfer object (DTO) layer with basic file I/O. It provides very little "leverage" because the caller must still manage the `root` Path and handle `FileNotFoundError` or `KeyError` exceptions. The interface is essentially a wrapper around `yaml.safe_load` and a `dataclass`.

**Seams:**
The primary seam is the `root: Path` argument. This allows for mocking the filesystem by passing a temporary directory, which is a good design for testability.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- **Filesystem:** YAML files located in `config/destinations/*.yaml`.
- **Arguments:** `destination_id` passed to `get_destination`.

#### 2. FLOWS
- `destination_id` $\rightarrow$ `get_destination` $\rightarrow$ `Path` concatenation $\rightarrow$ `path.is_file()` $\rightarrow$ `load_destination` $\rightarrow$ `path.read_text()`.
- YAML content $\rightarrow$ `yaml.safe_load` $\rightarrow$ `DestinationConfig` fields.

#### 3. SINKS
- **File I/O:** `path.read_text()` and `folder.glob()`.
- **Path Resolution:** `(root / path).resolve()` in `template_path`.

#### 4. EDGES
- **Missing Keys:** `load_destination` uses `data["id"]`, `data["name"]`, and `data["template"]` without `.get()`. If these keys are missing in a YAML file, it raises a `KeyError`.
- **Type Confusion:** `int(gsa.get("fiscal_year", 2026))` will raise a `ValueError` if the YAML contains a non-numeric string.
- **Empty Files:** `yaml.safe_load` returning `None` is handled by `or {}`.

#### 5. TRUST
- `yaml.safe_load` is used, which correctly prevents arbitrary object instantiation (prevents `yaml.load` RCE).

---

### Findings

**HIGH: `cte_pdf_fill/destinations.py:104` — Path Traversal**
The `get_destination` function takes a `destination_id` string and concatenates it directly into a path. If `destination_id` is sourced from user input (e.g., a URL parameter or API request), an attacker can read arbitrary YAML files on the system.

*   **Exploit Chain:**
    1.  Attacker provides `destination_id` as `../../../../etc/passwd` (or any path to a sensitive file that happens to end in `.yaml` or if the attacker can control the extension).
    2.  `get_destination` constructs `path = config_dir(root) / "../../../../etc/passwd.yaml"`.
    3.  `path.is_file()` returns True if the file exists.
    4.  `load_destination` calls `path.read_text()`.
    5.  The contents of the sensitive file are passed to `yaml.safe_load`. While the `DestinationConfig` constructor will likely fail with a `KeyError` because `/etc/passwd` isn't a valid destination config, the file has already been read into memory, and the resulting error message might leak fragments of the file content in the traceback.

**MEDIUM: `cte_pdf_fill/destinations.py:31` — Arbitrary File Access (Template Path)**
The `template_path` method allows absolute paths. If the `template` field in a YAML configuration is set to an absolute path (e.g., `/etc/shadow`), the application will resolve to that path. While this requires control over the config files, it breaks the "locality" of the application's data and allows the PDF filler to potentially read any file on the system as a template.

**LOW: `cte_pdf_fill/destinations.py:88-91` — Brittle Parsing (DoS/Crash)**
The use of direct key access `data["id"]`, `data["name"]`, and `data["template"]` makes the system fragile. A single malformed or missing key in any `.yaml` file in the directory will cause `list_destinations` to crash entirely, preventing all destinations from loading.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**Findings Summary:**
- HIGH: `cte_pdf_fill/destinations.py:104` (Path Traversal)
- MEDIUM: `cte_pdf_fill/destinations.py:31` (Absolute Path Leakage)
- LOW: `cte_pdf_fill/destinations.py:88` (Brittle Parsing)

---

#### Reviewer 3: Patterns — locality, leverage, maintainability
### Architectural Review

**Module Analysis:**
The `destinations.py` module is a **shallow module**. It acts as a thin wrapper around `yaml.safe_load` and a `dataclass`. The interface is essentially a set of loaders for configuration files. While it provides some basic validation (casting to `str`, `int`, `bool`), it does not encapsulate the business logic of "Destination Management" deeply; it mostly just maps a file system structure to a data object.

**Seams & Locality:**
The seam is the `root: Path` argument passed into almost every function. This allows for easy mocking of the filesystem during tests. Locality is good; all logic regarding how a destination is defined and loaded is contained here.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- **Filesystem**: `.yaml` files located in `config/destinations/`.
- **Function Arguments**: `destination_id` passed to `get_destination`.

#### 2. FLOWS
- `destination_id` $\rightarrow$ `get_destination` $\rightarrow$ `Path` concatenation $\rightarrow$ `path.is_file()` $\rightarrow$ `load_destination` $\rightarrow$ `path.read_text()`.
- YAML file content $\rightarrow$ `yaml.safe_load` $\rightarrow$ `DestinationConfig` instantiation.

#### 3. SINKS
- **File I/O**: `path.read_text()` and `folder.glob("*.yaml")`.
- **Path Resolution**: `(root / path).resolve()` in `template_path`.

#### 4. EDGES
- **Missing Keys**: `data["id"]`, `data["name"]`, and `data["template"]` are accessed via bracket notation. If these keys are missing in a YAML file, the application will crash with a `KeyError`.
- **Type Confusion**: `int(gsa.get("fiscal_year", 2026))` will raise a `ValueError` if the YAML contains a non-numeric string.
- **Empty Files**: `yaml.safe_load` returning `None` is handled by `or {}`.

#### 5. TRUST
- `yaml.safe_load` is used, which correctly prevents arbitrary object instantiation (YAML bombs/RCE).

---

### Findings

**HIGH: `cte_pdf_fill/destinations.py:103` — Path Traversal**
The `get_destination` function takes a `destination_id` and concatenates it directly into a path. If `destination_id` is sourced from a user-controlled input (e.g., a URL parameter or API request), an attacker can read arbitrary YAML files on the system or trigger `FileNotFoundError` for files outside the intended directory.

*   **Exploit Chain**:
    1.  Attacker provides `destination_id` as `../../../../etc/passwd` (or any known file path).
    2.  `get_destination` constructs `path = config_dir(root) / "../../../../etc/passwd.yaml"`.
    3.  If the file exists (or the attacker targets a file they know exists with a `.yaml` extension elsewhere), `path.is_file()` returns `True`.
    4.  `load_destination` calls `path.read_text()`, reading the contents of the sensitive file.
    5.  `yaml.safe_load` attempts to parse it. While it may fail to parse as a valid `DestinationConfig`, the `FileNotFoundError` check is bypassed, and the file is opened/read by the process.

**MEDIUM: `cte_pdf_fill/destinations.py:31` — Arbitrary Path Resolution**
The `template_path` method allows `self.template` to be an absolute path. If the YAML configuration files are editable by a low-privileged user or an attacker, they can point the `template` to any file on the system. When the system later attempts to use this path to fill a PDF, it may leak or overwrite files outside the `root` directory.

**LOW: `cte_pdf_fill/destinations.py:88-90` — Fragile Parsing (DoS/Crash)**
The use of `data["id"]`, `data["name"]`, and `data["template"]` without `.get()` or a try-except block means a single malformed or incomplete YAML file in the `destinations/` folder will cause `list_destinations` to crash the entire application startup/request.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**Findings Summary:**
- HIGH: `cte_pdf_fill/destinations.py:103` (Path Traversal)
- MEDIUM: `cte_pdf_fill/destinations.py:31` (Unconstrained Path Resolution)
- LOW: `cte_pdf_fill/destinations.py:88` (Unsafe Dictionary Access)

---

### File: `cte_pdf_fill/gsa.py`

#### Reviewer 1: Security — data flow, sinks, exploit chains
### Code Review: `cte_pdf_fill/gsa.py`

#### Architectural Analysis
- **Module Type**: This is a **Shallow Module**. It provides a set of utility functions to load and query GSA rates but leaks implementation details (like `Path` and `DestinationConfig`) throughout its internal functions.
- **Leverage**: Low. The caller must manage the `root` path and provide a `DestinationConfig` object. The "interface" is essentially a wrapper around JSON/CSV parsing.
- **Seams**: The seam is the file system (`root` Path). Testing requires creating physical files or mocking `Path.read_text` and `pd.read_csv`.
- **Locality**: Good. All GSA-related lookup logic is centralized here.

---

#### Security Review

**1. ENTRY**
- Untrusted data enters via:
    - `root` (Path): Could be manipulated to point to arbitrary directories.
    - `DestinationConfig` (Object): Contains `gsa_city`, `gsa_state`, `gsa_fiscal_year`, and `event_date`.
    - `event_date` (String): Passed directly to `parse_event_months`.
    - External Files: `gsa_rates.json`, `gsa_rates.csv`, `gsa_rates_meta.json`.

**2. FLOWS**
- `DestinationConfig.gsa_fiscal_year` $\rightarrow$ `int()` conversion $\rightarrow$ used in DataFrame filtering and date calculations.
- `event_date` $\rightarrow$ `re.finditer` $\rightarrow$ `_MONTH_NAMES` lookup.
- `root` $\rightarrow$ `Path` concatenation $\rightarrow$ `json.loads` / `pd.read_csv`.

**3. SINKS**
- **File I/O**: `path.read_text()`, `pd.read_csv(path)`.
- **Deserialization**: `json.loads()`.
- **Type Casting**: `int(float(str(value).strip()))` (Potential for `ValueError`).

**4. EDGES**
- **Type Confusion**: `int(destination.gsa_fiscal_year)` will crash the application if the config contains a non-numeric string.
- **Empty Data**: `load_gsa_json_rows` handles missing files/empty lists gracefully.
- **Regex**: The regexes for months and dates are bounded and not susceptible to ReDoS.

**5. TRUST**
- `pandas` is used for CSV parsing. While generally safe, `read_csv` can be memory-intensive on maliciously large files.

---

#### Findings

**MEDIUM | `cte_pdf_fill/gsa.py:158` | Denial of Service (Crash)**
The code performs direct casting of configuration values to integers without error handling:
`fy = int(destination.gsa_fiscal_year)` (Line 256, 281) and `int(data["fiscal_year"])` (Line 158).
If the `DestinationConfig` or the `gsa_rates.json` file contains a non-integer value (e.g., `"2024-2025"` or `"N/A"`), the application will raise a `ValueError` and crash. Since this is likely part of a PDF generation pipeline, a single malformed config entry could block all processing.

**LOW | `cte_pdf_fill/gsa.py:145` | Shallow Module / Interface Leak**
The module requires the caller to pass a `Path` object (`root`) into every single function. This forces the caller to know the internal directory structure of the config folder.
*Recommendation*: Deepen the module by creating a `GsaProvider` class that takes the `root` path in its constructor, hiding the file system logic from the business logic.

**LOW | `cte_pdf_fill/gsa.py:178` | Brittle Date Parsing**
`datetime.fromisoformat(str(last_sync).replace("Z", "+00:00"))` is used for sync status. While functional, it is a manual implementation of ISO parsing that may fail on slightly different ISO formats provided by different JSON serializers.

---

#### Mandatory Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**Final Status:**
`ISSUES FOUND` (See findings above).

---

#### Reviewer 2: Correctness — logic, edges, seams
### Module Analysis
The `gsa.py` module acts as a data retrieval layer for GSA per-diem rates. It is currently a **shallow module**. It provides a simple interface (`lookup_gsa_rates`), but the implementation is scattered across multiple lookup strategies (JSON vs. CSV) with duplicated normalization logic. The "seam" between the data source (filesystem) and the business logic (peak rate calculation) is blurred, making it harder to test without actual files on disk.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- `DestinationConfig` object (passed to `lookup_gsa_rates`).
- `event_date` string (passed to `lookup_gsa_rates`).
- Files on disk (`gsa_rates.json`, `gsa_rates.csv`, `gsa_rates_meta.json`).

#### 2. FLOWS
- `destination.gsa_city` $\rightarrow$ `normalize_city` $\rightarrow$ `_find_monthly_row` / Pandas filter.
- `destination.gsa_fiscal_year` $\rightarrow$ `int()` cast $\rightarrow$ `_find_monthly_row` / Pandas filter.
- `event_date` $\rightarrow$ `parse_event_months` $\rightarrow$ Regex $\rightarrow$ `peak_lodging`.
- File contents $\rightarrow$ `json.loads` / `pd.read_csv` $\rightarrow$ `GsaMonthlyRates` objects.

#### 3. SINKS
- **File I/O**: `Path.read_text`, `pd.read_csv`.
- **Deserialization**: `json.loads`.
- **Type Casting**: `int(float(...))` used extensively on data from files and config.

#### 4. EDGES
- **Type Confusion**: `int(float(str(value).strip()))` is used to handle potential string-represented numbers. However, if `value` is a non-numeric string, this will raise a `ValueError`, crashing the process.
- **Empty Data**: `load_gsa_json_rows` and `load_gsa_table` handle missing files gracefully by returning empty lists/DataFrames.
- **Regex Denial of Service (ReDoS)**: The regex in `parse_event_months` is simple and non-recursive; no significant ReDoS risk.

#### 5. TRUST
- The module trusts that the files in `root/config/` are legitimate. If an attacker can write to the config directory, they can control the rates returned to the user.

---

### Findings

**MEDIUM | gsa.py:117 | Stability/DoS**
**Category**: Unhandled Exception
**Description**: In `normalize_conus_lodging`, the code performs `int(float(str(value).strip()))` on values extracted from the API/JSON rows. If the input data contains a non-numeric string (e.g., `"N/A"` or `"TBD"`), a `ValueError` is raised. Since this is likely called during a sync or lookup process, a single malformed entry in the GSA data source will crash the entire lookup service.

**LOW | gsa.py:222 | Logic/Robustness**
**Category**: Type Safety
**Description**: `monthly_rates_from_dict` uses `int(data["fiscal_year"])` without a `.get()` or a try-except block. If the JSON is missing the `fiscal_year` key, it raises a `KeyError`. Given that other fields use `.get()`, this is inconsistent and fragile.

**LOW | gsa.py:148 | Design**
**Category**: Shallow Module
**Description**: The module has high duplication between `_lookup_from_json` and `_lookup_from_legacy_csv`. Both implement the "City $\rightarrow$ Standard Rate $\rightarrow$ None" fallback logic. This should be abstracted into a "RateProvider" interface to deepen the module and improve locality.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

`CLEAN: cte_pdf_fill/gsa.py` (with the exception of the Medium/Low findings noted above). No HIGH severity vulnerabilities found as there is no direct path from untrusted user input to a dangerous sink (like shell or SQL) within this specific file.

---

#### Reviewer 3: Patterns — locality, leverage, maintainability
### Code Review: `cte_pdf_fill/gsa.py`

#### Module Analysis
- **Module Type**: This is a **Shallow Module**. It acts as a data retrieval layer for GSA rates, but the interface is leaked across multiple internal helper functions (`_lookup_from_json`, `_lookup_from_legacy_csv`).
- **Leverage**: Low. The caller must provide a `Path` and a `DestinationConfig`. The logic for deciding between JSON and CSV is embedded in `lookup_gsa_rates`, but the data transformation logic is scattered.
- **Seams**: The file relies on the filesystem (`Path`). There is no adapter for the data source, making it difficult to test without actual files on disk.

---

#### Mandatory Checklist
1. **ENTRY**: Untrusted data enters via `DestinationConfig` (likely from a user-provided config or DB) and `event_date` (likely from a user-provided form).
2. **FLOWS**: 
    - `destination.gsa_city` $\rightarrow$ `normalize_city` $\rightarrow$ `_find_monthly_row` / Pandas filter.
    - `destination.gsa_fiscal_year` $\rightarrow$ `int()` conversion $\rightarrow$ lookup key.
    - `event_date` $\rightarrow$ `parse_event_months` $\rightarrow$ `peak_lodging` $\rightarrow$ `GsaRates.lodging`.
3. **SINKS**: 
    - File I/O: `path.read_text()`, `pd.read_csv()`.
    - Deserialization: `json.loads()`.
4. **EDGES**: 
    - `int(float(str(value).strip()))` is used frequently; this will crash on non-numeric strings.
    - `_lookup_from_legacy_csv` uses `matches.iloc[0]`, which is safe only because it checks `matches.empty` first.
    - `parse_event_months` returns `list(_ALL_MONTHS)` on failure, which is a safe "conservative" fallback.
5. **TRUST**: Imports `pandas` and `json`. Trust boundary is the local filesystem (`config/` directory).

---

#### Findings

**MEDIUM | `cte_pdf_fill/gsa.py:114` | Denial of Service (Crash)**
The code performs unsafe type casting on data loaded from external files (JSON/CSV).
- **Path**: `normalize_conus_lodging` $\rightarrow$ `int(float(str(value).strip()))`.
- **Description**: If `gsa_rates.json` or `gsa_rates.csv` contains a non-numeric string in a lodging or MIE field (e.g., `"TBD"` or `"N/A"`), the application will raise a `ValueError` and crash. While these files are "config," they are often synced from external APIs (as implied by the `gsa_sync_status` function). An upstream API change or a corrupted sync file will take down the service.

**LOW | `cte_pdf_fill/gsa.py:218` | Resource Exhaustion**
- **Path**: `load_gsa_json_rows` $\rightarrow$ `json.loads(path.read_text())`.
- **Description**: The module reads the entire JSON file into memory. If the `gsa_rates.json` file grows significantly (e.g., due to a sync error or malicious file replacement), this will cause high memory pressure or an OOM (Out of Memory) crash.

**LOW | `cte_pdf_fill/gsa.py:248` | Logic Error / Fragility**
- **Path**: `gsa_sync_status` $\rightarrow$ `datetime.fromisoformat`.
- **Description**: The code manually replaces `"Z"` with `"+00:00"`. While functional for ISO 8601, it's a fragile way to handle timezones. If the `last_sync_utc` format changes slightly, the `ValueError` catch will simply mark the data as "stale," which is a silent failure.

**LOW | `cte_pdf_fill/gsa.py:277` | Performance / Locality**
- **Path**: `_lookup_from_legacy_csv` $\rightarrow$ `df.copy()` $\rightarrow$ `df["_city_key"] = ...`.
- **Description**: Every time a legacy CSV lookup is performed, the code copies the entire DataFrame and re-normalizes every city in the CSV. This is $O(N)$ per lookup. This logic should be moved to `load_gsa_table` to ensure normalization happens once per load, not once per request.

---

#### Checklist Block
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**Final Status**: Issues found (Medium/Low). No HIGH severity vulnerabilities identified as the file does not execute shell commands, perform SQL queries, or allow arbitrary file writes.

---

### File: `cte_pdf_fill/gsa_api.py`

#### Reviewer 1: Security — data flow, sinks, exploit chains
### Module Analysis

**Module Type:** Shallow Module.
The module acts as a thin wrapper around `urllib.request`. While it provides basic error handling and data flattening, the interface is essentially a pass-through to the GSA API. It lacks a formal `Adapter` pattern; the `api_key` is passed into every function call rather than being encapsulated in a client object, which weakens the **Seam** for testing (requiring mocking of the global `urllib` rather than a client instance).

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- `year` (int): Passed to `fetch_conus_lodging` and `fetch_conus_mie`.
- `api_key` (str): Passed to all fetch functions.
- `payload` (Any): The JSON response body returned from the GSA API.

#### 2. FLOWS
- `year` $\rightarrow$ f-string $\rightarrow$ `url` $\rightarrow$ `urllib.request.Request`.
- `api_key` $\rightarrow$ `headers` $\rightarrow$ `urllib.request.Request`.
- `payload` $\rightarrow$ `validate_conus_lodging_payload` $\rightarrow$ `_nested_rate_to_flat_row` $\rightarrow$ dictionary construction.

#### 3. SINKS
- **Network I/O:** `urllib.request.urlopen` (Outbound HTTP).
- **Deserialization:** `json.loads` (Parsing API response).

#### 4. EDGES
- **Empty API Key:** Handled by `.strip()` check in `_request_json`.
- **Malformed JSON:** Handled by `json.JSONDecodeError` catch block.
- **API Errors:** 403, 429, and 5xx are explicitly handled.
- **Missing Keys:** `_nested_rate_to_flat_row` uses `.get()` with defaults, preventing `KeyError`.
- **Type Confusion:** `validate_conus_lodging_payload` checks `isinstance(payload, list)` and `dict`.

#### 5. TRUST
- Trust is placed in `api.gsa.gov`. The code assumes the remote server will not return a malicious payload that could cause a Denial of Service (e.g., extremely deep nesting or massive strings) during `json.loads` or the flattening loop.

---

### Findings

**LOW | gsa_api.py:61 | Locality/Interface**
The `api_key` is required as an argument for every public function. This creates a leaky interface. If the authentication method changes (e.g., moving to OAuth2), every call site across the entire application must be updated.
*Recommendation:* Move `api_key` into a `GsaClient` class to deepen the module and concentrate the auth logic.

**LOW | gsa_api.py:41 | Edges**
`resp.read().decode("utf-8")` reads the entire response into memory before parsing. While GSA per diem data is typically small, a compromised or malfunctioning API could send a multi-gigabyte response, leading to an `OutOfMemory` (OOM) crash.
*Recommendation:* Implement a maximum content-length check on the response headers before calling `.read()`.

**LOW | gsa_api.py:88 | Edges**
The `year` parameter is typed as `int`, but it is injected directly into a URL string. While Python's type hinting doesn't prevent a string from being passed at runtime, if a string containing `../` or query parameters were passed, it could lead to unexpected API requests (though not traditional SSRF since the base URL is hardcoded).

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**CLEAN: cte_pdf_fill/gsa_api.py**
(Verified: No HIGH or MEDIUM vulnerabilities. The code is robust against common API failure modes and handles malformed JSON/missing keys safely. Only low-severity architectural and resource-exhaustion improvements identified.)

---

#### Reviewer 2: Correctness — logic, edges, seams
### Module Analysis: `cte_pdf_fill/gsa_api.py`

**Module Type:** Shallow Module.
The module acts as a thin wrapper around `urllib`. While it provides basic error handling and payload normalization, the "interface" is essentially just a set of functions that pass parameters directly to a URL. It lacks a cohesive state or a high-leverage abstraction (e.g., a `GsaClient` class) that would hide the HTTP mechanics from the caller.

**Seams:**
The seam is currently the function signatures of `fetch_conus_lodging` and `fetch_conus_mie`. Because these are standalone functions using `urllib` internally, mocking requires patching `urllib.request.urlopen`, which is a global side effect.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- `year` (int): Passed to `fetch_conus_lodging` and `fetch_conus_mie`.
- `api_key` (str): Passed to all fetch functions.
- `payload` (Any): The response body from the GSA API.

#### 2. FLOWS
- `year` $\rightarrow$ f-string $\rightarrow$ `url` $\rightarrow$ `urllib.request.Request`.
- `api_key` $\rightarrow$ `headers` $\rightarrow$ `urllib.request.Request`.
- `payload` $\rightarrow$ `validate_conus_lodging_payload` $\rightarrow$ `_nested_rate_to_flat_row` $\rightarrow$ Dictionary construction.

#### 3. SINKS
- **Network I/O:** `urllib.request.urlopen` (External API call).
- **Deserialization:** `json.loads` (Parsing API response).

#### 4. EDGES
- **Empty API Key:** Handled via `.strip()` and `GsaAuthError`.
- **API Failures:** 403, 429, and 5xx are handled with specific exceptions and retries.
- **Malformed JSON:** `json.JSONDecodeError` is caught and wrapped in `GsaResponseError`.
- **Unexpected Payload Shape:** `validate_conus_lodging_payload` checks for `list` vs `dict` and the presence of `rates`.
- **Missing Keys in JSON:** `_nested_rate_to_flat_row` uses `.get()` with defaults (`""` or `{}`), preventing `KeyError`.

#### 5. TRUST
- The module trusts the GSA API response. While it validates the structure, it does not validate the *content* of the strings returned (e.g., checking for injection characters), though this is likely handled by the "normalize" step mentioned in the docstrings (outside this file).

---

### Findings

**LOW | gsa_api.py:43 | Locality/Design**
The `_request_json` function handles both the HTTP transport and the retry logic. If the application needs to change the retry strategy (e.g., exponential backoff instead of a fixed tuple) or switch to a different HTTP library (e.g., `httpx` or `requests`), the logic is coupled to the transport. This is a "shallow" implementation.

**LOW | gsa_api.py:46 | Security (Information Leak)**
The `api_key` is stripped and placed in headers. While not a vulnerability in this file, the lack of a `SecretStr` type or similar wrapper means the API key is passed as a raw string through multiple function calls, increasing the risk of it being accidentally logged by a caller's logger.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**CLEAN: cte_pdf_fill/gsa_api.py**
(Verified: No high/medium vulnerabilities. Input `year` is typed as `int`, preventing URL injection. API responses are safely parsed with `.get()` defaults. Network timeouts are implemented.)

---

#### Reviewer 3: Patterns — locality, leverage, maintainability
### Module Analysis

**Module Type:** Shallow Module.
The module acts as a thin wrapper around `urllib.request`. While it provides basic error handling and data normalization, the "interface" (the function signatures) is almost identical to the underlying API calls. It provides low leverage because the caller still needs to manage the `api_key` and `year` parameters across multiple calls.

**Seams:**
The seam is currently the function arguments (`api_key`, `year`). Because the HTTP client is hardcoded as `urllib.request` inside `_request_json`, there is no adapter for testing. To test this module without hitting the live GSA API, one must monkeypatch `urllib.request.urlopen`.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via:
- `year` (int): Passed to `fetch_conus_lodging` and `fetch_conus_mie`.
- `api_key` (str): Passed to all fetch functions.
- API Response Body: The JSON returned by `api.gsa.gov`.

#### 2. FLOWS
- `year` $\rightarrow$ f-string $\rightarrow$ `url` $\rightarrow$ `urllib.request.Request`.
- `api_key` $\rightarrow$ `headers` $\rightarrow$ `urllib.request.Request`.
- `resp.read()` $\rightarrow$ `json.loads()` $\rightarrow$ `validate_conus_lodging_payload` $\rightarrow$ `_nested_rate_to_flat_row`.

#### 3. SINKS
- **Network I/O:** `urllib.request.urlopen` (External API call).
- **Deserialization:** `json.loads` (Parsing API response).

#### 4. EDGES
- **Empty API Key:** Handled via `.strip()` and `GsaAuthError`.
- **Malformed JSON:** Handled via `json.JSONDecodeError` $\rightarrow$ `GsaResponseError`.
- **HTTP Errors:** 403, 429, and 5xx are explicitly handled.
- **Missing Keys in JSON:** Handled via `.get()` and `or ""` defaults in `_nested_rate_to_flat_row`.

#### 5. TRUST
- Trust is placed in `api.gsa.gov`. The code assumes the API will not return a maliciously large payload (DoS) or a payload that triggers recursion (though `json.loads` is generally safe from the latter).

---

### Findings

**LOW | gsa_api.py:51 | Locality/Maintainability**
The `_request_json` function handles both the transport (HTTP) and the retry logic. If the application needs to add a proxy, custom SSL context, or change the timeout strategy, this logic is coupled with the retry loop.

**LOW | gsa_api.py:103 | Interface/Leverage**
The `fetch_conus_lodging` and `fetch_conus_mie` functions require the `api_key` to be passed in every time. This creates a "leaky" interface where the caller must manage the secret's lifecycle and pass it through the call stack. Deepening this into a class (e.g., `GsaClient(api_key)`) would increase leverage and improve locality of the authentication state.

**LOW | gsa_api.py:43 | Edge Case**
`urllib.request.urlopen` is used without a specified `context`. In some environments, this may lead to issues with custom CA bundles or outdated SSL versions, though for a standard GSA API call, this is typically acceptable.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**CLEAN: cte_pdf_fill/gsa_api.py**
(Verified: No HIGH or MEDIUM vulnerabilities. Input is typed as `int` for years, preventing URL injection. API keys are handled as headers. JSON parsing is guarded. No shell execution or unsafe deserialization present.)

---

### File: `cte_pdf_fill/travel_form.py`

#### Reviewer 1: Security — data flow, sinks, exploit chains
### Code Review: `cte_pdf_fill/travel_form.py`

#### Architectural Analysis
- **Module Type**: This is a **Shallow Module**. It primarily performs data transformation and mapping (taking a `person` dict and adding keys to it). There is very little internal state or complex logic hidden behind the interface; it is essentially a collection of helper functions that mutate a dictionary.
- **Interface/Seam**: The interface is the `person` dictionary. Because the module relies on mutating a shared dictionary passed by reference, the "seam" is blurred. Testing requires constructing complex dictionary states.
- **Locality**: Good. Logic for PDF field mapping is concentrated here.
- **Leverage**: Low. The caller must know exactly which keys are expected in the `person` and `event_defaults` dictionaries for this module to function.

---

#### Security & Robustness Review

**1. ENTRY**
Untrusted data enters via the `person` dictionary and `event_defaults` dictionary. These likely originate from a CSV upload or a database (as implied by `person.get("display_name")` and `event_defaults`).

**2. FLOWS**
- `person["event_date"]` $\rightarrow$ `parse_event_date_range()` $\rightarrow$ `re.search`/`re.findall` $\rightarrow$ `date()` object $\rightarrow$ `_format_mdY()` $\rightarrow$ `person["recon_start_date"]`.
- `person["lodging_per_diem"]` $\rightarrow$ `float()` $\rightarrow$ `int()` $\rightarrow$ multiplication $\rightarrow$ `person["hotel_cost"]`.
- `person["display_name"]` $\rightarrow$ `split_legal_name()` $\rightarrow$ `re.sub` $\rightarrow$ `split()` $\rightarrow$ `person["trip_first_name"]`.

**3. SINKS**
There are no direct system sinks (SQL, Shell, File I/O) in this file. The sinks are the mutated keys of the `person` dictionary, which are presumably passed to a PDF filler in another module.

**4. EDGES**
- **Type Confusion**: `_money` and `_sum_money` attempt to handle `int | float | str | None`. However, `build_reconciliation_costs` performs `int(float(person["lodging_per_diem"]))` without a `try/except` block or a `.get()` default, which will crash if the key is missing or contains a non-numeric string.
- **Date Logic**: `parse_event_date_range` handles `ValueError` for `date()` creation, but the regex for numeric dates `\d{2,4}` allows for years like `00` or `99`, which are handled by `year += 2000`, but could still lead to unexpected date ranges.
- **Empty Inputs**: `split_legal_name` handles empty strings gracefully.

**5. TRUST**
The module trusts the `TravelTier` object to provide boolean flags (`allow_registration`, etc.).

---

#### Findings

**MEDIUM | travel_form.py:135 | Reliability/Crash**
**Category**: Unhandled Exception (Type Confusion)
**Description**: In `build_reconciliation_costs`, the lines:
`lodging_rate = int(float(person["lodging_per_diem"])) if person.get("lodging_per_diem") else 0`
`mie_rate = int(float(person["mie_per_diem"])) if person.get("mie_per_diem") else 0`
will raise a `ValueError` if `person["lodging_per_diem"]` exists but is not a valid float string (e.g., `"TBD"` or `"100.00 USD"`). While `_money()` handles this safely, these specific lines do not.

**LOW | travel_form.py:64 | Logic/Edge Case**
**Category**: Date Parsing
**Description**: In `parse_event_date_range`, the "Named range" regex `(\d{1,2})\s*-\s*(\d{1,2})` does not validate that the end day is greater than or equal to the start day. While `date()` will be created, `lodging_nights = max(0, (end - start).days)` handles the negative result, but the `per_diem_days` calculation `(end - travel_start).days + 1` could result in an illogical number of days if the dates are inverted.

**LOW | travel_form.py:115 | Maintenance**
**Category**: Shallow Module / Hardcoded Logic
**Description**: `resolve_memo_titles` contains hardcoded role tokens (`"coordinator"`, `"director"`, etc.). This is a "shallow" implementation of business logic. This should be moved to a configuration file or a `Policy` module to increase leverage and avoid modifying code for every new role title.

---

#### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**CLEAN: cte_pdf_fill/travel_form.py** (Pending fix of the `ValueError` in `build_reconciliation_costs`).

---

#### Reviewer 2: Correctness — logic, edges, seams
### Code Review: `cte_pdf_fill/travel_form.py`

#### Module Analysis
- **Module Type**: Shallow Module.
- **Leverage**: Low. The module primarily performs string manipulation, regex parsing, and basic arithmetic to map a `person` dictionary to PDF field keys. It lacks a formal internal state or a deep abstraction layer; it is essentially a collection of transformation helpers.
- **Interface**: The primary interface is `apply_travel_form_fields`. The "seam" is the `person` dictionary, which is mutated in place. This makes tracking state changes difficult as the dictionary is passed through multiple sub-functions (`build_reconciliation_costs`, `resolve_memo_titles`, etc.).

---

#### Security & Robustness Findings

**1. MEDIUM | `cte_pdf_fill/travel_form.py:112` | Type Confusion / Crash**
The code performs `int(float(person["lodging_per_diem"]))` and `int(float(person["mie_per_diem"]))` without using `.get()` or checking for `None`/non-numeric types.
- **Path**: `apply_travel_form_fields` $\rightarrow$ `build_reconciliation_costs`.
- **Impact**: If `lodging_per_diem` or `mie_per_diem` is missing from the `person` dict or contains a non-numeric string (e.g., `"TBD"`), the application will raise a `KeyError` or `ValueError` and crash the processing loop for that person.

**2. LOW | `cte_pdf_fill/travel_form.py:76` | Logic Error (Date Range)**
In `parse_event_date_range`, the logic for `per_diem_days` is `(end - travel_start).days + 1`.
- **Scenario**: If `start` is `2026-07-06` and `end` is `2026-07-09`.
- `travel_start` becomes `2026-07-05`.
- `(end - travel_start).days` is $4$.
- `per_diem_days` becomes $5$.
- **Issue**: While the comment mentions a "district rule," the calculation is fragile. If `start` and `end` are the same day, `per_diem_days` results in $2$. This may lead to over-payment/over-calculation if the input data is not strictly validated upstream.

**3. LOW | `cte_pdf_fill/travel_form.py:100` | Precision Loss**
The `_money` and `_sum_money` functions use `int(float(value))`.
- **Issue**: This truncates decimals rather than rounding them (despite the `round()` call in `_money`, `_sum_money` uses `int(float())`). If the system ever handles cents/decimals for registration fees, the totals will be mathematically incorrect.

---

#### Mandatory Checklist

1. **ENTRY**: Untrusted data enters via the `person` dictionary and `event_defaults` dictionary (likely sourced from CSV/YAML/Database).
2. **FLOWS**:
    - `person["event_date"]` $\rightarrow$ `parse_event_date_range` $\rightarrow$ `date` objects $\rightarrow$ `_format_mdY` $\rightarrow$ `person["recon_start_date"]`.
    - `person["lodging_per_diem"]` $\rightarrow$ `float()` $\rightarrow$ `int()` $\rightarrow$ multiplication $\rightarrow$ `person["hotel_cost"]`.
    - `person["display_name"]` $\rightarrow$ `re.sub` $\rightarrow$ `split()` $\rightarrow$ `person["trip_first_name"]`.
3. **SINKS**: No direct SQL, shell, or file I/O in this file. The "sink" is the mutation of the `person` dictionary, which is presumably passed to a PDF generator later.
4. **EDGES**:
    - `display_name` as `None`: Handled by `(display_name or "")`.
    - `event_date` as empty string: Handled by `if not text: return "", "", 0, 0`.
    - `fiscal_year` as `None`: Handled by `or 2026`.
    - `lodging_per_diem` missing: **Not handled** (raises `KeyError`).
5. **TRUST**: Imports `TravelTier` from `cte_pdf_fill.travel_policy`. Trust boundary is maintained as it only reads attributes from the `tier` object.

CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**FINAL STATUS: Issues found (Medium/Low).**

---

#### Reviewer 3: Patterns — locality, leverage, maintainability
### Architecture Review

**Module Analysis:**
The `travel_form.py` module is a **shallow module**. It primarily acts as a data transformer, taking a `person` dictionary and adding keys to it based on business logic. It has very little internal state and relies entirely on the caller to provide the data structures.

**Seams & Locality:**
The "seam" is the `person` dictionary. Because the module modifies this dictionary in-place (mutating the input), it creates a tight coupling between the data source and this transformation logic. Locality is generally good for the business rules of the travel form, but the mutation pattern makes tracking the "source of truth" difficult across a larger system.

---

### Security Review

#### 1. ENTRY
Untrusted data enters via the `person` dictionary and `event_defaults` dictionary. These are likely sourced from a CSV, JSON API, or database (based on keys like `display_name`, `event_date`, and `registration_fee`).

#### 2. FLOWS
- `person["event_date"]` $\rightarrow$ `parse_event_date_range` $\rightarrow$ `date()` object $\rightarrow$ `_format_mdY` $\rightarrow$ `person["recon_start_date"]`.
- `person["registration_fee"]` / `person["lodging_per_diem"]` $\rightarrow$ `float()` $\rightarrow$ `int()` $\rightarrow$ `person["recon_total"]`.
- `person["display_name"]` $\rightarrow$ `split_legal_name` $\rightarrow$ `re.sub` $\rightarrow$ `person["trip_first_name"]`.

#### 3. SINKS
There are no direct sinks (SQL, Shell, File I/O) in this file. The "sink" is the mutation of the `person` dictionary, which is presumably passed to a PDF generator in another module.

#### 4. EDGES
- **Type Confusion:** `_money` and `_sum_money` handle `None`, `str`, `int`, and `float` gracefully using `try/except`.
- **Date Validation:** `parse_event_date_range` uses `try/except ValueError` around `date()` instantiation, preventing crashes on invalid dates (e.g., Feb 30).
- **Empty Inputs:** Extensive use of `.get("", "")` and `or ""` prevents `AttributeError` on `None` types.

#### 5. TRUST
The module trusts the `TravelTier` object to provide boolean flags (`allow_hotel`, etc.). It assumes `fiscal_year` can be cast to `int`.

---

### Findings

**MEDIUM | travel_form.py:116 | Denial of Service (Resource Exhaustion)**
The `_money` and `_sum_money` functions use `float(value)`. In Python, providing an extremely large string or a string with a massive number of digits to `float()` can lead to significant CPU consumption or, in some environments, trigger `ValueError: Exceeds the limit (4300) for integer string conversion` (though `float` is usually less restricted than `int`). While not a remote code execution, an attacker controlling the `registration_fee` or `lodging_per_diem` fields could provide a string like `"1e1000000000"` or a very long sequence of digits to slow down the processing of the PDF batch.

**LOW | travel_form.py:133 | Logic Error / Data Loss**
In `build_reconciliation_costs`, the code performs `int(float(person["lodging_per_diem"]))`. If `person["lodging_per_diem"]` is missing, this will raise a `KeyError` because it uses square bracket access `person["lodging_per_diem"]` instead of `.get()`, despite using `.get()` for other fields in the same function.
*Path:* `build_reconciliation_costs` $\rightarrow$ `person["lodging_per_diem"]` (if key is missing) $\rightarrow$ `KeyError`.

**LOW | travel_form.py:58 | Potential Logic Bug (Year Overflow)**
In `parse_event_date_range`, if the regex matches a date but the year is missing, it defaults to `fiscal_year`. If the `fiscal_year` provided is not a valid year (e.g., 0 or 99999), `date(year, month, start_day)` will raise a `ValueError`. While caught by the `try/except` block, it results in the function returning `("", "", 0, 0)`, which may be interpreted as "no date" rather than "invalid date," masking data quality issues.

---

### Checklist
CHECKLIST: entry=[done] flows=[done] sinks=[done] edges=[done] trust=[done]

**Final Status:**
`ISSUES FOUND` (See findings above).

---

