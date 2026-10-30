
# SQL Injection Testing Toolkit

A Python-based toolkit for authorized SQL injection testing and web application security research.

This project was developed to explore and automate repetitive SQL injection testing workflows while keeping the testing process configurable and understandable.

## Features

### Input Handling

- URL parameter testing
- POST form input testing
- Cookie and HTTP header testing
- Automatic form discovery where supported

### SQL Injection Testing

- Boolean-based testing workflows
- Error-based detection
- Time-based detection
- UNION-related testing helpers
- Column counting and data type probing
- Database version-related checks

### Payload Processing

- Case variation
- Inline comment transformations
- Hexadecimal and character encoding
- Unicode and entity transformations
- Alternative keyword representations
- Configurable encoding layers

### Target Management

- Save frequently used targets locally
- Store labels and notes
- Reuse target configurations

### Browser Integration

Optional Playwright integration can open selected responses in Chromium for manual inspection.

## Technologies

- Python
- Requests
- BeautifulSoup
- Playwright (optional)

## Installation

Clone the repository:

```bash
git clone https://github.com/sudoxs/SQL_Injection_tool.git
cd SQL_Injection_tool
```

Install the main dependencies:

```bash
pip install requests beautifulsoup4
```

For optional browser integration:

```bash
pip install playwright
playwright install chromium
```

## Usage

Start the interactive application:

```bash
python SQLI.py
```

The application provides an interactive workflow for preparing requests, selecting injection points, managing payloads, and reviewing responses.

## Project Structure

```text
SQL_Injection_tool/
│
├── SQLI.py
├── targets.json
├── payloads/
└── errors/
```

`targets.json`, `payloads/`, and `errors/` are used for local target storage and optional custom payload or error-pattern resources.

## Testing

Automated tests are being added to cover deterministic helper functions, input parsing, encoding utilities, and payload-processing behavior.

Run the test suite with:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Limitations

- SQL injection detection is based on response behavior and configured heuristics.
- Results require manual validation before being considered confirmed vulnerabilities.
- Different database engines and application behavior may require different testing approaches.
- Automated results should not replace manual security analysis.

## Responsible Use

This project is intended for authorized security testing, controlled lab environments, and educational research.

Only test systems that you own or have explicit permission to assess.

The author is not responsible for unauthorized use or damage resulting from misuse of this tool.

## Author

**Shayan Ghasemi**

GitHub: https://github.com/sudoxs

Portfolio: https://sudoxs.github.io/sudoxsweb/
