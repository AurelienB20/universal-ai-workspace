import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// Content Security Policy. The page loads nothing from another origin: scripts,
// styles and fonts (next/font self-hosts them) come from this server, and the browser
// only calls this server's /api routes. Links to GitHub are plain navigations.
//
// Trade-off: 'unsafe-inline' scripts, as Next.js documents for static pages. A nonce
// would force rendering the page on every request. The risk it leaves is limited:
// untrusted content (answers quoting repositories) is rendered by react-markdown,
// which escapes HTML, and nothing uses dangerouslySetInnerHTML. 'unsafe-eval' is only
// for React's debugging tools in development.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

// HTTPS-only headers (HSTS) belong to the reverse proxy that terminates TLS.
const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" }, // older browsers; CSP frame-ancestors for others
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
];

const nextConfig: NextConfig = {
  // Self-contained server in .next/standalone, for the Docker image.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
