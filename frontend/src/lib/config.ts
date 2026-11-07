/**
 * Frontend configuration module.
 *
 * Exposes a typed configuration object validated from environment variables.
 * Note: NEXT_PUBLIC_* variables are embedded into client bundles at build time.
 */

export interface FrontendConfig {
  readonly apiBaseUrl: string;
}

/**
 * Validates that the provided URL string has an http: or https: scheme and strips any trailing slash.
 * Defaults to http://localhost:8000 if input is omitted or empty.
 */
export function validateAndNormalizeApiBaseUrl(
  urlStr?: string,
  defaultUrl: string = "http://localhost:8000"
): string {
  const target = urlStr && urlStr.trim() ? urlStr.trim() : defaultUrl;

  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    throw new Error(
      `Invalid NEXT_PUBLIC_API_BASE_URL: "${target}" is not a valid URL.`
    );
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(
      `Invalid NEXT_PUBLIC_API_BASE_URL: Protocol must be "http:" or "https:", received "${parsed.protocol}".`
    );
  }

  // Strip any trailing slash
  return target.replace(/\/+$/, "");
}

export const config: FrontendConfig = {
  apiBaseUrl: validateAndNormalizeApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL),
};

export default config;
