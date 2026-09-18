"""Playwright Browser Anti-Bot Stealth Script."""

STEALTH_JS = """
// 1. Erase navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});

// 2. Mock chrome runtime object
if (!window.chrome) {
    window.chrome = {
        runtime: {},
        app: {},
        loadTimes: function() { return {}; },
        csi: function() { return {}; }
    };
}

// 3. Mock navigator.languages and plugins
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
    configurable: true
});

if (navigator.plugins.length === 0) {
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
        configurable: true
    });
}

// 4. Mock WebGL vendor & renderer
try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) {
            return 'Intel Inc.';
        }
        if (parameter === 37446) {
            return 'Intel(R) Iris(R) Xe Graphics';
        }
        return getParameter.apply(this, [parameter]);
    };
} catch(e) {}
"""

def get_stealth_js() -> str:
    """Return anti-bot detection JavaScript injection string."""
    return STEALTH_JS
