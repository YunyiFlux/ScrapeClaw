from typing import List, Dict, Any

TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate the probe browser to a target URL and wait for DOM load.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target webpage URL to visit."},
                    "wait_seconds": {"type": "integer", "description": "Seconds to wait after navigation for asynchronous content.", "default": 3}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the active browser page down to trigger lazy loading or infinite scrolling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "distance": {"type": "integer", "description": "Pixel distance to scroll down.", "default": 1000},
                    "wait_seconds": {"type": "integer", "description": "Seconds to wait after scroll for network calls.", "default": 2}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element matching the given CSS selector to trigger interactions or pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to click."},
                    "wait_seconds": {"type": "integer", "description": "Seconds to wait after click for network calls.", "default": 2}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_input",
            "description": "Fill text into an input field matching the CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input field."},
                    "text": {"type": "string", "description": "Text to fill into the input."},
                    "press_enter": {"type": "boolean", "description": "Whether to press Enter after typing.", "default": False}
                },
                "required": ["selector", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_inspect_dom",
            "description": "Inspect DOM elements matching a CSS selector, returning tag names, text, and attributes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to search for in DOM."},
                    "max_elements": {"type": "integer", "description": "Maximum matching elements to return.", "default": 10}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "traffic_list",
            "description": "List captured background network requests, filtered by candidates likely to be data APIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max requests to return.", "default": 15},
                    "only_json": {"type": "boolean", "description": "Filter for JSON content-type only.", "default": True}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "traffic_inspect",
            "description": "Inspect detailed request face and distilled JSON schema for a specific traffic ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "traffic_id": {"type": "string", "description": "The ID of the traffic entry, e.g., 't003'"}
                },
                "required": ["traffic_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "diff_probe_headers",
            "description": "Prune redundant browser headers by sending differential requests, finding minimal required headers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "traffic_id": {"type": "string", "description": "The base traffic ID to optimize."},
                    "keep_cookies": {"type": "boolean", "description": "Whether to test keeping or stripping cookies.", "default": True}
                },
                "required": ["traffic_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_js_crypto",
            "description": (
                "Inspect intercepted client-side JavaScript cryptographic operations, "
                "such as subtleCrypto, btoa/atob, CryptoJS, custom sign() functions, and "
                "signature HTTP headers (e.g., X-Bogus, _signature, token)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_type": {
                        "type": "string",
                        "description": "Optional filter by function category or name, e.g., 'hash', 'encrypt', 'base64', 'sign_header', or 'CryptoJS.MD5'."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent crypto snapshots to inspect (default: 20).",
                        "default": 20
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_js_snippet",
            "description": (
                "Execute an isolated JavaScript snippet in the sandboxed JSRuntime (Node.js) "
                "or browser RPC to verify extracted reverse-engineered signing logic, decode payloads, "
                "or test algorithm equivalence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The JavaScript code snippet or function expression to execute."
                    },
                    "context_vars": {
                        "type": "object",
                        "description": "Optional dictionary of variable name -> value to inject into global context."
                    },
                    "expected_output": {
                        "type": "string",
                        "description": "Optional expected signature/output string to verify equivalence against."
                    },
                    "use_browser_rpc": {
                        "type": "boolean",
                        "description": "If true, execute directly in the live browser page context via BrowserRPCBridge (for Wasm/Webpack bindings). Default is false (offline Node.js sandbox).",
                        "default": False
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "infer_pagination",
            "description": "Analyze differential requests after scrolling/paging to deduce pagination parameters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base_traffic_id": {"type": "string", "description": "Traffic ID of page 1."},
                    "next_traffic_id": {"type": "string", "description": "Traffic ID of page 2."}
                },
                "required": ["base_traffic_id", "next_traffic_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "synthesize_crawler",
            "description": "Render and save a complete standalone Python crawler script based on analyzed specs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_api_url": {"type": "string", "description": "The underlying private API URL."},
                    "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                    "minimal_headers": {"type": "object", "description": "Dict of pruned minimal required headers."},
                    "minimal_cookies": {"type": "object", "description": "Dict of required cookies (if any)."},
                    "query_params": {"type": "object", "description": "Query parameters dictionary."},
                    "pagination_param": {"type": "string", "description": "Param name for pagination, e.g., 'page' or 'offset'."},
                    "pagination_step": {"type": "integer", "description": "Step per page increment.", "default": 1},
                    "data_jsonpath": {"type": "string", "description": "JSONPath to the target item list, e.g., 'data.items'"},
                    "sign_js_code": {"type": "string", "description": "Optional standalone JavaScript code snippet to compute dynamic signature."},
                    "sign_header_name": {"type": "string", "description": "Optional HTTP header name to populate with signature (e.g. 'X-Signature')."},
                    "sign_param_name": {"type": "string", "description": "Optional query param name to populate with signature (e.g. '_sign')."}
                },
                "required": ["target_api_url", "minimal_headers", "data_jsonpath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_custom_crawler",
            "description": (
                "Write a fully custom Python crawler script when the standard template "
                "cannot handle the API pattern (e.g., two-stage ID-to-detail fetching, "
                "cursor-chain pagination, WebSocket, dynamic signing). "
                "The code must: (1) use httpx for HTTP, (2) output a JSON array to stdout, "
                "(3) accept --max-pages and --output CLI args. "
                "Code is AST-checked for safety and written to disk. "
                "You MUST call execute_crawler_sandbox after this to verify."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete Python crawler script source code."
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the crawling strategy."
                    },
                    "auxiliary_files": {
                        "type": "object",
                        "description": "Optional mapping of filename -> file content for auxiliary assets (e.g. {'sign.js': '...'})."
                    }
                },
                "required": ["code", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_crawler_sandbox",
            "description": "Run the synthesized crawler script in a subprocess sandbox to physically verify execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_path": {"type": "string", "description": "File path to the synthesized crawler script."}
                },
                "required": ["script_path"]
            }
        }
    }
]
