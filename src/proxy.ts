import { NextRequest, NextResponse } from "next/server";

import { localApiRejection } from "@/lib/server/local-request-policy";

const LOCAL_RESPONSE_HEADERS = {
  "Cache-Control": "no-store, max-age=0",
  Pragma: "no-cache",
  Expires: "0",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Resource-Policy": "same-origin",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
} as const;

function withLocalHeaders(response: NextResponse): NextResponse {
  for (const [name, value] of Object.entries(LOCAL_RESPONSE_HEADERS)) {
    response.headers.set(name, value);
  }
  return response;
}

export function proxy(request: NextRequest): NextResponse {
  if (process.env.SNIPER_EXECUTION_MODE !== "local") {
    return NextResponse.next();
  }

  const rejection = localApiRejection({
    method: request.method,
    pathname: request.nextUrl.pathname,
    protocol: request.nextUrl.protocol,
    host: request.headers.get("host"),
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
    contentType: request.headers.get("content-type"),
  });

  if (rejection) {
    const response = NextResponse.json(
      { error: rejection.error },
      { status: rejection.status },
    );
    return withLocalHeaders(response);
  }

  return withLocalHeaders(NextResponse.next());
}

export const config = {
  matcher: "/api/:path*",
};
